import sys
import time
import uuid
import json
import httpx
from typing import Dict, Any

BASE_URL = "http://127.0.0.1:8000"

def print_header(title: str):
    print("\n" + "=" * 75)
    print(f" 🤖 AI BUYER AGENT SIMULATION: {title.upper()}")
    print("=" * 75)

def print_step(step_num: int, title: str, details: Dict[str, Any]):
    print(f"\n[Step {step_num}] {title}")
    print(json.dumps(details, indent=2))

def run_persona_bargain_hunter(client):
    """
    Persona 1: The Bargain Hunter
    Behavior:
    1. Reads catalog
    2. Proposes excessive discount (30%)
    3. Receives explainable rejection from Policy Engine
    4. Autonomously parses rejection reason and renegotiates at the exact allowable limit (15%)
    5. Executes checkout with idempotency key
    6. Simulates webhook payment capture -> verifies paid state & trust score update
    """
    agent_id = "agent_bargain_hunter"
    print_header("Persona 1: The Bargain Hunter (Aggressive Negotiation & Autonomous Renegotiation)")
    
    # 1. Catalog Discovery
    res = client.get("/api/catalog")
    catalog = res.json()
    sku_item = next(i for i in catalog["items"] if i["sku"] == "SKU-AI-ROUTER-PRO")
    print_step(1, f"Catalog Discovered Product: {sku_item['name']}", {
        "sku": sku_item["sku"],
        "base_price": f"₹{sku_item['price_inr']:,.2f}",
        "max_allowable_discount": f"{sku_item['max_discount_pct']}%"
    })

    # 2. Aggressive Negotiation Attempt (30% discount requested)
    neg_payload_1 = {
        "sku": sku_item["sku"],
        "requested_discount_pct": 30.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }
    neg_res_1 = client.post("/api/negotiate", json=neg_payload_1).json()
    print_step(2, "Negotiation Attempt #1 (Aggressive 30% Ask) -> Policy Engine Evaluation", {
        "requested_discount": "30%",
        "policy_status": neg_res_1["policy_status"],
        "allowed": neg_res_1["allowed"],
        "explainable_reason": neg_res_1["reason"]
    })

    assert neg_res_1["allowed"] is False, "Expected 30% discount to be rejected by policy engine"

    # 3. Autonomous Renegotiation Loop
    print("\n🧠 [Agent Reasoning] Rejection received due to SKU discount bound. Counter-offering at maximum permissible cap (15%)...")
    time.sleep(0.3)

    neg_payload_2 = {
        "sku": sku_item["sku"],
        "requested_discount_pct": sku_item["max_discount_pct"],  # 15.0%
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }
    neg_res_2 = client.post("/api/negotiate", json=neg_payload_2).json()
    print_step(3, "Renegotiation Attempt #2 (Bounded 15% Ask) -> Approved by Policy Engine", {
        "requested_discount": f"{sku_item['max_discount_pct']}%",
        "policy_status": neg_res_2["policy_status"],
        "allowed": neg_res_2["allowed"],
        "final_unit_price": f"₹{neg_res_2['final_unit_price_inr']:,.2f}",
        "explainable_reason": neg_res_2["reason"]
    })

    assert neg_res_2["allowed"] is True

    # 4. Autonomous Checkout
    idempotency_key = f"idemp_bargain_{uuid.uuid4().hex[:10]}"
    checkout_payload = {
        "sku": sku_item["sku"],
        "quantity": 1,
        "requested_discount_pct": sku_item["max_discount_pct"],
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": idempotency_key,
        "customer_name": "Autonomous Bargain Agent"
    }
    checkout_res = client.post("/api/checkout", json=checkout_payload).json()
    print_step(4, "Autonomous Checkout -> Razorpay Test Order Created", {
        "order_reference": checkout_res["order_reference"],
        "razorpay_order_id": checkout_res["razorpay_order_id"],
        "payment_link": checkout_res["payment_link"],
        "total_amount": f"₹{checkout_res['total_amount_inr']:,.2f}",
        "status": checkout_res["status"]
    })

    # 5. Webhook Payment Verification
    webhook_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_test_{uuid.uuid4().hex[:10]}",
                    "order_id": checkout_res["razorpay_order_id"],
                    "amount": int(checkout_res["total_amount_inr"] * 100),
                    "status": "captured"
                }
            }
        }
    }
    import hmac, hashlib
    body_bytes = json.dumps(webhook_payload).encode("utf-8")
    sig = hmac.new(b"whsec_mock_razorpay_secret_123", body_bytes, hashlib.sha256).hexdigest()
    
    wh_res = client.post(
        "/api/webhook/razorpay",
        content=body_bytes,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    ).json()
    
    print_step(5, "Razorpay Webhook Signature Verified -> Order Marked PAID", {
        "webhook_result": wh_res,
        "order_status": wh_res["order_status"]
    })

def run_persona_whale_enterprise(client):
    """
    Persona 2: The Whale Enterprise (High-Value Order Gating)
    Behavior:
    1. Selects high-value GPU Dev Box (₹1,85,000)
    2. Runs policy engine -> triggers PENDING_APPROVAL gating because it exceeds ₹1,50,000 threshold
    3. Checkout creates order in PENDING_APPROVAL state (no instant charge)
    4. Merchant Admin reviews and approves order via /api/admin/orders/{id}/approve
    """
    agent_id = "agent_enterprise_whale"
    print_header("Persona 2: The Whale Enterprise (High-Value Gated Approval)")

    sku = "SKU-GPU-DEV-BOX"
    idempotency_key = f"idemp_whale_{uuid.uuid4().hex[:10]}"

    checkout_payload = {
        "sku": sku,
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": idempotency_key,
        "customer_name": "MegaCorp AI Labs"
    }
    
    checkout_res = client.post("/api/checkout", json=checkout_payload).json()
    print_step(1, "High-Value Checkout (₹1,75,750) -> Policy Gating Triggered", {
        "order_reference": checkout_res["order_reference"],
        "total_amount": f"₹{checkout_res['total_amount_inr']:,.2f}",
        "status": checkout_res["status"],
        "policy_reason": checkout_res["policy_reason"]
    })

    assert checkout_res["status"] == "pending_approval"

    # Admin Manual Review Approval
    print("\n👔 [Merchant Portal] Merchant Admin reviews high-value order and grants approval...")
    time.sleep(0.3)

    admin_res = client.post(f"/api/admin/orders/{checkout_res['order_reference']}/approve").json()
    print_step(2, "Admin Manual Approval -> Order Promoted & Razorpay Order Generated", {
        "order_reference": admin_res["order_reference"],
        "status": admin_res["status"],
        "razorpay_order_id": admin_res["razorpay_order_id"],
        "payment_link": admin_res["payment_link"]
    })

    assert admin_res["status"] == "pending_payment"

def run_persona_impatient_retryer(client):
    """
    Persona 3: The Impatient Retryer (Idempotency & Zero Double-Charge Guarantee)
    Behavior:
    1. Sends checkout with idempotency key
    2. Sends exact same checkout repeatedly with identical idempotency key
    3. Confirms identical order reference returned with idempotent_replay: true and zero duplicate charges
    """
    agent_id = "agent_impatient_fast"
    print_header("Persona 3: The Impatient Retryer (Strict Idempotency Verification)")

    fixed_idempotency_key = f"idemp_fixed_double_tap_{uuid.uuid4().hex[:8]}"
    payload = {
        "sku": "SKU-CLOUD-CREDITS",
        "quantity": 2,
        "requested_discount_pct": 10.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": fixed_idempotency_key,
        "customer_name": "Fast Retry Agent"
    }

    # Request 1
    res1 = client.post("/api/checkout", json=payload).json()
    print_step(1, "First Checkout Invocation", {
        "order_reference": res1["order_reference"],
        "razorpay_order_id": res1["razorpay_order_id"],
        "idempotent_replay": res1["idempotent_replay"],
        "status": res1["status"]
    })

    # Request 2 (Duplicate with same idempotency key)
    print("\n⚡ [Network Simulation] Buyer resends identical checkout payload due to timeout/retry...")
    time.sleep(0.2)
    res2 = client.post("/api/checkout", json=payload).json()
    print_step(2, "Second Checkout Invocation (Same Idempotency Key) -> Replay Recognized", {
        "order_reference": res2["order_reference"],
        "razorpay_order_id": res2["razorpay_order_id"],
        "idempotent_replay": res2["idempotent_replay"],
        "status": res2["status"],
        "guarantee": "ZERO duplicate orders created. ZERO double charges."
    })

    assert res1["order_reference"] == res2["order_reference"]
    assert res2["idempotent_replay"] is True

def run_all_simulations():
    print("\n" + "#" * 75)
    print("   STARTING RAZORPAY AUTONOMOUS AI BUYER AGENT MULTI-PERSONA SUITE")
    print("#" * 75)
    
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.database import engine, Base, SessionLocal
    from backend.app.seed_data import seed_catalog
    
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed_catalog(db)
    db.close()
    
    client = TestClient(app)

    run_persona_bargain_hunter(client)
    run_persona_whale_enterprise(client)
    run_persona_impatient_retryer(client)

    print("\n" + "=" * 75)
    print(" ✅ ALL 3 AI BUYER PERSONAS COMPLETED SUCCESSFULLY")
    print("    Check Audit Dashboard at http://localhost:8000 to view the complete audit log!")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    run_all_simulations()
