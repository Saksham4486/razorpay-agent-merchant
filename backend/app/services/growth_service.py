"""
Growth / Revenue Analytics (D2).

Pulls real numbers from the existing Order and AuditLog tables only - no
fabricated data. Computes a funnel (ads generated -> chat sessions started
-> negotiations attempted -> orders completed -> revenue) and a simple,
honestly-derived comparison of AI-negotiated orders vs a flat
no-negotiation baseline, both computed from the same real order rows.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.models import Order, AuditLog


def _funnel_counts(db: Session) -> Dict[str, int]:
    ads_generated = db.query(AuditLog).filter(AuditLog.status == "ad_generated").count()
    chat_sessions_started = db.query(AuditLog).filter(AuditLog.status == "chat_session_started").count()
    negotiations_attempted = db.query(AuditLog).filter(
        AuditLog.status.in_(["negotiated", "mandate_rejected"])
    ).count()
    orders_completed = db.query(Order).filter(Order.status == "paid").count()

    return {
        "ads_generated": ads_generated,
        "chat_sessions_started": chat_sessions_started,
        "negotiations_attempted": negotiations_attempted,
        "orders_completed": orders_completed
    }


def _revenue(db: Session) -> float:
    total = db.query(func.coalesce(func.sum(Order.total_amount_inr), 0.0)).filter(
        Order.status == "paid"
    ).scalar()
    return float(total or 0.0)


def _negotiated_vs_flat_baseline(db: Session) -> Dict[str, Any]:
    """
    Splits real Order rows into two genuine groups from the SAME underlying
    data - no synthetic/fabricated comparison group:
      - 'negotiated': orders where a discount was actually requested (>0%)
      - 'flat_no_negotiation': orders where no discount was requested (0%)
    and computes conversion rate (paid / total) and average discount for
    each, directly from Order.status and Order.approved_discount_pct.
    """
    def _group_stats(discount_filter):
        orders = db.query(Order).filter(discount_filter).all()
        total = len(orders)
        paid = [o for o in orders if o.status == "paid"]
        paid_count = len(paid)
        conversion_rate_pct = round((paid_count / total * 100), 2) if total > 0 else 0.0
        avg_discount_pct = round(
            sum(o.approved_discount_pct or 0.0 for o in paid) / paid_count, 2
        ) if paid_count > 0 else 0.0
        revenue_inr = round(sum(o.total_amount_inr for o in paid), 2)
        return {
            "total_orders": total,
            "paid_orders": paid_count,
            "conversion_rate_pct": conversion_rate_pct,
            "avg_discount_pct": avg_discount_pct,
            "revenue_inr": revenue_inr
        }

    negotiated = _group_stats(Order.requested_discount_pct > 0)
    flat_baseline = _group_stats(Order.requested_discount_pct == 0)

    return {
        "ai_negotiated": negotiated,
        "flat_no_negotiation_baseline": flat_baseline
    }


def compute_growth_summary(db: Session) -> Dict[str, Any]:
    funnel = _funnel_counts(db)
    revenue = _revenue(db)
    comparison = _negotiated_vs_flat_baseline(db)

    return {
        "funnel": {
            **funnel,
            "revenue_inr": round(revenue, 2)
        },
        "negotiation_impact": comparison
    }
