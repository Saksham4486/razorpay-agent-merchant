import uuid
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.services.payment_service import payment_service

client = TestClient(app)


def test_simulate_payment_completes_full_mock_checkout():
    """
    A2: With default mock credentials, a checkout can be completed via the
    honestly-labeled /simulate-payment endpoint, which generates a genuine
    HMAC SHA-256 signature server-side and runs it through the exact same
    verification path a real payment takes - never a client-side fake.
    """
    assert payment_service.is_mock is True

    idemp_key = f"a2_sim_idemp_{uuid.uuid4().hex}"
    chk = client.post("/api/checkout", json={
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    }).json()
    order_ref = chk["order_reference"]
    assert chk["status"] == "pending_payment"

    sim = client.post(f"/api/orders/{order_ref}/simulate-payment")
    assert sim.status_code == 200
    data = sim.json()
    assert data["status"] == "paid"
    assert data["simulated"] is True
    assert data["is_link_active"] is False

    order_check = client.get(f"/api/orders/{order_ref}")
    assert order_check.status_code == 200
    assert order_check.json()["status"] == "paid"


def test_simulate_payment_respects_dead_link_invariant():
    """A second simulate-payment call on an already-paid order must be blocked,
    proving it goes through the real verify_client_payment invariants, not a
    shortcut."""
    idemp_key = f"a2_sim_idemp2_{uuid.uuid4().hex}"
    chk = client.post("/api/checkout", json={
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    }).json()
    order_ref = chk["order_reference"]

    first = client.post(f"/api/orders/{order_ref}/simulate-payment")
    assert first.status_code == 200

    second = client.post(f"/api/orders/{order_ref}/simulate-payment")
    assert second.status_code == 400
    assert second.json()["detail"]["error"] == "DeadPaymentLink"


def test_simulate_payment_blocked_when_not_mock(monkeypatch):
    """Simulation must refuse to run against live test-mode credentials."""
    monkeypatch.setattr(payment_service, "is_mock", False)
    try:
        res = client.post("/api/orders/ORD_DOES_NOT_MATTER/simulate-payment")
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "SimulationNotAllowed"
    finally:
        monkeypatch.setattr(payment_service, "is_mock", True)
