"""
Upsell / Cross-sell Agent (D1).

After a successful negotiate or checkout, evaluates the catalog for one
complementary or upgraded SKU and offers it through the SAME
policy-engine-gated path as any other order line - it never bypasses
check_policy(). Both the offer and its outcome are audit-logged like
everything else in the system.
"""
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from backend.app.models import CatalogItem
from backend.app.policy_engine import check_policy, PolicyStatus
from backend.app.config import settings
from backend.app.services.audit_service import record_audit_log

# Simple static "pairs well with" mapping per SKU. An LLM call over the
# catalog list would be a reasonable alternative implementation; a static
# mapping is deliberately used here for predictability and zero extra
# LLM cost on every single successful order.
PAIRS_WELL_WITH: Dict[str, str] = {
    "SKU-AI-ROUTER-PRO": "SKU-CLOUD-CREDITS",   # edge gateway -> API credits to run on it
    "SKU-GPU-DEV-BOX": "SKU-NOISE-HEADSET",     # dev workstation -> focus headset
    "SKU-POS-TERMINAL": "SKU-CLOUD-CREDITS",    # POS terminal -> transaction/API credits
    "SKU-CLOUD-CREDITS": "SKU-AI-ROUTER-PRO",   # API credits -> hardware to run them on
    "SKU-ERGO-DESK": "SKU-NOISE-HEADSET",       # standing desk -> ANC headset for the new setup
    "SKU-NOISE-HEADSET": "SKU-ERGO-DESK",       # headset -> ergonomic desk
}

# Discount offered on the upsell item itself - a modest, non-negotiated
# incentive, still fully bounded by the SKU's own max_discount_pct via
# check_policy() below.
UPSELL_DISCOUNT_PCT = 5.0


def evaluate_upsell_offer(
    triggering_sku: str,
    db: Session,
    agent_id: Optional[str],
    actor: str
) -> Optional[Dict[str, Any]]:
    """
    Evaluates whether a complementary SKU can be offered after a successful
    negotiate/checkout on `triggering_sku`. Returns an offer dict (already
    policy-cleared) or None if there's no mapped complement, the mapped SKU
    doesn't exist/is out of stock, or the policy engine rejects it.

    The offer itself never creates an order - it only proposes a
    policy-approved next step; the buyer (human or agent) still has to
    accept and go through negotiate/checkout normally to actually buy it.
    """
    complement_sku = PAIRS_WELL_WITH.get(triggering_sku)
    if not complement_sku:
        return None

    item = db.query(CatalogItem).filter(CatalogItem.sku == complement_sku).first()
    if not item or item.stock <= 0:
        return None

    decision = check_policy(
        sku_price=item.price_inr,
        max_sku_discount_pct=item.max_discount_pct,
        requested_discount_pct=min(UPSELL_DISCOUNT_PCT, item.max_discount_pct),
        quantity=1,
        base_approval_threshold=item.requires_approval_above_inr,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=settings.DAILY_MERCHANT_SPEND_CAP_INR,
        min_order_inr=item.min_order_inr
    )

    offer_approved = decision.status == PolicyStatus.APPROVED

    record_audit_log(
        db=db,
        actor=actor,
        agent_id=agent_id,
        sku=complement_sku,
        requested_discount=min(UPSELL_DISCOUNT_PCT, item.max_discount_pct),
        order_value_inr=decision.total_order_value,
        policy_decision="approved" if offer_approved else "rejected",
        reason=(
            f"🎯 Upsell offer for {item.name} triggered by purchase of {triggering_sku}: "
            f"{decision.reason}"
        ),
        status="upsell_offered" if offer_approved else "upsell_rejected"
    )
    db.commit()

    if not offer_approved:
        return None

    return {
        "sku": item.sku,
        "name": item.name,
        "description": item.description,
        "unit_price_inr": item.price_inr,
        "offered_discount_pct": min(UPSELL_DISCOUNT_PCT, item.max_discount_pct),
        "final_unit_price_inr": decision.final_unit_price,
        "reason": decision.reason,
        "triggering_sku": triggering_sku
    }
