import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import CatalogItem
from backend.app.schemas import NegotiateRequest, NegotiateResponse
from backend.app.policy_engine import check_policy, PolicyStatus
from backend.app.services.trust_service import get_or_create_trust_score
from backend.app.services.mandate_service import evaluate_buyer_mandate
from backend.app.services.audit_service import record_audit_log
from backend.app.middleware.auth import verify_or_provision_agent_key, check_rate_limit
from backend.app.config import settings

router = APIRouter(prefix="/api/negotiate", tags=["Negotiation"])

# Concurrency lock for SQLite policy evaluation critical section
POLICY_LOCK = threading.Lock()

@router.post("", response_model=NegotiateResponse)
def negotiate_price(
    req: NegotiateRequest,
    request: Request = None,
    x_agent_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Evaluates requested discount against:
    1. AP2 Signed Buyer Mandate (if present)
    2. Pure Merchant Policy Engine
    Returns deterministic, explainable approval/rejection reason.
    """
    # 1. Rate Limiting
    if request:
        check_rate_limit(request, req.agent_id)

    # 2. Agent Authentication
    issued_agent_key = None
    if req.agent_id:
        issued_agent_key = verify_or_provision_agent_key(req.agent_id, x_agent_key, db)

    # 3. Lookup SKU
    item = db.query(CatalogItem).filter(CatalogItem.sku == req.sku).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{req.sku}' not found in catalog")

    # 4. AP2 Mandate Evaluation (Pre-policy check)
    mandate_ok, mandate_reason = evaluate_buyer_mandate(
        mandate=req.mandate,
        signature=req.mandate_signature,
        sku=req.sku,
        quantity=req.quantity,
        requested_discount_pct=req.requested_discount_pct
    )
    if not mandate_ok:
        actor_name = f"ai_agent:{req.agent_id}" if req.agent_id else "ad_human"
        record_audit_log(
            db=db,
            actor=actor_name,
            agent_id=req.agent_id,
            sku=item.sku,
            requested_discount=req.requested_discount_pct,
            order_value_inr=item.price_inr * req.quantity,
            policy_decision="rejected",
            reason=mandate_reason,
            status="mandate_rejected",
            failure_detail="AP2MandateViolation"
        )
        db.commit()
        return NegotiateResponse(
            sku=item.sku,
            original_price_inr=item.price_inr,
            requested_discount_pct=req.requested_discount_pct,
            approved_discount_pct=0.0,
            final_unit_price_inr=item.price_inr,
            total_order_value_inr=item.price_inr * req.quantity,
            policy_status="rejected",
            allowed=False,
            reason=mandate_reason,
            requires_approval=False,
            effective_approval_threshold_inr=item.requires_approval_above_inr,
            mandate_verified=False,
            issued_agent_key=issued_agent_key
        )

    # 5. Fetch Agent Trust Score
    trust_score = None
    if req.agent_id:
        trust_record = get_or_create_trust_score(db, req.agent_id)
        trust_score = trust_record.trust_score

    # 6. Policy Check with Threading Lock (Avoid TOCTOU in SQLite)
    with POLICY_LOCK:
        # Import checkout daily spend calculator
        from backend.app.routes.checkout import get_current_daily_spend
        daily_spend = get_current_daily_spend(db)

        decision = check_policy(
            sku_price=item.price_inr,
            max_sku_discount_pct=item.max_discount_pct,
            requested_discount_pct=req.requested_discount_pct,
            quantity=req.quantity,
            base_approval_threshold=item.requires_approval_above_inr,
            agent_trust_score=trust_score,
            current_daily_spend=daily_spend,
            daily_spend_cap=settings.DAILY_MERCHANT_SPEND_CAP_INR,
            min_order_inr=item.min_order_inr
        )

    actor_name = f"ai_agent:{req.agent_id}" if req.agent_id else "ad_human"
    record_audit_log(
        db=db,
        actor=actor_name,
        agent_id=req.agent_id,
        sku=item.sku,
        requested_discount=req.requested_discount_pct,
        order_value_inr=decision.total_order_value,
        policy_decision=decision.status.value,
        reason=decision.reason,
        status="negotiated",
        metadata={"mandate_present": req.mandate is not None}
    )
    db.commit()

    return NegotiateResponse(
        sku=item.sku,
        original_price_inr=item.price_inr,
        requested_discount_pct=req.requested_discount_pct,
        approved_discount_pct=decision.approved_discount_pct,
        final_unit_price_inr=decision.final_unit_price,
        total_order_value_inr=decision.total_order_value,
        policy_status=decision.status.value,
        allowed=decision.status in [PolicyStatus.APPROVED, PolicyStatus.PENDING_APPROVAL],
        reason=decision.reason,
        requires_approval=(decision.status == PolicyStatus.PENDING_APPROVAL),
        agent_trust_score=trust_score,
        effective_approval_threshold_inr=decision.effective_approval_threshold,
        mandate_verified=True if req.mandate else None,
        issued_agent_key=issued_agent_key
    )
