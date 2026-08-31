import pytest
from backend.app.policy_engine import check_policy, PolicyStatus

def test_quantity_validation():
    # Quantity <= 0 must be rejected
    res = check_policy(
        sku_price=1000.0,
        max_sku_discount_pct=10.0,
        requested_discount_pct=5.0,
        quantity=0,
        base_approval_threshold=50000.0,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=500000.0
    )
    assert res.status == PolicyStatus.REJECTED
    assert "at least 1 unit" in res.reason

def test_discount_cap_enforcement_and_explainability():
    # Requested discount (25%) exceeds SKU cap (15%) -> MUST REJECT
    res = check_policy(
        sku_price=45000.0,
        max_sku_discount_pct=15.0,
        requested_discount_pct=25.0,
        quantity=1,
        base_approval_threshold=50000.0,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=500000.0
    )
    assert res.status == PolicyStatus.REJECTED
    assert res.approved_discount_pct == 0.0
    assert "exceeds the SKU maximum allowable discount limit of 15.0%" in res.reason

def test_approved_discount_within_bounds():
    # Requested discount (10%) within SKU cap (15%) -> MUST APPROVE
    res = check_policy(
        sku_price=45000.0,
        max_sku_discount_pct=15.0,
        requested_discount_pct=10.0,
        quantity=1,
        base_approval_threshold=50000.0,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=500000.0
    )
    assert res.status == PolicyStatus.APPROVED
    assert res.approved_discount_pct == 10.0
    assert res.final_unit_price == 40500.0
    assert res.total_order_value == 40500.0

def test_gated_approval_for_high_value_order():
    # Order value (₹1,75,750) exceeds threshold -> MUST BE PENDING_APPROVAL
    res = check_policy(
        sku_price=185000.0,
        max_sku_discount_pct=10.0,
        requested_discount_pct=5.0,
        quantity=1,
        base_approval_threshold=50000.0,
        agent_trust_score=0.5,
        current_daily_spend=0.0,
        daily_spend_cap=500000.0
    )
    assert res.status == PolicyStatus.PENDING_APPROVAL
    assert "exceeds dynamic instant-checkout threshold" in res.reason

def test_dynamic_trust_score_modulation():
    # High trust score (0.9) increases approval threshold
    res_high = check_policy(
        sku_price=60000.0,
        max_sku_discount_pct=10.0,
        requested_discount_pct=0.0,
        quantity=1,
        base_approval_threshold=50000.0,
        agent_trust_score=0.9,
        current_daily_spend=0.0,
        daily_spend_cap=500000.0
    )
    assert res_high.status == PolicyStatus.APPROVED
    assert res_high.effective_approval_threshold == 70000.0

    # Low trust score (0.1) reduces approval threshold
    res_low = check_policy(
        sku_price=35000.0,
        max_sku_discount_pct=10.0,
        requested_discount_pct=0.0,
        quantity=1,
        base_approval_threshold=50000.0,
        agent_trust_score=0.1,
        current_daily_spend=0.0,
        daily_spend_cap=500000.0
    )
    assert res_low.status == PolicyStatus.PENDING_APPROVAL
    assert res_low.effective_approval_threshold == 30000.0

def test_daily_spend_cap_enforcement():
    # Current spend + order value exceeds daily spend cap -> REJECTED
    res = check_policy(
        sku_price=50000.0,
        max_sku_discount_pct=10.0,
        requested_discount_pct=0.0,
        quantity=1,
        base_approval_threshold=100000.0,
        agent_trust_score=0.5,
        current_daily_spend=480000.0,
        daily_spend_cap=500000.0
    )
    assert res.status == PolicyStatus.REJECTED
    assert "exceeds merchant daily ceiling" in res.reason
