import uuid
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_growth_summary_starts_at_zero_with_no_activity():
    res = client.get("/api/growth/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["funnel"]["ads_generated"] == 0
    assert data["funnel"]["chat_sessions_started"] == 0
    assert data["funnel"]["negotiations_attempted"] == 0
    assert data["funnel"]["orders_completed"] == 0
    assert data["funnel"]["revenue_inr"] == 0.0


def test_growth_summary_reflects_real_activity_across_the_funnel():
    """
    DoD: real numbers pulled from Order/AuditLog, updating as new activity
    happens - not fabricated, not static.
    """
    # 1. Generate an ad
    client.post("/api/ads/generate", json={"sku": "SKU-CLOUD-CREDITS", "languages": ["en"]})

    # 2. Start a chat session
    client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "hello"}],
        "language": "en"
    })

    # 3. Attempt a negotiation
    client.post("/api/negotiate", json={
        "sku": "SKU-CLOUD-CREDITS",
        "requested_discount_pct": 5.0,
        "quantity": 1,
        "actor_type": "human"
    })

    # 4. Complete a paid order (via mock simulate-payment, A2)
    idemp_key = f"growth_test_{uuid.uuid4().hex}"
    chk = client.post("/api/checkout", json={
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    }).json()
    client.post(f"/api/orders/{chk['order_reference']}/simulate-payment")

    res = client.get("/api/growth/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["funnel"]["ads_generated"] >= 1
    assert data["funnel"]["chat_sessions_started"] >= 1
    assert data["funnel"]["negotiations_attempted"] >= 1
    assert data["funnel"]["orders_completed"] >= 1
    assert data["funnel"]["revenue_inr"] > 0.0


def test_growth_summary_updates_as_new_orders_come_in():
    """DoD: panel updates as new orders come in during a live demo."""
    before = client.get("/api/growth/summary").json()["funnel"]

    idemp_key = f"growth_update_test_{uuid.uuid4().hex}"
    chk = client.post("/api/checkout", json={
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    }).json()
    client.post(f"/api/orders/{chk['order_reference']}/simulate-payment")

    after = client.get("/api/growth/summary").json()["funnel"]
    assert after["orders_completed"] == before["orders_completed"] + 1
    assert after["revenue_inr"] > before["revenue_inr"]


def test_negotiation_impact_compares_negotiated_vs_flat_orders_from_real_data():
    """
    DoD: a simple comparison of AI-negotiated avg discount/conversion vs a
    flat no-negotiation baseline, computed from the same order data.
    """
    # A negotiated order (discount > 0), paid
    neg_idemp = f"neg_group_{uuid.uuid4().hex}"
    neg_chk = client.post("/api/checkout", json={
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 10.0,
        "actor_type": "human",
        "idempotency_key": neg_idemp
    }).json()
    client.post(f"/api/orders/{neg_chk['order_reference']}/simulate-payment")

    # A flat, no-negotiation order (0% discount), paid
    flat_idemp = f"flat_group_{uuid.uuid4().hex}"
    flat_chk = client.post("/api/checkout", json={
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "actor_type": "human",
        "idempotency_key": flat_idemp
    }).json()
    client.post(f"/api/orders/{flat_chk['order_reference']}/simulate-payment")

    res = client.get("/api/growth/summary")
    impact = res.json()["negotiation_impact"]

    assert impact["ai_negotiated"]["total_orders"] >= 1
    assert impact["ai_negotiated"]["avg_discount_pct"] > 0.0
    assert impact["flat_no_negotiation_baseline"]["total_orders"] >= 1
    assert impact["flat_no_negotiation_baseline"]["avg_discount_pct"] == 0.0
