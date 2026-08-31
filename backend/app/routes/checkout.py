import json
import uuid
import datetime
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from backend.app.database import get_db
from backend.app.models import CatalogItem, Order, IdempotencyRecord, utcnow
from backend.app.schemas import CheckoutRequest, CheckoutResponse
from backend.app.policy_engine import check_policy, PolicyStatus
from backend.app.services.trust_service import get_or_create_trust_score
from backend.app.services.payment_service import payment_service
from backend.app.services.mandate_service import evaluate_buyer_mandate
from backend.app.services.audit_service import record_audit_log
from backend.app.middleware.auth import verify_or_provision_agent_key, check_rate_limit
from backend.app.config import settings

router = APIRouter(prefix="/api/checkout", tags=["Checkout"])

CHECKOUT_LOCK = threading.Lock()

def get_current_daily_spend(db: Session) -> float:
    today_start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = db.query(func.sum(Order.total_amount_inr)).filter(
        Order.created_at >= today_start,
        Order.status.in_(["paid", "pending_payment", "pending_approval", "pending_confirmation"])
    ).scalar()
    return float(total or 0.0)

@router.post("", response_model=CheckoutResponse)
def create_checkout(
    req: CheckoutRequest,
    request: Request = None,
    x_agent_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Executes transactional checkout with:
    1. Idempotency verification (with IntegrityError race condition handling)
    2. Rate limiting & Agent key authentication
    3. AP2 Signed Buyer Mandate validation
    4. Mutex-guarded Policy Engine evaluation (TOCTOU spend protection)
    5. Real Razorpay Test Order creation (no fake links)
    6. Tamper-evident hash-chained audit logging
    """
    # 1. Rate Limiting
    if request:
        check_rate_limit(request, req.agent_id)

    with CHECKOUT_LOCK:
        # 2. Early Idempotency Check
        existing_idempotency = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == req.idempotency_key
        ).first()
        
        if existing_idempotency:
            cached_data = json.loads(existing_idempotency.response_json)
            cached_data["idempotent_replay"] = True
            return CheckoutResponse(**cached_data)

        # 3. Agent Authentication
        if req.agent_id:
            verify_or_provision_agent_key(req.agent_id, x_agent_key, db)

        # 4. SKU Lookup
        item = db.query(CatalogItem).filter(CatalogItem.sku == req.sku).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"SKU '{req.sku}' not found in catalog")

        # 5. AP2 Mandate Evaluation
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
            raise HTTPException(
                status_code=400,
                detail={"error": "MandateViolation", "reason": mandate_reason}
            )

        # 6. Trust Score Lookup
        trust_score = None
        if req.agent_id:
            trust_record = get_or_create_trust_score(db, req.agent_id)
            trust_score = trust_record.trust_score

        actor_name = f"ai_agent:{req.agent_id}" if req.agent_id else "ad_human"
        order_ref = f"ORD_{uuid.uuid4().hex[:10].upper()}"
        ttl_mins = req.ttl_minutes or 15
        expires_at = utcnow() + datetime.timedelta(minutes=ttl_mins)

        # 7. Policy Engine Evaluation
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

        if decision.status == PolicyStatus.REJECTED:
            record_audit_log(
                db=db,
                actor=actor_name,
                agent_id=req.agent_id,
                sku=item.sku,
                requested_discount=req.requested_discount_pct,
                order_value_inr=decision.total_order_value,
                policy_decision="rejected",
                reason=decision.reason,
                status="rejected",
                failure_detail="Order rejected by Merchant Policy Engine"
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "PolicyViolation",
                    "reason": decision.reason,
                    "max_allowable_discount": item.max_discount_pct
                }
            )

        # Gated vs Approved
        if decision.status == PolicyStatus.PENDING_APPROVAL:
            order_status = "pending_approval"
            rzp_order_id = None
        else:
            order_status = "pending_payment"
            rzp_res = payment_service.create_order(
                amount_inr=decision.total_order_value,
                order_reference=order_ref,
                notes={
                    "actor": actor_name,
                    "sku": item.sku,
                    "discount_pct": decision.approved_discount_pct,
                    "expires_at": expires_at.isoformat()
                }
            )
            rzp_order_id = rzp_res["razorpay_order_id"]

        new_order = Order(
            order_reference=order_ref,
            actor=actor_name,
            agent_id=req.agent_id,
            sku=item.sku,
            quantity=req.quantity,
            unit_price_inr=decision.final_unit_price,
            requested_discount_pct=req.requested_discount_pct,
            approved_discount_pct=decision.approved_discount_pct,
            total_amount_inr=decision.total_order_value,
            status=order_status,
            razorpay_order_id=rzp_order_id,
            idempotency_key=req.idempotency_key,
            policy_reason=decision.reason,
            expires_at=expires_at,
            is_link_active=True
        )
        db.add(new_order)

        # Audit Log
        record_audit_log(
            db=db,
            actor=actor_name,
            agent_id=req.agent_id,
            sku=item.sku,
            requested_discount=req.requested_discount_pct,
            order_value_inr=decision.total_order_value,
            policy_decision=decision.status.value,
            reason=decision.reason,
            razorpay_order_id=rzp_order_id,
            status=order_status,
            metadata={
                "order_reference": order_ref,
                "idempotency_key": req.idempotency_key,
                "expires_at": expires_at.isoformat()
            }
        )

        response_obj = CheckoutResponse(
            order_reference=order_ref,
            sku=item.sku,
            quantity=req.quantity,
            unit_price_inr=decision.final_unit_price,
            discount_pct=decision.approved_discount_pct,
            total_amount_inr=decision.total_order_value,
            status=order_status,
            razorpay_order_id=rzp_order_id,
            razorpay_key_id=settings.RAZORPAY_KEY_ID,
            idempotent_replay=False,
            policy_reason=decision.reason,
            expires_at=expires_at,
            is_link_active=True,
            created_at=new_order.created_at or utcnow()
        )

        idempotency_entry = IdempotencyRecord(
            idempotency_key=req.idempotency_key,
            actor=actor_name,
            request_hash=f"{req.sku}:{req.quantity}:{req.requested_discount_pct}",
            order_reference=order_ref,
            response_json=response_obj.model_dump_json()
        )
        db.add(idempotency_entry)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing_record = db.query(IdempotencyRecord).filter(
                IdempotencyRecord.idempotency_key == req.idempotency_key
            ).first()
            if existing_record:
                cached_data = json.loads(existing_record.response_json)
                cached_data["idempotent_replay"] = True
                return CheckoutResponse(**cached_data)
            raise HTTPException(status_code=500, detail="Concurrent checkout idempotency race failure")

    return response_obj
