import json
import uuid
import datetime
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.services.payment_service import payment_service
from backend.app.schemas import BuyerMandate
from backend.app.services.mandate_service import sign_mandate
from backend.app.config import settings

client = TestClient(app)

def test_full_agent_money_loop():
    # 1. Catalog Lookup
    cat_res = client.get("/api/catalog")
    assert cat_res.status_code == 200
    catalog = cat_res.json()
    assert catalog["count"] > 0
    sku = "SKU-POS-TERMINAL"
    agent_id = f"test_e2e_agent_{uuid.uuid4().hex[:8]}"

    # 0. Explicit agent registration (A1) - real random key, shown once
    reg_res = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert reg_res.status_code == 201
    agent_key = reg_res.json()["agent_key"]
    assert agent_key and len(agent_key) > 20
    auth_headers = {"X-Agent-Key": agent_key}

    # 0b. Reusing the agent_id with NO key must now be rejected (A1 regression guard)
    spoof_res = client.post("/api/negotiate", json={
        "sku": sku,
        "requested_discount_pct": 10.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    })
    assert spoof_res.status_code == 401

    # 2. Negotiate - Excessive discount rejected with explainable reason
    neg_bad = client.post("/api/negotiate", json={
        "sku": sku,
        "requested_discount_pct": 50.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }, headers=auth_headers)
    assert neg_bad.status_code == 200
    data_bad = neg_bad.json()
    assert data_bad["allowed"] is False
    assert data_bad["policy_status"] == "rejected"
    assert "exceeds the SKU maximum allowable discount limit" in data_bad["reason"]

    # 3. Negotiate - Renegotiate within limits (15%)
    neg_ok = client.post("/api/negotiate", json={
        "sku": sku,
        "requested_discount_pct": 15.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }, headers=auth_headers)
    assert neg_ok.status_code == 200
    data_ok = neg_ok.json()
    assert data_ok["allowed"] is True
    assert data_ok["policy_status"] == "approved"
    assert data_ok["approved_discount_pct"] == 15.0

    # 4. Checkout - Create Razorpay order
    idemp_key = f"e2e_idemp_{uuid.uuid4().hex}"
    chk_res = client.post("/api/checkout", json={
        "sku": sku,
        "quantity": 1,
        "requested_discount_pct": 15.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": idemp_key
    }, headers=auth_headers)
    assert chk_res.status_code == 200
    chk_data = chk_res.json()
    assert chk_data["status"] == "pending_payment"
    assert chk_data["razorpay_order_id"] is not None
    order_ref = chk_data["order_reference"]
    rzp_order_id = chk_data["razorpay_order_id"]

    # 5. Webhook Signature Verification and Payment Confirmation
    wh_payload = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_e2e_{uuid.uuid4().hex[:8]}",
                    "order_id": rzp_order_id,
                    "amount": int(chk_data["total_amount_inr"] * 100),
                    "status": "captured"
                }
            }
        }
    }
    raw_body = json.dumps(wh_payload).encode("utf-8")
    sig = payment_service.generate_test_webhook_signature(raw_body)
    
    wh_res = client.post(
        "/api/webhooks/razorpay",
        content=raw_body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    )
    assert wh_res.status_code == 200
    assert wh_res.json()["order_status"] == "paid"

    # 6. Verify in Order query
    order_query = client.get(f"/api/orders/{order_ref}")
    assert order_query.status_code == 200
    assert order_query.json()["status"] == "paid"

def test_webhook_idempotency_replay():
    # Replaying the exact same webhook event ID must be an idempotent no-op (no duplicate state changes)
    sku = "SKU-CLOUD-CREDITS"
    idemp_key = f"e2e_wh_idemp_{uuid.uuid4().hex}"
    chk = client.post("/api/checkout", json={
        "sku": sku,
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    }).json()

    event_id = f"evt_idemp_{uuid.uuid4().hex[:10]}"
    wh_payload = {
        "id": event_id,
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_wh_{uuid.uuid4().hex[:8]}",
                    "order_id": chk["razorpay_order_id"],
                    "amount": int(chk["total_amount_inr"] * 100),
                    "status": "captured"
                }
            }
        }
    }
    raw_body = json.dumps(wh_payload).encode("utf-8")
    sig = payment_service.generate_test_webhook_signature(raw_body)

    # First delivery
    r1 = client.post("/api/webhooks/razorpay", content=raw_body, headers={"X-Razorpay-Signature": sig})
    assert r1.status_code == 200
    assert r1.json()["status"] == "success"

    # Second delivery (replay) -> Idempotent
    r2 = client.post("/api/webhooks/razorpay", content=raw_body, headers={"X-Razorpay-Signature": sig})
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_processed"
    assert r2.json()["idempotent_replay"] is True

def test_admin_auth_and_rejection():
    # Place a high-value order (GPU Dev Box -> pending_approval)
    idemp_key = f"admin_auth_test_{uuid.uuid4().hex}"
    chk = client.post("/api/checkout", json={
        "sku": "SKU-GPU-DEV-BOX",
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "ai_agent",
        "idempotency_key": idemp_key
    }).json()
    order_ref = chk["order_reference"]
    assert chk["status"] == "pending_approval"

    # 1. Unauthenticated approval attempt -> MUST BE 401
    unauth_res = client.post(f"/api/admin/orders/{order_ref}/approve")
    assert unauth_res.status_code == 401

    # 2. Authenticated approval with valid Basic Auth credentials -> 200
    auth_res = client.post(
        f"/api/admin/orders/{order_ref}/approve",
        auth=(settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD)
    )
    assert auth_res.status_code == 200
    assert auth_res.json()["status"] == "pending_payment"

    # 3. Create another high-value order and reject it
    idemp_key_2 = f"admin_rej_test_{uuid.uuid4().hex}"
    chk2 = client.post("/api/checkout", json={
        "sku": "SKU-GPU-DEV-BOX",
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "ai_agent",
        "idempotency_key": idemp_key_2
    }).json()
    order_ref_2 = chk2["order_reference"]

    rej_res = client.post(
        f"/api/admin/orders/{order_ref_2}/reject",
        auth=(settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD)
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"

def test_acp_feed_and_checkout_session_lifecycle():
    # 1. ACP Feed
    feed_res = client.get("/acp/feed")
    assert feed_res.status_code == 200
    feed = feed_res.json()
    assert feed["protocol"] == "ACP-1.0-draft"
    assert len(feed["items"]) > 0

    # 2. Create ACP Checkout Session
    cs_create = client.post("/acp/checkout_sessions", json={
        "sku": "SKU-AI-ROUTER-PRO",
        "quantity": 1,
        "requested_discount_pct": 10.0,
        "agent_id": "test_acp_agent"
    })
    assert cs_create.status_code == 200
    cs = cs_create.json()
    session_id = cs["session_id"]
    assert cs["status"] == "open"

    # 3. Complete ACP Checkout Session
    cs_complete = client.post(f"/acp/checkout_sessions/{session_id}/complete")
    assert cs_complete.status_code == 200
    comp_data = cs_complete.json()
    assert comp_data["status"] == "completed"
    assert comp_data["razorpay_order_id"] is not None

def test_ap2_buyer_mandates():
    sku = "SKU-AI-ROUTER-PRO"
    agent_id = f"mandate_agent_{uuid.uuid4().hex[:6]}"
    
    mandate = BuyerMandate(
        agent_id=agent_id,
        sku=sku,
        max_unit_price=45000.0,
        max_discount_pct=15.0,
        max_quantity=2,
        valid_until=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
        issued_at=datetime.datetime.now(datetime.timezone.utc)
    )
    sig = sign_mandate(mandate)

    # 0. Explicit agent registration (A1) before any negotiate/checkout traffic
    reg_res = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert reg_res.status_code == 201
    auth_headers = {"X-Agent-Key": reg_res.json()["agent_key"]}

    # 1. Valid mandate within bounds -> MUST PASS
    pass_res = client.post("/api/negotiate", json={
        "sku": sku,
        "requested_discount_pct": 10.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent",
        "mandate": mandate.model_dump(mode="json"),
        "mandate_signature": sig
    }, headers=auth_headers)
    assert pass_res.status_code == 200
    assert pass_res.json()["allowed"] is True
    assert pass_res.json()["mandate_verified"] is True

    # 2. Mandate violation: Asking for 5 units (mandate cap is 2) -> MUST BE REJECTED BEFORE POLICY
    fail_res = client.post("/api/negotiate", json={
        "sku": sku,
        "requested_discount_pct": 10.0,
        "quantity": 5,
        "agent_id": agent_id,
        "actor_type": "ai_agent",
        "mandate": mandate.model_dump(mode="json"),
        "mandate_signature": sig
    }, headers=auth_headers)
    assert fail_res.status_code == 200
    assert fail_res.json()["allowed"] is False
    assert "exceeds buyer authorized mandate limit" in fail_res.json()["reason"]

def test_audit_hash_chain_verification():
    verify_res = client.get("/api/audit/verify")
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["valid"] is True
    assert v_data["total_verified"] > 0
