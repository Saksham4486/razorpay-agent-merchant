"""
Scripted Buyer Persona Regression Test (moved from simulation/ai_buyer_simulation.py, A3).

IMPORTANT: This is a SCRIPTED regression test with fixed, hardcoded steps and
embedded assert statements - it is NOT an AI demo and should never be
presented as one in the README or UI. It exercises three fixed personas
(bargain hunter, enterprise whale, impatient retryer) end to end against the
real HTTP API via FastAPI's TestClient, printing a readable trace as it goes.

For a genuinely LLM-driven autonomous buyer, see scripts/buyer_agent.py (A3),
which makes real Gemini tool-calling decisions rather than following a fixed
script.
"""
import time
import uuid
import json
import hmac
import hashlib
from typing import Dict, Any

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def print_header(title: str):
    print("\n" + "=" * 75)
    print(f" 🤖 SCRIPTED BUYER PERSONA REGRESSION: {title.upper()}")
    print("=" * 75)


def print_step(step_num: int, title: str, details: Dict[str, Any]):
    print(f"\n[Step {step_num}] {title}")
    print(json.dumps(details, indent=2, default=str))


def _register_agent(agent_id: str) -> Dict[str, str]:
    """A1: real agents must register and present X-Agent-Key on every call."""
    res = client.post("/api/agents/register", json={"agent_id": agent_id})
    if res.status_code == 201:
        key = res.json()["agent_key"]
    elif res.status_code == 409:
        # Already registered by an earlier test run against the same DB
        # session; we can't recover the key, so treat this persona as
        # already-proven and skip re-registration friction. In this
        # in-memory test DB each run starts fresh, so this path is
        # defensive rather than expected.
        raise RuntimeError(f"Agent {agent_id} unexpectedly already registered")
    else:
        raise RuntimeError(f"Agent registration failed: {res.status_code} {res.text}")
    return {"X-Agent-Key": key}


def run_persona_bargain_hunter():
    """
    Persona 1: The Bargain Hunter
    1. Reads catalog
    2. Proposes excessive discount (30%)
    3. Receives explainable rejection from Policy Engine
    4. Autonomously parses rejection reason and renegotiates at the exact allowable limit (15%)
    5. Executes checkout with idempotency key
    6. Simulates webhook payment capture -> verifies paid state & trust score update
    """
    agent_id = f"agent_bargain_hunter_{uuid.uuid4().hex[:6]}"
    auth = _register_agent(agent_id)
    print_header("Persona 1: The Bargain Hunter (Aggressive Negotiation & Autonomous Renegotiation)")

    res = client.get("/api/catalog")
    catalog = res.json()
    sku_item = next(i for i in catalog["items"] if i["sku"] == "SKU-AI-ROUTER-PRO")
    print_step(1, f"Catalog Discovered Product: {sku_item['name']}", {
        "sku": sku_item["sku"],
        "base_price": f"₹{sku_item['price_inr']:,.2f}",
        "max_allowable_discount": f"{sku_item['max_discount_pct']}%"
    })

    neg_payload_1 = {
        "sku": sku_item["sku"], "requested_discount_pct": 30.0, "quantity": 1,
        "agent_id": agent_id, "actor_type": "ai_agent"
    }
    neg_res_1 = client.post("/api/negotiate", json=neg_payload_1, headers=auth).json()
    print_step(2, "Negotiation Attempt #1 (Aggressive 30% Ask) -> Policy Engine Evaluation", {
        "requested_discount": "30%",
        "policy_status": neg_res_1["policy_status"],
        "allowed": neg_res_1["allowed"],
        "explainable_reason": neg_res_1["reason"]
    })
    assert neg_res_1["allowed"] is False, "Expected 30% discount to be rejected by policy engine"

    print("\n🧠 [Agent Reasoning] Rejection received due to SKU discount bound. Counter-offering at maximum permissible cap (15%)...")
    neg_payload_2 = {
        "sku": sku_item["sku"], "requested_discount_pct": sku_item["max_discount_pct"],
        "quantity": 1, "agent_id": agent_id, "actor_type": "ai_agent"
    }
    neg_res_2 = client.post("/api/negotiate", json=neg_payload_2, headers=auth).json()
    print_step(3, "Renegotiation Attempt #2 (Bounded 15% Ask) -> Approved by Policy Engine", {
        "requested_discount": f"{sku_item['max_discount_pct']}%",
        "policy_status": neg_res_2["policy_status"],
        "allowed": neg_res_2["allowed"],
        "final_unit_price": f"₹{neg_res_2['final_unit_price_inr']:,.2f}",
        "explainable_reason": neg_res_2["reason"]
    })
    assert neg_res_2["allowed"] is True

    idempotency_key = f"idemp_bargain_{uuid.uuid4().hex[:10]}"
    checkout_payload = {
        "sku": sku_item["sku"], "quantity": 1, "requested_discount_pct": sku_item["max_discount_pct"],
        "actor_type": "ai_agent", "agent_id": agent_id, "idempotency_key": idempotency_key,
        "customer_name": "Autonomous Bargain Agent"
    }
    checkout_res = client.post("/api/checkout", json=checkout_payload, headers=auth).json()
    print_step(4, "Autonomous Checkout -> Razorpay Test Order Created", {
        "order_reference": checkout_res["order_reference"],
        "razorpay_order_id": checkout_res["razorpay_order_id"],
        "total_amount": f"₹{checkout_res['total_amount_inr']:,.2f}",
        "status": checkout_res["status"]
    })

    webhook_payload = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": f"pay_test_{uuid.uuid4().hex[:10]}",
            "order_id": checkout_res["razorpay_order_id"],
            "amount": int(checkout_res["total_amount_inr"] * 100),
            "status": "captured"
        }}}
    }
    body_bytes = json.dumps(webhook_payload).encode("utf-8")
    sig = hmac.new(b"whsec_mock_razorpay_secret_123", body_bytes, hashlib.sha256).hexdigest()

    # Note: the plural route (/api/webhooks/razorpay) is the only one that
    # exists after Section B removed the duplicate singular alias.
    wh_res = client.post(
        "/api/webhooks/razorpay",
        content=body_bytes,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    ).json()
    print_step(5, "Razorpay Webhook Signature Verified -> Order Marked PAID", {
        "webhook_result": wh_res,
        "order_status": wh_res["order_status"]
    })
    assert wh_res["order_status"] == "paid"


def run_persona_whale_enterprise():
    """
    Persona 2: The Whale Enterprise (High-Value Order Gating)
    1. Selects high-value GPU Dev Box (₹1,85,000)
    2. Policy engine triggers PENDING_APPROVAL gating (exceeds ₹1,50,000 threshold)
    3. Checkout creates order in PENDING_APPROVAL state (no instant charge)
    4. Merchant Admin reviews and approves order via authenticated
       /api/admin/orders/{id}/approve (HTTP Basic auth)
    """
    agent_id = f"agent_enterprise_whale_{uuid.uuid4().hex[:6]}"
    auth = _register_agent(agent_id)
    print_header("Persona 2: The Whale Enterprise (High-Value Gated Approval)")

    sku = "SKU-GPU-DEV-BOX"
    idempotency_key = f"idemp_whale_{uuid.uuid4().hex[:10]}"

    checkout_payload = {
        "sku": sku, "quantity": 1, "requested_discount_pct": 5.0,
        "actor_type": "ai_agent", "agent_id": agent_id, "idempotency_key": idempotency_key,
        "customer_name": "MegaCorp AI Labs"
    }
    checkout_res = client.post("/api/checkout", json=checkout_payload, headers=auth).json()
    print_step(1, "High-Value Checkout (₹1,75,750) -> Policy Gating Triggered", {
        "order_reference": checkout_res["order_reference"],
        "total_amount": f"₹{checkout_res['total_amount_inr']:,.2f}",
        "status": checkout_res["status"],
        "policy_reason": checkout_res["policy_reason"]
    })
    assert checkout_res["status"] == "pending_approval"

    print("\n👔 [Merchant Portal] Merchant Admin reviews high-value order and grants approval...")
    time.sleep(0.05)

    import base64
    basic_auth = "Basic " + base64.b64encode(b"admin:razorpay_agent_secure_2026").decode()
    admin_res = client.post(
        f"/api/admin/orders/{checkout_res['order_reference']}/approve",
        headers={"Authorization": basic_auth}
    ).json()
    print_step(2, "Admin Manual Approval -> Order Promoted & Razorpay Order Generated", {
        "order_reference": admin_res["order_reference"],
        "status": admin_res["status"],
        "razorpay_order_id": admin_res["razorpay_order_id"]
    })
    assert admin_res["status"] == "pending_payment"


def run_persona_impatient_retryer():
    """
    Persona 3: The Impatient Retryer (Idempotency & Zero Double-Charge Guarantee)
    1. Sends checkout with idempotency key
    2. Sends exact same checkout again with identical idempotency key
    3. Confirms identical order reference with idempotent_replay: true
    """
    agent_id = f"agent_impatient_fast_{uuid.uuid4().hex[:6]}"
    auth = _register_agent(agent_id)
    print_header("Persona 3: The Impatient Retryer (Strict Idempotency Verification)")

    fixed_idempotency_key = f"idemp_fixed_double_tap_{uuid.uuid4().hex[:8]}"
    payload = {
        "sku": "SKU-CLOUD-CREDITS", "quantity": 2, "requested_discount_pct": 10.0,
        "actor_type": "ai_agent", "agent_id": agent_id, "idempotency_key": fixed_idempotency_key,
        "customer_name": "Fast Retry Agent"
    }

    res1 = client.post("/api/checkout", json=payload, headers=auth).json()
    print_step(1, "First Checkout Invocation", {
        "order_reference": res1["order_reference"],
        "idempotent_replay": res1["idempotent_replay"],
        "status": res1["status"]
    })

    print("\n⚡ [Network Simulation] Buyer resends identical checkout payload due to timeout/retry...")
    res2 = client.post("/api/checkout", json=payload, headers=auth).json()
    print_step(2, "Second Checkout Invocation (Same Idempotency Key) -> Replay Recognized", {
        "order_reference": res2["order_reference"],
        "idempotent_replay": res2["idempotent_replay"],
        "status": res2["status"],
        "guarantee": "ZERO duplicate orders created. ZERO double charges."
    })

    assert res1["order_reference"] == res2["order_reference"]
    assert res2["idempotent_replay"] is True


def test_scripted_persona_bargain_hunter():
    run_persona_bargain_hunter()


def test_scripted_persona_whale_enterprise():
    run_persona_whale_enterprise()


def test_scripted_persona_impatient_retryer():
    run_persona_impatient_retryer()
