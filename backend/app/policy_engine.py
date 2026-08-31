from dataclasses import dataclass
from enum import Enum
from typing import Optional

class PolicyStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_APPROVAL = "pending_approval"

@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    status: PolicyStatus
    reason: str
    original_price: float
    requested_discount_pct: float
    approved_discount_pct: float
    final_unit_price: float
    total_order_value: float
    effective_approval_threshold: float
    requires_human_approval: bool

def compute_effective_approval_threshold(
    base_threshold: float,
    agent_trust_score: Optional[float] = None
) -> float:
    """
    Dynamically adjusts the instant checkout approval threshold based on the buyer's trust score.
    Default baseline trust score = 0.5 (multiplier = 1.0).
    Trust score ranges from 0.0 (multiplier = 0.5) to 1.0 (multiplier = 1.5).
    """
    score = agent_trust_score if agent_trust_score is not None else 0.5
    # Clamp score to [0.0, 1.0]
    score = max(0.0, min(1.0, score))
    multiplier = 0.5 + score
    return round(base_threshold * multiplier, 2)

def check_policy(
    sku_price: float,
    max_sku_discount_pct: float,
    requested_discount_pct: float,
    quantity: int,
    base_approval_threshold: float,
    agent_trust_score: Optional[float] = None,
    current_daily_spend: float = 0.0,
    daily_spend_cap: float = 500000.0,
    min_order_inr: float = 0.0
) -> PolicyResult:
    """
    Pure Policy Engine function enforcing merchant financial and risk rules.
    Called uniformly by both Human Conversational Flow and Autonomous AI Buyer Agents.
    
    Invariants enforced:
    1. Quantity & Minimum Order Value
    2. Hard Discount Cap (SKU level bounds)
    3. Merchant Global Daily Spend Cap
    4. Gated Approval Threshold (Dynamic, modulated by Agent Trust Score)
    """
    # 1. Quantity Validation
    if quantity <= 0:
        return PolicyResult(
            allowed=False,
            status=PolicyStatus.REJECTED,
            reason="Order quantity must be at least 1 unit.",
            original_price=sku_price,
            requested_discount_pct=requested_discount_pct,
            approved_discount_pct=0.0,
            final_unit_price=sku_price,
            total_order_value=0.0,
            effective_approval_threshold=base_approval_threshold,
            requires_human_approval=False
        )

    # 2. Check Discount Cap
    if requested_discount_pct > max_sku_discount_pct:
        reason = (
            f"Requested discount of {requested_discount_pct:.1f}% exceeds the SKU maximum "
            f"allowable discount limit of {max_sku_discount_pct:.1f}%. Merchant policy strictly bounds discount."
        )
        return PolicyResult(
            allowed=False,
            status=PolicyStatus.REJECTED,
            reason=reason,
            original_price=sku_price,
            requested_discount_pct=requested_discount_pct,
            approved_discount_pct=0.0,
            final_unit_price=sku_price,
            total_order_value=sku_price * quantity,
            effective_approval_threshold=base_approval_threshold,
            requires_human_approval=False
        )

    # Calculate discounted price
    approved_discount = max(0.0, requested_discount_pct)
    discount_factor = (100.0 - approved_discount) / 100.0
    final_unit_price = round(sku_price * discount_factor, 2)
    total_order_value = round(final_unit_price * quantity, 2)

    # 3. Minimum Order Check
    if min_order_inr > 0.0 and total_order_value < min_order_inr:
        return PolicyResult(
            allowed=False,
            status=PolicyStatus.REJECTED,
            reason=f"Order value of ₹{total_order_value:,.2f} is below SKU minimum required order value of ₹{min_order_inr:,.2f}.",
            original_price=sku_price,
            requested_discount_pct=requested_discount_pct,
            approved_discount_pct=approved_discount,
            final_unit_price=final_unit_price,
            total_order_value=total_order_value,
            effective_approval_threshold=base_approval_threshold,
            requires_human_approval=False
        )

    # 4. Daily Merchant Spend Cap
    if (current_daily_spend + total_order_value) > daily_spend_cap:
        reason = (
            f"Order value ₹{total_order_value:,.2f} plus current daily volume ₹{current_daily_spend:,.2f} "
            f"exceeds merchant daily ceiling of ₹{daily_spend_cap:,.2f}."
        )
        return PolicyResult(
            allowed=False,
            status=PolicyStatus.REJECTED,
            reason=reason,
            original_price=sku_price,
            requested_discount_pct=requested_discount_pct,
            approved_discount_pct=approved_discount,
            final_unit_price=final_unit_price,
            total_order_value=total_order_value,
            effective_approval_threshold=base_approval_threshold,
            requires_human_approval=False
        )

    # 5. Gated Approval Threshold (with Dynamic Trust Score Adjustment)
    effective_threshold = compute_effective_approval_threshold(base_approval_threshold, agent_trust_score)
    
    if total_order_value > effective_threshold:
        trust_desc = f" (Agent Trust Score: {agent_trust_score:.2f})" if agent_trust_score is not None else ""
        reason = (
            f"Order value ₹{total_order_value:,.2f} exceeds dynamic instant-checkout threshold of "
            f"₹{effective_threshold:,.2f}{trust_desc}. Order held as PENDING_APPROVAL requiring merchant authorization."
        )
        return PolicyResult(
            allowed=True,
            status=PolicyStatus.PENDING_APPROVAL,
            reason=reason,
            original_price=sku_price,
            requested_discount_pct=requested_discount_pct,
            approved_discount_pct=approved_discount,
            final_unit_price=final_unit_price,
            total_order_value=total_order_value,
            effective_approval_threshold=effective_threshold,
            requires_human_approval=True
        )

    # 6. Approved
    reason = (
        f"Approved: Requested discount {approved_discount:.1f}% is within SKU cap ({max_sku_discount_pct:.1f}%) "
        f"and total value ₹{total_order_value:,.2f} is within dynamic threshold ₹{effective_threshold:,.2f}."
    )
    return PolicyResult(
        allowed=True,
        status=PolicyStatus.APPROVED,
        reason=reason,
        original_price=sku_price,
        requested_discount_pct=requested_discount_pct,
        approved_discount_pct=approved_discount,
        final_unit_price=final_unit_price,
        total_order_value=total_order_value,
        effective_approval_threshold=effective_threshold,
        requires_human_approval=False
    )
