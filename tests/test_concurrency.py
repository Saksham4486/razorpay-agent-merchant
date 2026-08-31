import uuid
import pytest
import httpx
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models import Order

client = TestClient(app)

@pytest.mark.anyio
async def test_concurrent_idempotent_checkouts():
    """
    Phase 2 Concurrency Test:
    Fires 20 parallel identical checkout requests with the same idempotency_key.
    Guarantees:
    - Exactly 1 Order created in the database
    - 19 successful idempotent replays
    - Zero 500 Internal Server Errors (IntegrityError handled cleanly)
    """
    idemp_key = f"concurrent_race_{uuid.uuid4().hex}"
    payload = {
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "ai_agent",
        "agent_id": "test_concurrency_agent",
        "idempotency_key": idemp_key
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        import asyncio
        tasks = [ac.post("/api/checkout", json=payload) for _ in range(20)]
        responses = await asyncio.gather(*tasks)

    # Verify all responses returned 200 OK
    assert all(r.status_code == 200 for r in responses), f"Statuses: {[r.status_code for r in responses]}"
    
    data_list = [r.json() for r in responses]
    order_refs = set(d["order_reference"] for d in data_list)
    assert len(order_refs) == 1, "All 20 concurrent requests must reference the exact same order"

    # Count how many were replays vs original
    replays = [d["idempotent_replay"] for d in data_list]
    assert replays.count(True) >= 19, f"Expected at least 19 replays, got {replays.count(True)}"

    # Check database: exactly 1 order row exists for this key
    db = SessionLocal()
    orders_in_db = db.query(Order).filter(Order.idempotency_key == idemp_key).all()
    assert len(orders_in_db) == 1, f"Expected 1 order in DB, found {len(orders_in_db)}"
    db.close()
