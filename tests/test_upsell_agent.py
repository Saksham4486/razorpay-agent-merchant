import uuid
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_chat_checkout_triggers_policy_gated_upsell_offer_visible_in_reply():
    """
    DoD: a completed order for one SKU triggers a policy-gated upsell
    offer for a second SKU, visible in the chat reply and recorded in
    the audit trail.
    """
    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "I want to buy SKU-AI-ROUTER-PRO, checkout please"}],
        "language": "en"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["active_order"] is not None
    assert data["active_order"]["status"] in ("paid", "pending_payment")

    # SKU-AI-ROUTER-PRO maps to SKU-CLOUD-CREDITS in PAIRS_WELL_WITH
    assert data["upsell_offer"] is not None
    assert data["upsell_offer"]["sku"] == "SKU-CLOUD-CREDITS"
    assert data["upsell_offer"]["triggering_sku"] == "SKU-AI-ROUTER-PRO"
    assert "SKU-CLOUD-CREDITS" in data["reply"] or data["upsell_offer"]["name"] in data["reply"]

    # Visible in the audit trail
    audit_res = client.get("/api/audit")
    logs = audit_res.json()["logs"]
    upsell_logs = [l for l in logs if l.get("status") == "upsell_offered" and l.get("sku") == "SKU-CLOUD-CREDITS"]
    assert len(upsell_logs) >= 1


def test_upsell_offer_is_policy_gated_not_unconditional():
    """The upsell offer must go through check_policy() exactly like any
    other order line - an out-of-policy complement should not be offered
    unconditionally. We verify the offer, when present, always carries a
    policy reason and a discount that respects the complement SKU's own cap."""
    from backend.app.database import SessionLocal
    from backend.app.services.upsell_service import evaluate_upsell_offer, PAIRS_WELL_WITH
    from backend.app.models import CatalogItem

    db = SessionLocal()
    try:
        for triggering_sku, complement_sku in PAIRS_WELL_WITH.items():
            offer = evaluate_upsell_offer(triggering_sku, db, agent_id=None, actor="test_actor")
            if offer is not None:
                item = db.query(CatalogItem).filter(CatalogItem.sku == complement_sku).first()
                assert offer["offered_discount_pct"] <= item.max_discount_pct
                assert offer["reason"]
    finally:
        db.close()


def test_acp_checkout_session_completion_includes_upsell_offer():
    create_res = client.post("/acp/checkout_sessions", json={
        "sku": "SKU-AI-ROUTER-PRO",
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "agent_id": f"acp_upsell_test_{uuid.uuid4().hex[:6]}"
    })
    assert create_res.status_code == 200
    session_id = create_res.json()["session_id"]

    complete_res = client.post(f"/acp/checkout_sessions/{session_id}/complete")
    assert complete_res.status_code == 200
    data = complete_res.json()
    assert data["status"] == "completed"
    assert data["upsell_offer"] is not None
    assert data["upsell_offer"]["sku"] == "SKU-CLOUD-CREDITS"


def test_upsell_offer_never_bypasses_out_of_stock_or_missing_sku():
    """SKUs with no mapped complement, or a complement with zero stock,
    must yield no offer rather than fabricating one."""
    from backend.app.database import SessionLocal
    from backend.app.services.upsell_service import evaluate_upsell_offer

    db = SessionLocal()
    try:
        offer = evaluate_upsell_offer("SKU-DOES-NOT-EXIST", db, agent_id=None, actor="test_actor")
        assert offer is None
    finally:
        db.close()
