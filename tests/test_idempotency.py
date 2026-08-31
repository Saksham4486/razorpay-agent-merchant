import pytest
import uuid
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_idempotent_checkout_prevents_duplicate_orders():
    idempotency_key = f"test_idemp_{uuid.uuid4().hex}"
    
    payload = {
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 10.0,
        "actor_type": "ai_agent",
        "agent_id": "test_agent_idemp",
        "idempotency_key": idempotency_key,
        "customer_name": "Idempotency Test Client"
    }

    # First checkout
    res1 = client.post("/api/checkout", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["idempotent_replay"] is False
    order_ref = data1["order_reference"]
    rzp_order_id = data1["razorpay_order_id"]

    # Second checkout with identical key
    res2 = client.post("/api/checkout", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["idempotent_replay"] is True
    assert data2["order_reference"] == order_ref
    assert data2["razorpay_order_id"] == rzp_order_id
    assert data2["total_amount_inr"] == data1["total_amount_inr"]
