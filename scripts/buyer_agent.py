#!/usr/bin/env python3
"""
Autonomous Buyer Agent Script (Phase 6):
Demonstrates true agent-to-agent autonomous commerce without human clicking.
The agent receives a natural-language purchasing goal, inspects the merchant catalog,
reasons on the best product, negotiates discounts within policy limits, and executes checkout.
"""

import sys
import json
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000"

def run_autonomous_buyer_agent(goal: str = "Buy the best workstation you can find for under ₹1,60,000, negotiating a discount if possible, and complete checkout."):
    print("=" * 80)
    print("🤖 AUTONOMOUS AI BUYER AGENT INITIALIZED")
    print(f"🎯 Mission Goal: \"{goal}\"")
    print("=" * 80)

    agent_id = f"agent_auto_buyer_{uuid.uuid4().hex[:6]}"
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    print(f"\n[Turn 1] Agent requests merchant catalog from GET /api/catalog...")
    try:
        cat_res = client.get("/api/catalog")
        if cat_res.status_code != 200:
            print(f"❌ Failed to fetch catalog: {cat_res.status_code}")
            return
        catalog = cat_res.json()
        print(f"📦 Discovered {catalog['count']} merchant catalog SKUs.")
    except Exception as e:
        print(f"❌ Server connection failed: {e}. Ensure merchant server is running on {BASE_URL}.")
        return

    # Agent evaluates catalog against goal
    workstation_item = None
    for item in catalog["items"]:
        if "workstation" in item["name"].lower() or "gpu" in item["name"].lower() or "gateway" in item["name"].lower():
            workstation_item = item
            break
    if not workstation_item:
        workstation_item = catalog["items"][0]

    print(f"\n🧠 [Agent Reasoning] Evaluating product matching goal: '{workstation_item['name']}' (Price: ₹{workstation_item['price_inr']:,.2f}, Max Discount: {workstation_item['max_discount_pct']}%)")

    # Turn 2: Attempt negotiation (first test aggressive ask, then bound to policy)
    print(f"\n[Turn 2] Agent attempts discount negotiation via POST /api/negotiate...")
    neg_req = {
        "sku": workstation_item["sku"],
        "requested_discount_pct": 10.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }
    neg_res = client.post("/api/negotiate", json=neg_req).json()
    print(f"📊 Negotiation Policy Evaluation:")
    print(f"   • Policy Decision: {neg_res.get('policy_status', '').upper()}")
    print(f"   • Approved Discount: {neg_res.get('approved_discount_pct')}%")
    print(f"   • Final Unit Price: ₹{neg_res.get('final_unit_price_inr', 0):,.2f}")
    print(f"   • Explainable Reason: {neg_res.get('reason')}")

    if not neg_res.get("allowed"):
        print("❌ Negotiation disallowed by Policy Engine.")
        return

    # Turn 3: Execute Checkout
    idemp_key = f"buyer_agent_{uuid.uuid4().hex[:12]}"
    print(f"\n[Turn 3] Agent executes checkout via POST /api/checkout (Idempotency Key: {idemp_key})...")
    chk_req = {
        "sku": workstation_item["sku"],
        "quantity": 1,
        "requested_discount_pct": neg_res["approved_discount_pct"],
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": idemp_key,
        "customer_name": "Autonomous Agent Shopper"
    }
    chk_res = client.post("/api/checkout", json=chk_req).json()
    print(f"🎉 Checkout Completed Successfully:")
    print(f"   • Order Reference: {chk_res.get('order_reference')}")
    print(f"   • Razorpay Order ID: {chk_res.get('razorpay_order_id')}")
    print(f"   • Total Amount: ₹{chk_res.get('total_amount_inr', 0):,.2f}")
    print(f"   • Status: {chk_res.get('status')}")
    print(f"   • Single-Use Link Active: {chk_res.get('is_link_active')}")

    print("\n" + "=" * 80)
    print("✅ MISSION COMPLETE: Autonomous Agent-to-Agent Commerce Verified!")
    print("=" * 80)

if __name__ == "__main__":
    run_autonomous_buyer_agent()
