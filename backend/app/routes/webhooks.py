import json
import logging
import hashlib
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import Order, ProcessedWebhookEvent, utcnow
from backend.app.services.payment_service import payment_service
from backend.app.services.trust_service import record_agent_order_outcome
from backend.app.services.audit_service import record_audit_log

logger = logging.getLogger("webhook_route")
router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# Also create an alias router for /api/webhook/razorpay
webhook_alias_router = APIRouter(prefix="/api/webhook", tags=["Webhooks"])

async def process_webhook_payload(
    request: Request,
    x_razorpay_signature: str,
    db: Session
):
    body_bytes = await request.body()
    
    # 1. Verify Signature
    if not payment_service.verify_webhook_signature(body_bytes, x_razorpay_signature):
        logger.warning("Invalid Razorpay webhook signature received.")
        record_audit_log(
            db=db,
            actor="razorpay_webhook",
            sku="SYSTEM",
            requested_discount=0.0,
            order_value_inr=0.0,
            policy_decision="rejected",
            reason="🚫 Invalid webhook signature rejected by HMAC SHA256 verification.",
            status="rejected",
            failure_detail="InvalidWebhookSignature"
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    event = payload.get("event")
    payload_data = payload.get("payload", {})
    payment_entity = payload_data.get("payment", {}).get("entity", {})
    order_entity = payload_data.get("order", {}).get("entity", {})
    refund_entity = payload_data.get("refund", {}).get("entity", {})
    
    event_id = payload.get("id") or payment_entity.get("id") or f"evt_{hashlib.sha256(body_bytes).hexdigest()[:16]}"
    payload_hash = hashlib.sha256(body_bytes).hexdigest()

    # 2. Idempotency check: Has this event already been processed?
    existing_evt = db.query(ProcessedWebhookEvent).filter(
        ProcessedWebhookEvent.event_id == event_id
    ).first()
    
    if existing_evt:
        logger.info(f"Webhook event {event_id} already processed. Returning idempotent 200.")
        return {
            "status": "already_processed",
            "event_id": event_id,
            "idempotent_replay": True
        }

    razorpay_order_id = payment_entity.get("order_id") or order_entity.get("id") or refund_entity.get("order_id")
    razorpay_payment_id = payment_entity.get("id") or refund_entity.get("payment_id")

    if not razorpay_order_id:
        # Mark event as processed
        db.add(ProcessedWebhookEvent(event_id=event_id, event_type=event or "unknown", payload_hash=payload_hash))
        db.commit()
        return {"status": "ignored", "message": "No order_id found in event"}

    # Find matching internal order
    order = db.query(Order).filter(Order.razorpay_order_id == razorpay_order_id).first()
    if not order:
        logger.info(f"Order for Razorpay ID {razorpay_order_id} not found in merchant database.")
        db.add(ProcessedWebhookEvent(event_id=event_id, event_type=event or "unknown", payload_hash=payload_hash))
        db.commit()
        return {"status": "order_not_found"}

    # 3. Handle Events
    if event in ["payment.captured", "order.paid"]:
        if order.status != "paid":
            order.status = "paid"
            order.is_link_active = False  # Deactivate payment link
            order.razorpay_payment_id = razorpay_payment_id
            order.updated_at = utcnow()
            
            record_audit_log(
                db=db,
                actor=order.actor,
                agent_id=order.agent_id,
                sku=order.sku,
                requested_discount=order.requested_discount_pct,
                order_value_inr=order.total_amount_inr,
                policy_decision="approved",
                reason=f"💳 Payment verified and captured via Razorpay Webhook ({event}) for order {order.order_reference}. Link deactivated.",
                razorpay_order_id=razorpay_order_id,
                status="paid",
                metadata={"payment_id": razorpay_payment_id, "event": event, "event_id": event_id}
            )
            
            if order.agent_id:
                record_agent_order_outcome(db, order.agent_id, "paid")

    elif event in ["payment.failed"]:
        order.status = "failed"
        order.updated_at = utcnow()
        
        record_audit_log(
            db=db,
            actor=order.actor,
            agent_id=order.agent_id,
            sku=order.sku,
            requested_discount=order.requested_discount_pct,
            order_value_inr=order.total_amount_inr,
            policy_decision="approved",
            reason=f"⚠️ Payment failed via Razorpay Webhook ({event}) for order {order.order_reference}.",
            razorpay_order_id=razorpay_order_id,
            status="failed",
            failure_detail=payment_entity.get("error_description", "Payment transaction failed"),
            metadata={"payment_id": razorpay_payment_id, "event_id": event_id}
        )
        
        if order.agent_id:
            record_agent_order_outcome(db, order.agent_id, "failed")

    elif event in ["refund.processed"]:
        order.status = "refunded"
        order.refund_id = refund_entity.get("id")
        order.refund_amount_inr = (refund_entity.get("amount", 0)) / 100.0
        order.updated_at = utcnow()
        
        record_audit_log(
            db=db,
            actor="merchant_admin",
            agent_id=order.agent_id,
            sku=order.sku,
            requested_discount=order.requested_discount_pct,
            order_value_inr=order.total_amount_inr,
            policy_decision="approved",
            reason=f"🔄 Refund processed via Razorpay Webhook for order {order.order_reference}. Refund ID: {order.refund_id}.",
            razorpay_order_id=razorpay_order_id,
            status="refunded",
            metadata={"refund_id": order.refund_id, "event_id": event_id}
        )

    # Record Processed Event
    db.add(ProcessedWebhookEvent(
        event_id=event_id,
        event_type=event or "unknown",
        payload_hash=payload_hash
    ))
    db.commit()

    return {"status": "success", "event": event, "order_status": order.status, "event_id": event_id}

@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: Session = Depends(get_db)
):
    return await process_webhook_payload(request, x_razorpay_signature, db)

@webhook_alias_router.post("/razorpay")
async def handle_razorpay_webhook_alias(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: Session = Depends(get_db)
):
    return await process_webhook_payload(request, x_razorpay_signature, db)
