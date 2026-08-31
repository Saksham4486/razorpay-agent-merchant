import json
import logging
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import Order, utcnow
from backend.app.schemas import FallbackPollResponse, VerifyPaymentRequest, RefundRequest, RefundResponse
from backend.app.services.payment_service import payment_service
from backend.app.services.trust_service import record_agent_order_outcome
from backend.app.services.audit_service import record_audit_log

logger = logging.getLogger("orders_route")
router = APIRouter(prefix="/api/orders", tags=["Orders"])

def expire_order_if_due(order: Order, db: Session) -> bool:
    """
    Shared helper to check and expire orders whose TTL has elapsed.
    Returns True if expired, False otherwise.
    """
    now = utcnow()
    if order.status == "pending_payment" and order.expires_at:
        exp = order.expires_at.replace(tzinfo=datetime.timezone.utc) if order.expires_at.tzinfo is None else order.expires_at
        if now > exp:
            order.status = "expired"
            order.is_link_active = False
            order.updated_at = now
            
            record_audit_log(
                db=db,
                actor=order.actor,
                agent_id=order.agent_id,
                sku=order.sku,
                requested_discount=order.requested_discount_pct,
                order_value_inr=order.total_amount_inr,
                policy_decision="rejected",
                reason=f"⌛ Payment link TTL elapsed for order {order.order_reference}. Link is permanently DEAD.",
                razorpay_order_id=order.razorpay_order_id,
                status="expired",
                failure_detail="Payment Link Expired (TTL Timeout)"
            )
            return True
    return False

@router.get("/{order_ref}")
def get_order(order_ref: str, db: Session = Depends(get_db)):
    """
    Query order details, expiration TTL, and link active status.
    """
    order = db.query(Order).filter(
        (Order.order_reference == order_ref) | (Order.razorpay_order_id == order_ref)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if expire_order_if_due(order, db):
        db.commit()

    return {
        "id": order.id,
        "order_reference": order.order_reference,
        "actor": order.actor,
        "agent_id": order.agent_id,
        "sku": order.sku,
        "quantity": order.quantity,
        "unit_price_inr": order.unit_price_inr,
        "total_amount_inr": order.total_amount_inr,
        "status": order.status,
        "razorpay_order_id": order.razorpay_order_id,
        "razorpay_payment_id": order.razorpay_payment_id,
        "refund_id": order.refund_id,
        "refund_amount_inr": order.refund_amount_inr,
        "policy_reason": order.policy_reason,
        "expires_at": order.expires_at,
        "is_link_active": order.is_link_active,
        "created_at": order.created_at,
        "updated_at": order.updated_at
    }

@router.post("/{order_ref}/verify-payment")
def verify_client_payment(
    order_ref: str,
    req: VerifyPaymentRequest,
    db: Session = Depends(get_db)
):
    """
    Single-Use Payment Link, TTL Guard & Cryptographic Signature Verification:
    1. Rejects if order is already PAID (prevents multiple payments on same link).
    2. Rejects if payment link has EXPIRED.
    3. Verifies Razorpay HMAC SHA256 signature (rejects forged/tampered requests).
    4. On successful verification, marks order PAID and permanently deactivates link.
    """
    order = db.query(Order).filter(
        (Order.order_reference == order_ref) | (Order.razorpay_order_id == order_ref)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    now = utcnow()

    # Invariant 1: Prevent multiple payments on already fulfilled link
    if order.status == "paid" or not order.is_link_active:
        record_audit_log(
            db=db,
            actor=order.actor,
            agent_id=order.agent_id,
            sku=order.sku,
            requested_discount=order.requested_discount_pct,
            order_value_inr=order.total_amount_inr,
            policy_decision="rejected",
            reason=f"🚫 Blocked duplicate payment attempt on already DEAD/FULFILLED payment link for order {order.order_reference}.",
            razorpay_order_id=order.razorpay_order_id,
            status="paid",
            failure_detail="Rejected Multi-Payment on Dead Link"
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "DeadPaymentLink",
                "message": "This payment link is DEAD. The order has already been paid and fulfilled. Multiple payments on the same link are strictly blocked. To buy more units, please initiate a new checkout.",
                "order_reference": order.order_reference,
                "status": "paid",
                "is_link_active": False
            }
        )

    # Invariant 2: Enforce Time-To-Pay (TTL) Expiration
    if expire_order_if_due(order, db):
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "LinkExpired",
                "message": "Payment link has EXPIRED and is now dead. Please create a new checkout to proceed.",
                "order_reference": order.order_reference,
                "status": "expired",
                "is_link_active": False
            }
        )

    # Invariant 3: Real Cryptographic Signature Verification
    rzp_order_id = req.razorpay_order_id or order.razorpay_order_id or ""
    is_valid_signature = payment_service.verify_payment_signature(
        razorpay_order_id=rzp_order_id,
        razorpay_payment_id=req.razorpay_payment_id,
        razorpay_signature=req.razorpay_signature
    )
    
    if not is_valid_signature:
        record_audit_log(
            db=db,
            actor=order.actor,
            agent_id=order.agent_id,
            sku=order.sku,
            requested_discount=order.requested_discount_pct,
            order_value_inr=order.total_amount_inr,
            policy_decision="rejected",
            reason=f"🚫 Forged/invalid payment signature rejected for order {order.order_reference}.",
            razorpay_order_id=rzp_order_id,
            status="pending_payment",
            failure_detail="InvalidPaymentSignature"
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "InvalidPaymentSignature",
                "message": "Razorpay payment signature verification failed. The payment signature is forged or mismatched."
            }
        )

    # Invariant 4: Fulfill Payment & Kill Link
    order.status = "paid"
    order.is_link_active = False  # Link is now permanently DEAD for further payments
    order.razorpay_payment_id = req.razorpay_payment_id
    order.updated_at = now

    record_audit_log(
        db=db,
        actor=order.actor,
        agent_id=order.agent_id,
        sku=order.sku,
        requested_discount=order.requested_discount_pct,
        order_value_inr=order.total_amount_inr,
        policy_decision="approved",
        reason=f"💳 Cryptographically verified payment ({req.razorpay_payment_id}) for order {order.order_reference}. Payment link permanently DEACTIVATED.",
        razorpay_order_id=order.razorpay_order_id,
        status="paid",
        metadata={
            "payment_id": req.razorpay_payment_id,
            "order_id": rzp_order_id,
            "signature_verified": True,
            "link_deactivated": True
        }
    )

    if order.agent_id:
        record_agent_order_outcome(db, order.agent_id, "paid")

    db.commit()

    return {
        "status": "paid",
        "order_reference": order.order_reference,
        "razorpay_payment_id": req.razorpay_payment_id,
        "is_link_active": False,
        "message": "Payment verified successfully via HMAC SHA256! Link has been deactivated."
    }

@router.post("/{order_ref}/refund", response_model=RefundResponse)
def refund_order(
    order_ref: str,
    req: RefundRequest,
    db: Session = Depends(get_db)
):
    """
    Executes a refund on a PAID order via Razorpay Refunds API.
    Transitions order to REFUNDED and logs explainable audit entry.
    """
    order = db.query(Order).filter(
        (Order.order_reference == order_ref) | (Order.razorpay_order_id == order_ref)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "paid":
        raise HTTPException(status_code=400, detail=f"Cannot refund order in '{order.status}' status. Only PAID orders can be refunded.")

    if not order.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Missing payment_id for refund execution.")

    refund_amount = req.amount_inr or order.total_amount_inr
    
    # Execute refund via Razorpay
    rzp_refund = payment_service.create_refund(
        payment_id=order.razorpay_payment_id,
        amount_inr=refund_amount,
        notes={"order_reference": order.order_reference, "reason": req.reason}
    )

    order.status = "refunded"
    order.refund_id = rzp_refund["refund_id"]
    order.refund_amount_inr = refund_amount
    order.updated_at = utcnow()

    record_audit_log(
        db=db,
        actor="merchant_admin",
        agent_id=order.agent_id,
        sku=order.sku,
        requested_discount=order.requested_discount_pct,
        order_value_inr=order.total_amount_inr,
        policy_decision="approved",
        reason=f"🔄 Order {order.order_reference} refunded (₹{refund_amount:,.2f}) via Razorpay. Refund ID: {order.refund_id}. Reason: {req.reason}.",
        razorpay_order_id=order.razorpay_order_id,
        status="refunded",
        metadata={"refund_id": order.refund_id, "amount_inr": refund_amount, "reason": req.reason}
    )
    db.commit()

    return RefundResponse(
        order_reference=order.order_reference,
        refund_id=order.refund_id,
        amount_inr=refund_amount,
        status="refunded",
        message=f"Order {order.order_reference} successfully refunded."
    )

@router.post("/{order_ref}/simulate-webhook-delay")
def simulate_webhook_delay(order_ref: str, db: Session = Depends(get_db)):
    """
    Engineered Failure Simulator (Phase 4):
    Simulates a dropped or delayed Razorpay webhook. Transitions order to PENDING_CONFIRMATION
    and records the failure in the audit log.
    """
    order = db.query(Order).filter(
        (Order.order_reference == order_ref) | (Order.razorpay_order_id == order_ref)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status == "paid":
        raise HTTPException(status_code=400, detail="Order is already paid; cannot simulate webhook delay.")

    previous_status = order.status
    order.status = "pending_confirmation"
    order.updated_at = utcnow()

    record_audit_log(
        db=db,
        actor=order.actor,
        agent_id=order.agent_id,
        sku=order.sku,
        requested_discount=order.requested_discount_pct,
        order_value_inr=order.total_amount_inr,
        policy_decision="approved",
        reason=f"⚠️ Webhook timeout/delay detected for order {order.order_reference}. State transitioned to PENDING_CONFIRMATION. Awaiting fallback poll.",
        razorpay_order_id=order.razorpay_order_id,
        status="pending_confirmation",
        failure_detail="Simulated Webhook Delivery Failure (Timeout / Drop)",
        metadata={"previous_status": previous_status, "simulated_delay": True}
    )
    db.commit()

    return {
        "order_reference": order.order_reference,
        "status": order.status,
        "message": "Engineered failure activated: Webhook simulated as dropped. Order is now in PENDING_CONFIRMATION. Use /api/orders/{order_ref}/poll to recover."
    }

@router.post("/{order_ref}/poll", response_model=FallbackPollResponse)
def poll_order_fallback(order_ref: str, db: Session = Depends(get_db)):
    """
    Engineered Fallback Recovery (Phase 4):
    Polls Razorpay Payments API once as fallback when webhook is missing.
    Guarantees no double charges, no hanging state, and complete resolution.
    """
    order = db.query(Order).filter(
        (Order.order_reference == order_ref) | (Order.razorpay_order_id == order_ref)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    previous_status = order.status

    if order.status == "paid":
        return FallbackPollResponse(
            order_reference=order.order_reference,
            razorpay_order_id=order.razorpay_order_id,
            previous_status=previous_status,
            current_status=order.status,
            resolved_via="already_paid",
            payment_id=order.razorpay_payment_id,
            message="Order is already in PAID state. Idempotent check satisfied, zero double-charging."
        )

    poll_result = payment_service.poll_payment_status(order.razorpay_order_id or "order_test_fallback")
    new_status = poll_result["status"]
    payment_id = poll_result.get("payment_id")

    order.status = new_status
    order.is_link_active = False if new_status == "paid" else order.is_link_active
    if payment_id:
        order.razorpay_payment_id = payment_id
    order.updated_at = utcnow()

    record_audit_log(
        db=db,
        actor=order.actor,
        agent_id=order.agent_id,
        sku=order.sku,
        requested_discount=order.requested_discount_pct,
        order_value_inr=order.total_amount_inr,
        policy_decision="approved",
        reason=f"✅ Fallback Recovery Resolved: Polled Razorpay Payments API. Payment status confirmed as {new_status.upper()}.",
        razorpay_order_id=order.razorpay_order_id,
        status=new_status,
        metadata={
            "poll_response": poll_result,
            "recovered_from": previous_status,
            "payment_id": payment_id
        }
    )

    if order.agent_id:
        record_agent_order_outcome(db, order.agent_id, new_status)

    db.commit()

    return FallbackPollResponse(
        order_reference=order.order_reference,
        razorpay_order_id=order.razorpay_order_id,
        previous_status=previous_status,
        current_status=new_status,
        resolved_via=poll_result["resolved_via"],
        payment_id=payment_id,
        message=poll_result["message"]
    )
