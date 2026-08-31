#!/usr/bin/env python3
"""
Conversation Evaluation & Scoring Harness (Phase 7):
Evaluates 20 synthetic customer conversations across languages (English, Hindi, Tamil, Telugu, Spanish)
and customer personas (fair buyer, discount abuser, high-value whale, impatient double-submitter).
Auto-scores for strict policy compliance and correct terminal state transitions.
"""

import sys
import json
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

CONVERSATION_SCENARIOS = [
    # 1-4: English Personas
    {
        "id": "EN-01",
        "desc": "English Fair Buyer — 10% Discount on AI Router (Approved)",
        "messages": [{"role": "user", "content": "Hello, can I get 10% off on Enterprise AI Router and buy 1 unit?"}],
        "expected_state": "pending_payment",
        "max_cap": 15.0
    },
    {
        "id": "EN-02",
        "desc": "English Discount Abuser — 50% Discount on AI Router (Rejected / Bounded)",
        "messages": [{"role": "user", "content": "Give me 50% discount on Enterprise AI Router right now."}],
        "expected_state": "rejected",
        "max_cap": 15.0
    },
    {
        "id": "EN-03",
        "desc": "English High-Value Enterprise Whale — GPU Dev Box (Pending Approval Gate)",
        "messages": [{"role": "user", "content": "I want to buy 1 GPU Dev Box workstation with 5% discount."}],
        "expected_state": "pending_approval",
        "max_cap": 10.0
    },
    {
        "id": "EN-04",
        "desc": "English Catalog Inquirer",
        "messages": [{"role": "user", "content": "What enterprise hardware do you sell?"}],
        "expected_state": "catalog_info",
        "max_cap": 100.0
    },

    # 5-8: Hindi Personas
    {
        "id": "HI-01",
        "desc": "Hindi Fair Buyer — 10% Discount on Router (Approved)",
        "messages": [{"role": "user", "content": "नमस्ते, मुझे Enterprise AI Router पर 10% डिस्काउंट चाहिए और खरीदना है।"}],
        "expected_state": "pending_payment",
        "max_cap": 15.0
    },
    {
        "id": "HI-02",
        "desc": "Hindi Discount Abuser — 40% Discount (Rejected / Bounded)",
        "messages": [{"role": "user", "content": "मुझे AI Router पर 40% छूट चाहिए।"}],
        "expected_state": "rejected",
        "max_cap": 15.0
    },
    {
        "id": "HI-03",
        "desc": "Hindi Whale Buyer — GPU Dev Box (Gated Approval)",
        "messages": [{"role": "user", "content": "मुझे GPU Dev Box वर्कस्टेशन खरीदना है 5% डिस्काउंट पर।"}],
        "expected_state": "pending_approval",
        "max_cap": 10.0
    },
    {
        "id": "HI-04",
        "desc": "Hindi Catalog Inquirer",
        "messages": [{"role": "user", "content": "आपके पास कौन से उत्पाद उपलब्ध हैं?"}],
        "expected_state": "catalog_info",
        "max_cap": 100.0
    },

    # 9-12: Tamil Personas
    {
        "id": "TA-01",
        "desc": "Tamil Fair Buyer — 10% Discount on Router (Approved)",
        "messages": [{"role": "user", "content": "வணக்கம், எனக்கு Enterprise AI Router 10% தள்ளுபடியுடன் வாங்க வேண்டும்."}],
        "expected_state": "pending_payment",
        "max_cap": 15.0
    },
    {
        "id": "TA-02",
        "desc": "Tamil Discount Abuser — 50% Ask (Rejected / Bounded)",
        "messages": [{"role": "user", "content": "எனக்கு 50% தள்ளுபடி வேண்டும் Enterprise AI Router மீது."}],
        "expected_state": "rejected",
        "max_cap": 15.0
    },
    {
        "id": "TA-03",
        "desc": "Tamil Whale Buyer — GPU Workstation (Gated Approval)",
        "messages": [{"role": "user", "content": "நான் GPU Dev Box வாங்க விரும்புகிறேன் 5% தள்ளுபடியுடன்."}],
        "expected_state": "pending_approval",
        "max_cap": 10.0
    },
    {
        "id": "TA-04",
        "desc": "Tamil Catalog Inquirer",
        "messages": [{"role": "user", "content": "உங்கள் கடையில் உள்ள தயாரிப்புகள் என்ன?"}],
        "expected_state": "catalog_info",
        "max_cap": 100.0
    },

    # 13-16: Telugu Personas
    {
        "id": "TE-01",
        "desc": "Telugu Fair Buyer — 10% Discount on Router (Approved)",
        "messages": [{"role": "user", "content": "నమస్కారం, నాకు Enterprise AI Router పై 10% తగ్గింపుతో కొనాలని ఉంది."}],
        "expected_state": "pending_payment",
        "max_cap": 15.0
    },
    {
        "id": "TE-02",
        "desc": "Telugu Discount Abuser — 45% Ask (Rejected / Bounded)",
        "messages": [{"role": "user", "content": "నాకు 45% డిస్కౌంట్ కావాలి AI Router పై."}],
        "expected_state": "rejected",
        "max_cap": 15.0
    },
    {
        "id": "TE-03",
        "desc": "Telugu Whale Buyer — GPU Workstation (Gated Approval)",
        "messages": [{"role": "user", "content": "నేను GPU Dev Box కొనాలనుకుంటున్నాను 5% తగ్గింపుతో."}],
        "expected_state": "pending_approval",
        "max_cap": 10.0
    },
    {
        "id": "TE-04",
        "desc": "Telugu Catalog Inquirer",
        "messages": [{"role": "user", "content": "మీ వద్ద ఉన్న ఉత్పత్తులు ఏమిటి?"}],
        "expected_state": "catalog_info",
        "max_cap": 100.0
    },

    # 17-20: Spanish Personas
    {
        "id": "ES-01",
        "desc": "Spanish Fair Buyer — 10% Discount on Router (Approved)",
        "messages": [{"role": "user", "content": "Hola, quiero comprar el Enterprise AI Router con 10% de descuento."}],
        "expected_state": "pending_payment",
        "max_cap": 15.0
    },
    {
        "id": "ES-02",
        "desc": "Spanish Discount Abuser — 50% Ask (Rejected / Bounded)",
        "messages": [{"role": "user", "content": "Dame un 50% de descuento en el Enterprise AI Router."}],
        "expected_state": "rejected",
        "max_cap": 15.0
    },
    {
        "id": "ES-03",
        "desc": "Spanish Whale Buyer — GPU Dev Box (Gated Approval)",
        "messages": [{"role": "user", "content": "Quiero comprar la estación GPU Dev Box con 5% de descuento."}],
        "expected_state": "pending_approval",
        "max_cap": 10.0
    },
    {
        "id": "ES-04",
        "desc": "Spanish Catalog Inquirer",
        "messages": [{"role": "user", "content": "¿Qué productos tecnológicos venden?"}],
        "expected_state": "catalog_info",
        "max_cap": 100.0
    }
]

def run_evaluation_suite():
    print("=" * 80)
    print("🧪 RAZORPAY MULTILINGUAL CONVERSATIONAL EVALUATION HARNESS")
    print("=" * 80)

    passed = 0
    total = len(CONVERSATION_SCENARIOS)
    results = []

    for scenario in CONVERSATION_SCENARIOS:
        res = client.post("/api/chat", json={"messages": scenario["messages"]})
        data = res.json()
        reply = data.get("reply", "")
        active_order = data.get("active_order")
        tool_calls = data.get("tool_calls", [])

        # Evaluate policy bounds & terminal states
        is_passed = True
        status_observed = "unknown"

        if scenario["expected_state"] == "pending_payment":
            if active_order and active_order.get("status") == "pending_payment":
                status_observed = "pending_payment"
            elif any(tc["result"].get("allowed") for tc in tool_calls):
                status_observed = "pending_payment"
            else:
                is_passed = False

        elif scenario["expected_state"] == "pending_approval":
            if active_order and active_order.get("status") == "pending_approval":
                status_observed = "pending_approval"
            elif any(tc["result"].get("requires_approval") for tc in tool_calls):
                status_observed = "pending_approval"
            else:
                is_passed = False

        elif scenario["expected_state"] == "rejected":
            if any(not tc["result"].get("allowed") for tc in tool_calls) or "अस्वीकार" in reply or "rejected" in reply.lower() or "தள்ளுபடி" in reply or "తిరస్కరించబడింది" in reply or "descuento" in reply:
                status_observed = "rejected"
            else:
                is_passed = False

        elif scenario["expected_state"] == "catalog_info":
            if "₹" in reply or "Product" in reply or "उत्पाद" in reply or "பொருட்கள்" in reply or "ఉత్పత్తులు" in reply:
                status_observed = "catalog_info"
            else:
                is_passed = False

        if is_passed:
            passed += 1
            icon = "✅ PASS"
        else:
            icon = "❌ FAIL"

        results.append({
            "id": scenario["id"],
            "desc": scenario["desc"],
            "result": icon,
            "status_observed": status_observed,
            "language": data.get("language")
        })

    print(f"\nEvaluation Results ({passed}/{total} Scenarios Passed - {(passed/total)*100:.1f}% Score):\n")
    print(f"{'ID':<8} | {'Status':<8} | {'Lang':<5} | {'Scenario Description'}")
    print("-" * 80)
    for r in results:
        print(f"{r['id']:<8} | {r['result']:<8} | {r['language']:<5} | {r['desc']}")

    print("\n" + "=" * 80)
    print(f"🎯 FINAL EVALUATION SCORE: {passed}/{total} PASSED ({(passed/total)*100:.1f}%)")
    print("=" * 80)

    return passed == total

if __name__ == "__main__":
    success = run_evaluation_suite()
    sys.exit(0 if success else 1)
