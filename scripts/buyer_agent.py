#!/usr/bin/env python3
"""
Autonomous Buyer Agent Script (A3 - genuinely LLM-driven).

Unlike the old fixed 3-step script, this agent is given a natural-language
purchasing goal and decides its own sequence of tool calls (get_catalog,
negotiate, checkout) using a real Gemini tool-calling loop. The LLM only
DECIDES what to call and with what arguments; it never computes prices or
discounts itself - check_policy() on the server remains the sole source of
truth for every number, completely unchanged.

Requires GEMINI_API_KEY to be set (see .env). Without a key, or if the
Gemini call fails, this falls back to a single deterministic negotiate+
checkout pass so the script still completes - but that fallback path does
NOT satisfy A3's "genuinely different behavior per goal" requirement; only
the real LLM loop does.

Usage:
    python scripts/buyer_agent.py "Buy the cheapest item you can find."
    python scripts/buyer_agent.py "Negotiate the biggest discount you can on the workstation."
"""
import sys
import os
import json
import uuid
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.app.config import settings

BASE_URL = os.getenv("BUYER_AGENT_BASE_URL", "http://127.0.0.1:8000")
MAX_TURNS = 8

DEFAULT_GOAL = "Buy the best workstation you can find for under ₹1,60,000, negotiating a discount if possible, and complete checkout."


class MerchantAPIClient:
    """Thin wrapper around the real HTTP API. This is the ONLY place that
    talks to the server; the LLM never sees or influences pricing math -
    it only picks which of these to call and with what arguments."""

    def __init__(self, base_url: str, agent_id: str):
        self.http = httpx.Client(base_url=base_url, timeout=15.0)
        self.agent_id = agent_id
        self.agent_key = None

    def register(self):
        res = self.http.post("/api/agents/register", json={"agent_id": self.agent_id})
        if res.status_code == 201:
            self.agent_key = res.json()["agent_key"]
        elif res.status_code == 409:
            raise RuntimeError(
                f"Agent '{self.agent_id}' is already registered from a previous run and its key "
                "was not persisted by this script. Use a fresh agent_id."
            )
        else:
            raise RuntimeError(f"Agent registration failed: {res.status_code} {res.text}")
        return {"agent_id": self.agent_id, "registered": True}

    def _auth_headers(self):
        return {"X-Agent-Key": self.agent_key} if self.agent_key else {}

    def get_catalog(self) -> dict:
        res = self.http.get("/api/catalog")
        return res.json()

    def negotiate(self, sku: str, requested_discount_pct: float, quantity: int = 1) -> dict:
        payload = {
            "sku": sku,
            "requested_discount_pct": requested_discount_pct,
            "quantity": quantity,
            "agent_id": self.agent_id,
            "actor_type": "ai_agent"
        }
        res = self.http.post("/api/negotiate", json=payload, headers=self._auth_headers())
        return res.json()

    def checkout(self, sku: str, quantity: int, requested_discount_pct: float) -> dict:
        idemp_key = f"buyer_agent_{uuid.uuid4().hex[:12]}"
        payload = {
            "sku": sku,
            "quantity": quantity,
            "requested_discount_pct": requested_discount_pct,
            "actor_type": "ai_agent",
            "agent_id": self.agent_id,
            "idempotency_key": idemp_key,
            "customer_name": "Autonomous LLM Buyer Agent"
        }
        res = self.http.post("/api/checkout", json=payload, headers=self._auth_headers())
        return res.json()


def build_tool_declarations():
    """Gemini function-calling tool schema. Mirrors llm_service.py's
    tool-calling pattern (parse_chat_intent_with_llm) but here the LLM
    drives a full multi-turn loop rather than a single classification."""
    from google.genai import types

    return types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="get_catalog",
            description="Fetch the full merchant catalog: SKUs, names, prices, stock, and each SKU's max_discount_pct.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}, required=[])
        ),
        types.FunctionDeclaration(
            name="negotiate",
            description=(
                "Ask the merchant's policy engine to evaluate a requested discount for a SKU. "
                "Returns whether it's allowed, the approved discount, and an explainable reason. "
                "Does NOT place an order."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "sku": types.Schema(type=types.Type.STRING, description="Catalog SKU identifier"),
                    "requested_discount_pct": types.Schema(type=types.Type.NUMBER, description="Discount percent requested, 0-100"),
                    "quantity": types.Schema(type=types.Type.INTEGER, description="Units requested")
                },
                required=["sku", "requested_discount_pct", "quantity"]
            )
        ),
        types.FunctionDeclaration(
            name="checkout",
            description=(
                "Finalize a purchase for a SKU at a given (already policy-approved) discount. "
                "Creates a real order and Razorpay payment link. Only call this once you have "
                "an approved discount from negotiate()."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "sku": types.Schema(type=types.Type.STRING),
                    "quantity": types.Schema(type=types.Type.INTEGER),
                    "requested_discount_pct": types.Schema(type=types.Type.NUMBER)
                },
                required=["sku", "quantity", "requested_discount_pct"]
            )
        ),
        types.FunctionDeclaration(
            name="finish",
            description="Call this once the goal has been fully accomplished (or is impossible), with a short summary.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"summary": types.Schema(type=types.Type.STRING)},
                required=["summary"]
            )
        )
    ])


def run_llm_driven_buyer_agent(goal: str, api: MerchantAPIClient) -> bool:
    """
    Real Gemini tool-calling loop. The model decides its own sequence of
    calls (bounded to MAX_TURNS) and we print its reasoning at each step.
    Returns True if the LLM loop ran to completion, False if it fell back.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    tools = build_tool_declarations()
    config = types.GenerateContentConfig(tools=[tools])

    system_context = (
        "You are an autonomous purchasing agent for an enterprise store. "
        "You do NOT decide prices or discounts - the merchant's policy engine does that "
        "via the negotiate() and checkout() tools. Your job is only to decide WHICH tools "
        "to call, in WHAT order, and with WHAT arguments, to accomplish the buyer's goal. "
        "Explain your reasoning briefly before each tool call. When negotiate() rejects a "
        "discount, read its 'reason' and adjust your next request accordingly instead of "
        "repeating the same request. Call finish() with a short summary once done."
    )

    contents = [
        types.Content(role="user", parts=[types.Part(text=f"{system_context}\n\nGOAL: {goal}")])
    ]

    dispatch = {
        "get_catalog": lambda **kw: api.get_catalog(),
        "negotiate": lambda **kw: api.negotiate(**kw),
        "checkout": lambda **kw: api.checkout(**kw),
    }

    for turn in range(1, MAX_TURNS + 1):
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=contents,
            config=config
        )
        candidate = response.candidates[0]
        contents.append(candidate.content)

        text_parts = [p.text for p in candidate.content.parts if getattr(p, "text", None)]
        if text_parts:
            print(f"\n🧠 [Turn {turn}] Agent reasoning: {' '.join(text_parts)}")

        function_calls = [p.function_call for p in candidate.content.parts if getattr(p, "function_call", None)]

        if not function_calls:
            print(f"\n[Turn {turn}] No tool call issued by the model; ending loop.")
            return True

        response_parts = []
        stop = False
        for fc in function_calls:
            args = dict(fc.args) if fc.args else {}
            print(f"\n⚡ [Turn {turn}] Agent calls: {fc.name}({json.dumps(args)})")

            if fc.name == "finish":
                print(f"✅ Agent finished: {args.get('summary', '(no summary)')}")
                stop = True
                result = {"acknowledged": True}
            elif fc.name in dispatch:
                try:
                    result = dispatch[fc.name](**args)
                    print(f"📊 Result: {json.dumps(result, indent=2, default=str)[:800]}")
                except Exception as e:
                    result = {"error": str(e)}
                    print(f"❌ Tool call failed: {e}")
            else:
                result = {"error": f"Unknown tool {fc.name}"}

            response_parts.append(
                types.Part.from_function_response(name=fc.name, response={"result": result})
            )

        # Function responses go back with role="user" per the current
        # Gemini API (the older "tool" role string is no longer accepted -
        # see 400 INVALID_ARGUMENT: "Role 'tool' is not supported").
        contents.append(types.Content(role="user", parts=response_parts))

        if stop:
            return True

    print(f"\n⚠️ Reached MAX_TURNS ({MAX_TURNS}) without the agent calling finish().")
    return True


def run_deterministic_fallback(api: MerchantAPIClient):
    """
    Used only when GEMINI_API_KEY is unset or the LLM call errors. This is
    intentionally the OLD fixed-script behavior - it exists so the script
    still completes a purchase in a degraded environment, but it does NOT
    satisfy A3's requirement that different goals produce different
    behavior. That property only holds for the real LLM loop above.
    """
    print("\n⚠️ Falling back to deterministic single-pass negotiate+checkout (no LLM key or LLM call failed).")
    catalog = api.get_catalog()
    item = catalog["items"][0]
    neg = api.negotiate(item["sku"], requested_discount_pct=10.0, quantity=1)
    print(f"Negotiation: {neg.get('policy_status')} - {neg.get('reason')}")
    if neg.get("allowed"):
        chk = api.checkout(item["sku"], 1, neg["approved_discount_pct"])
        print(f"Checkout: {chk.get('status')} - {chk.get('order_reference')}")


def main():
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL

    print("=" * 80)
    print("🤖 AUTONOMOUS AI BUYER AGENT (A3 - genuinely LLM-driven)")
    print(f"🎯 Mission Goal: \"{goal}\"")
    print("=" * 80)

    agent_id = f"agent_llm_buyer_{uuid.uuid4().hex[:8]}"
    api = MerchantAPIClient(BASE_URL, agent_id)

    try:
        api.register()
        print(f"🔑 Registered agent '{agent_id}' and obtained a real X-Agent-Key.")
    except Exception as e:
        print(f"❌ Could not reach merchant server / register agent: {e}")
        print(f"   Ensure the server is running on {BASE_URL}.")
        return

    if not settings.GEMINI_API_KEY:
        print("\n⚠️ No GEMINI_API_KEY configured in .env.")
        run_deterministic_fallback(api)
        return

    try:
        run_llm_driven_buyer_agent(goal, api)
    except Exception as e:
        print(f"\n❌ LLM-driven loop failed: {e}")
        run_deterministic_fallback(api)
        return

    print("\n" + "=" * 80)
    print("✅ MISSION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
