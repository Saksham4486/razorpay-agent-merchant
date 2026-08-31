import uuid
import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import CatalogItem, utcnow
from backend.app.schemas import (
    AcpFeedResponse, AcpProductItem,
    AcpCheckoutSessionCreate, AcpCheckoutSessionUpdate, AcpCheckoutSessionResponse,
    CheckoutRequest
)
from backend.app.routes.checkout import create_checkout
from backend.app.policy_engine import check_policy, PolicyStatus
from backend.app.config import settings

router = APIRouter(prefix="/acp", tags=["Agentic Commerce Protocol (ACP)"])

# In-memory ACP checkout session store (backed by merchant policy & order engine)
ACP_SESSIONS: Dict[str, Dict[str, Any]] = {}

@router.get("/feed", response_model=AcpFeedResponse)
def get_acp_catalog_feed(db: Session = Depends(get_db)):
    """
    ACP (Agentic Commerce Protocol) Standard Product Feed:
    Exposes an agent-readable catalog feed adhering to ACP product discovery conventions.
    """
    items = db.query(CatalogItem).all()
    acp_items = [
        AcpProductItem(
            id=item.sku,
            title=item.name,
            description=item.description,
            price=item.price_inr,
            currency=item.currency,
            availability="in_stock" if item.stock > 0 else "out_of_stock",
            max_discount_pct=item.max_discount_pct,
            requires_approval_above=item.requires_approval_above_inr
        )
        for item in items
    ]

    return AcpFeedResponse(
        protocol="ACP-1.0-draft",
        merchant_name=settings.APP_NAME,
        feed_timestamp=utcnow(),
        items=acp_items
    )

@router.post("/checkout_sessions", response_model=AcpCheckoutSessionResponse)
def create_acp_checkout_session(
    req: AcpCheckoutSessionCreate,
    db: Session = Depends(get_db)
):
    """
    ACP Checkout Session Lifecycle — Create:
    Initiates an agent checkout session, evaluating merchant policy invariants.
    """
    item = db.query(CatalogItem).filter(CatalogItem.sku == req.sku).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{req.sku}' not found in ACP feed")

    # Evaluate Policy
    decision = check_policy(
        sku_price=item.price_inr,
        max_sku_discount_pct=item.max_discount_pct,
        requested_discount_pct=req.requested_discount_pct,
        quantity=req.quantity,
        base_approval_threshold=item.requires_approval_above_inr,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=settings.DAILY_MERCHANT_SPEND_CAP_INR,
        min_order_inr=item.min_order_inr
    )

    session_id = f"acp_cs_{uuid.uuid4().hex[:16]}"
    expires_at = utcnow() + datetime.timedelta(minutes=15)

    session_data = {
        "session_id": session_id,
        "status": "open",
        "sku": req.sku,
        "quantity": req.quantity,
        "requested_discount_pct": req.requested_discount_pct,
        "unit_price_inr": decision.final_unit_price,
        "total_amount_inr": decision.total_order_value,
        "policy_status": decision.status.value,
        "policy_reason": decision.reason,
        "agent_id": req.agent_id,
        "mandate": req.mandate,
        "mandate_signature": req.mandate_signature,
        "expires_at": expires_at,
        "razorpay_order_id": None
    }
    ACP_SESSIONS[session_id] = session_data

    return AcpCheckoutSessionResponse(
        session_id=session_id,
        status="open",
        sku=req.sku,
        quantity=req.quantity,
        unit_price_inr=decision.final_unit_price,
        total_amount_inr=decision.total_order_value,
        policy_status=decision.status.value,
        policy_reason=decision.reason,
        expires_at=expires_at
    )

@router.post("/checkout_sessions/{session_id}", response_model=AcpCheckoutSessionResponse)
def update_acp_checkout_session(
    session_id: str,
    req: AcpCheckoutSessionUpdate,
    db: Session = Depends(get_db)
):
    """
    ACP Checkout Session Lifecycle — Update:
    Updates quantity or requested discount, re-evaluating policy invariants.
    """
    session = ACP_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ACP checkout session not found")

    if session["status"] != "open":
        raise HTTPException(status_code=400, detail=f"Cannot update session in '{session['status']}' state")

    sku = session["sku"]
    item = db.query(CatalogItem).filter(CatalogItem.sku == sku).first()
    qty = req.quantity if req.quantity is not None else session["quantity"]
    disc = req.requested_discount_pct if req.requested_discount_pct is not None else session["requested_discount_pct"]

    decision = check_policy(
        sku_price=item.price_inr,
        max_sku_discount_pct=item.max_discount_pct,
        requested_discount_pct=disc,
        quantity=qty,
        base_approval_threshold=item.requires_approval_above_inr,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=settings.DAILY_MERCHANT_SPEND_CAP_INR,
        min_order_inr=item.min_order_inr
    )

    session["quantity"] = qty
    session["requested_discount_pct"] = disc
    session["unit_price_inr"] = decision.final_unit_price
    session["total_amount_inr"] = decision.total_order_value
    session["policy_status"] = decision.status.value
    session["policy_reason"] = decision.reason

    return AcpCheckoutSessionResponse(
        session_id=session_id,
        status=session["status"],
        sku=sku,
        quantity=qty,
        unit_price_inr=decision.final_unit_price,
        total_amount_inr=decision.total_order_value,
        policy_status=decision.status.value,
        policy_reason=decision.reason,
        expires_at=session["expires_at"]
    )

@router.post("/checkout_sessions/{session_id}/complete", response_model=AcpCheckoutSessionResponse)
def complete_acp_checkout_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    ACP Checkout Session Lifecycle — Complete:
    Finalizes the session by executing checkout through the core payment engine.
    """
    session = ACP_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ACP checkout session not found")

    if session["status"] != "open":
        raise HTTPException(status_code=400, detail=f"Cannot complete session in '{session['status']}' state")

    idemp_key = f"acp_idemp_{session_id}"
    chk_req = CheckoutRequest(
        sku=session["sku"],
        quantity=session["quantity"],
        requested_discount_pct=session["requested_discount_pct"],
        actor_type="ai_agent",
        agent_id=session["agent_id"] or "acp_buyer_agent",
        idempotency_key=idemp_key,
        customer_name="ACP Autonomous Buyer Agent",
        mandate=session.get("mandate"),
        mandate_signature=session.get("mandate_signature")
    )

    chk_res = create_checkout(chk_req, db=db)
    session["status"] = "completed"
    session["razorpay_order_id"] = chk_res.razorpay_order_id

    return AcpCheckoutSessionResponse(
        session_id=session_id,
        status="completed",
        sku=session["sku"],
        quantity=session["quantity"],
        unit_price_inr=chk_res.unit_price_inr,
        total_amount_inr=chk_res.total_amount_inr,
        policy_status="approved",
        policy_reason=chk_res.policy_reason,
        razorpay_order_id=chk_res.razorpay_order_id,
        razorpay_key_id=chk_res.razorpay_key_id,
        expires_at=chk_res.expires_at or session["expires_at"]
    )

@router.post("/checkout_sessions/{session_id}/cancel")
def cancel_acp_checkout_session(session_id: str):
    """
    ACP Checkout Session Lifecycle — Cancel.
    """
    session = ACP_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ACP checkout session not found")
    session["status"] = "cancelled"
    return {"session_id": session_id, "status": "cancelled", "message": "ACP checkout session cancelled."}
