import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from backend.app.database import get_db
from backend.app.models import Order, utcnow
from backend.app.services.payment_service import payment_service
from backend.app.services.audit_service import record_audit_log
from backend.app.middleware.auth import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["Merchant Admin"])

def find_order_by_ref_or_id(order_ref: str, db: Session) -> Order:
    """
    Explicit, robust lookup by order_reference or integer id.
    """
    filters = [Order.order_reference == order_ref]
    if order_ref.isdigit():
        filters.append(Order.id == int(order_ref))
    return db.query(Order).filter(or_(*filters)).first()

@router.post("/orders/{order_ref}/approve")
def approve_pending_order(
    order_ref: str,
    admin_user: str = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Allows an authenticated merchant administrator to review and approve orders held in PENDING_APPROVAL.
    Creates Razorpay order upon authorization.
    """
    order = find_order_by_ref_or_id(order_ref, db)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "pending_approval":
        raise HTTPException(status_code=400, detail=f"Order is in '{order.status}' state, not 'pending_approval'")

    # Create Razorpay order now that merchant has authorized it
    rzp_res = payment_service.create_order(
        amount_inr=order.total_amount_inr,
        order_reference=order.order_reference,
        notes={
            "actor": order.actor,
            "sku": order.sku,
            "approved_by": admin_user
        }
    )

    order.status = "pending_payment"
    order.razorpay_order_id = rzp_res["razorpay_order_id"]
    order.updated_at = utcnow()

    # Log approval in audit trail
    record_audit_log(
        db=db,
        actor=f"admin:{admin_user}",
        agent_id=order.agent_id,
        sku=order.sku,
        requested_discount=order.requested_discount_pct,
        order_value_inr=order.total_amount_inr,
        policy_decision="approved",
        reason=f"Merchant administrator '{admin_user}' authorized high-value order {order.order_reference} (₹{order.total_amount_inr:,.2f}). Razorpay test order generated.",
        razorpay_order_id=order.razorpay_order_id,
        status="pending_payment",
        metadata={"approved_by": admin_user, "razorpay_order_id": order.razorpay_order_id}
    )
    db.commit()

    return {
        "order_reference": order.order_reference,
        "status": order.status,
        "razorpay_order_id": order.razorpay_order_id,
        "message": f"Order approved by merchant administrator '{admin_user}'."
    }

@router.post("/orders/{order_ref}/reject")
def reject_pending_order(
    order_ref: str,
    reason: str = "Merchant administrator declined authorization",
    admin_user: str = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Allows an authenticated merchant administrator to reject an order held in PENDING_APPROVAL.
    Transitions order to REJECTED.
    """
    order = find_order_by_ref_or_id(order_ref, db)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "pending_approval":
        raise HTTPException(status_code=400, detail=f"Order is in '{order.status}' state, not 'pending_approval'")

    order.status = "rejected"
    order.is_link_active = False
    order.updated_at = utcnow()

    record_audit_log(
        db=db,
        actor=f"admin:{admin_user}",
        agent_id=order.agent_id,
        sku=order.sku,
        requested_discount=order.requested_discount_pct,
        order_value_inr=order.total_amount_inr,
        policy_decision="rejected",
        reason=f"Merchant administrator '{admin_user}' rejected order {order.order_reference}. Reason: {reason}",
        razorpay_order_id=order.razorpay_order_id,
        status="rejected",
        failure_detail=f"AdminRejection: {reason}",
        metadata={"rejected_by": admin_user, "reason": reason}
    )
    db.commit()

    return {
        "order_reference": order.order_reference,
        "status": "rejected",
        "message": f"Order {order.order_reference} rejected by merchant administrator."
    }
