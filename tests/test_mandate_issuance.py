import uuid
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.services.mandate_service import verify_mandate_signature
from backend.app.schemas import BuyerMandate

client = TestClient(app)

SKU = "SKU-AI-ROUTER-PRO"


def _register(agent_id):
    res = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert res.status_code == 201
    return res.json()["agent_key"]


def test_mandate_issuance_requires_registration():
    unregistered_agent = f"agent_no_reg_{uuid.uuid4().hex[:8]}"
    res = client.post(f"/api/agents/{unregistered_agent}/mandates", json={
        "sku": SKU, "max_unit_price": 45000.0, "max_discount_pct": 15.0,
        "max_quantity": 2, "valid_minutes": 60
    })
    assert res.status_code == 401


def test_mandate_issuance_requires_matching_key():
    agent_id = f"agent_mandate_{uuid.uuid4().hex[:8]}"
    _register(agent_id)

    res = client.post(f"/api/agents/{agent_id}/mandates", json={
        "sku": SKU, "max_unit_price": 45000.0, "max_discount_pct": 15.0,
        "max_quantity": 2, "valid_minutes": 60
    }, headers={"X-Agent-Key": "wrong-key"})
    assert res.status_code == 401


def test_mandate_issued_is_cryptographically_valid_and_usable():
    """A real agent can now obtain a signed mandate over HTTP (not just
    via a direct Python import in pytest) and use it end to end."""
    agent_id = f"agent_mandate_e2e_{uuid.uuid4().hex[:8]}"
    key = _register(agent_id)
    auth = {"X-Agent-Key": key}

    issue_res = client.post(f"/api/agents/{agent_id}/mandates", json={
        "sku": SKU, "max_unit_price": 45000.0, "max_discount_pct": 15.0,
        "max_quantity": 2, "valid_minutes": 60
    }, headers=auth)
    assert issue_res.status_code == 200
    body = issue_res.json()
    mandate = body["mandate"]
    signature = body["mandate_signature"]

    assert mandate["agent_id"] == agent_id
    assert mandate["sku"] == SKU

    # Signature independently verifies via the same verify_mandate_signature()
    # used inside evaluate_buyer_mandate().
    reconstructed = BuyerMandate(**mandate)
    assert verify_mandate_signature(reconstructed, signature) is True

    # End to end: use the issued mandate on a real negotiate call, within bounds.
    neg = client.post("/api/negotiate", json={
        "sku": SKU,
        "requested_discount_pct": 10.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent",
        "mandate": mandate,
        "mandate_signature": signature
    }, headers=auth)
    assert neg.status_code == 200
    assert neg.json()["allowed"] is True
    assert neg.json()["mandate_verified"] is True


def test_mandate_violation_rejected_distinctly_from_merchant_policy_violation():
    """
    DoD: a request that violates its own mandate must be rejected
    distinctly from a request that violates merchant policy.
    """
    agent_id = f"agent_mandate_distinct_{uuid.uuid4().hex[:8]}"
    key = _register(agent_id)
    auth = {"X-Agent-Key": key}

    issue_res = client.post(f"/api/agents/{agent_id}/mandates", json={
        "sku": SKU, "max_unit_price": 45000.0, "max_discount_pct": 15.0,
        "max_quantity": 2, "valid_minutes": 60
    }, headers=auth)
    mandate = issue_res.json()["mandate"]
    signature = issue_res.json()["mandate_signature"]

    # Case A: violates the AGENT'S OWN mandate (asks for 5 units, mandate cap is 2)
    # but the discount itself (10%) is well within merchant policy.
    mandate_violation = client.post("/api/checkout", json={
        "sku": SKU,
        "quantity": 5,
        "requested_discount_pct": 10.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": f"idemp_mviol_{uuid.uuid4().hex}",
        "mandate": mandate,
        "mandate_signature": signature
    }, headers=auth)
    assert mandate_violation.status_code == 400
    assert mandate_violation.json()["detail"]["error"] == "MandateViolation"

    # Case B: violates MERCHANT POLICY (discount far exceeds SKU's max_discount_pct
    # of 25%), with no mandate attached at all - a completely different failure path.
    policy_violation = client.post("/api/checkout", json={
        "sku": SKU,
        "quantity": 1,
        "requested_discount_pct": 90.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": f"idemp_pviol_{uuid.uuid4().hex}"
    }, headers=auth)
    assert policy_violation.status_code == 400
    assert policy_violation.json()["detail"]["error"] == "PolicyViolation"

    # The two rejection reasons must be distinguishable from each other.
    assert mandate_violation.json()["detail"]["error"] != policy_violation.json()["detail"]["error"]
