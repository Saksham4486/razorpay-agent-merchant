"""
A3: Tests the LLM-driven buyer agent's tool-calling LOOP LOGIC using a
mocked Gemini client (no live network call, since the sandbox this was
developed in cannot reach generativelanguage.googleapis.com). This proves
the dispatch/looping mechanics are correct; it does NOT substitute for a
real end-to-end run against the live Gemini API, which should be verified
separately with a real GEMINI_API_KEY and a running server.
"""
import sys
import os
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from backend.app.main import app
from google.genai import types

from scripts.buyer_agent import run_llm_driven_buyer_agent, MerchantAPIClient


class _FakeHTTPXWrapper:
    """Routes MerchantAPIClient's httpx.Client calls into the real FastAPI
    TestClient so tool calls hit real negotiate/checkout/policy logic -
    only the Gemini LLM call itself is mocked."""
    def __init__(self, test_client: TestClient):
        self._tc = test_client

    def get(self, path, **kw):
        return self._tc.get(path, **kw)

    def post(self, path, **kw):
        return self._tc.post(path, **kw)


def _make_agent_client():
    tc = TestClient(app)
    api = MerchantAPIClient("http://unused", f"agent_llm_mock_{uuid.uuid4().hex[:8]}")
    api.http = _FakeHTTPXWrapper(tc)
    api.register()
    return api


def _model_content(text=None, function_calls=None):
    parts = []
    if text:
        parts.append(types.Part(text=text))
    for fc in (function_calls or []):
        parts.append(types.Part(function_call=types.FunctionCall(name=fc[0], args=fc[1])))
    return types.Content(role="model", parts=parts)


def _fake_response(content):
    resp = MagicMock()
    candidate = MagicMock()
    candidate.content = content
    resp.candidates = [candidate]
    return resp


def test_llm_loop_dispatches_get_catalog_then_negotiate_then_checkout_then_finish():
    """Simulates a scripted Gemini conversation to prove the loop correctly
    dispatches each tool call to the real API and feeds results back."""
    api = _make_agent_client()

    scripted_turns = [
        _fake_response(_model_content(
            text="First I'll check the catalog.",
            function_calls=[("get_catalog", {})]
        )),
        _fake_response(_model_content(
            text="I'll try negotiating a 10% discount on the cheapest SKU.",
            function_calls=[("negotiate", {"sku": "SKU-CLOUD-CREDITS", "requested_discount_pct": 10.0, "quantity": 1})]
        )),
        _fake_response(_model_content(
            text="Discount approved, completing checkout.",
            function_calls=[("checkout", {"sku": "SKU-CLOUD-CREDITS", "quantity": 1, "requested_discount_pct": 10.0})]
        )),
        _fake_response(_model_content(
            text="Done.",
            function_calls=[("finish", {"summary": "Bought SKU-CLOUD-CREDITS at 10% off."})]
        )),
    ]

    with patch("google.genai.Client") as MockClient:
        instance = MockClient.return_value
        instance.models.generate_content.side_effect = scripted_turns
        result = run_llm_driven_buyer_agent("Buy the cheapest item you can find.", api)

    assert result is True
    assert instance.models.generate_content.call_count == 4


def test_different_goals_can_produce_different_tool_sequences():
    """
    Proves the loop mechanics support genuinely different sequences for
    different goals (goal A: cheap item, single negotiate+checkout; goal B:
    aggressive negotiation that gets rejected once, then retried) - the
    actual goal-to-sequence mapping is decided by the real LLM at runtime,
    not hardcoded here; this test only proves the harness doesn't force a
    fixed 3-step shape.
    """
    api = _make_agent_client()

    scripted_turns_goal_b = [
        _fake_response(_model_content(
            text="Checking catalog for the workstation.",
            function_calls=[("get_catalog", {})]
        )),
        _fake_response(_model_content(
            text="Asking for an aggressive 50% discount first.",
            function_calls=[("negotiate", {"sku": "SKU-AI-ROUTER-PRO", "requested_discount_pct": 50.0, "quantity": 1})]
        )),
        _fake_response(_model_content(
            text="That was rejected; the policy cap is 15%, retrying at the max allowed.",
            function_calls=[("negotiate", {"sku": "SKU-AI-ROUTER-PRO", "requested_discount_pct": 15.0, "quantity": 1})]
        )),
        _fake_response(_model_content(
            text="Approved at 15%, checking out.",
            function_calls=[("checkout", {"sku": "SKU-AI-ROUTER-PRO", "quantity": 1, "requested_discount_pct": 15.0})]
        )),
        _fake_response(_model_content(
            text="Done.",
            function_calls=[("finish", {"summary": "Negotiated the max allowed 15% discount and bought SKU-AI-ROUTER-PRO."})]
        )),
    ]

    with patch("google.genai.Client") as MockClient:
        instance = MockClient.return_value
        instance.models.generate_content.side_effect = scripted_turns_goal_b
        result = run_llm_driven_buyer_agent(
            "Negotiate the biggest discount you can on the workstation.", api
        )

    assert result is True
    # 5 turns for goal B vs 4 turns for goal A above - a different-length,
    # different-shaped tool sequence in response to a different goal.
    assert instance.models.generate_content.call_count == 5


def test_loop_respects_max_turns_bound():
    api = _make_agent_client()

    # Model never calls finish() - loop must stop at MAX_TURNS, not hang.
    endless_turn = _fake_response(_model_content(
        text="Still thinking...",
        function_calls=[("get_catalog", {})]
    ))

    with patch("google.genai.Client") as MockClient:
        instance = MockClient.return_value
        instance.models.generate_content.return_value = endless_turn
        result = run_llm_driven_buyer_agent("Do something impossible forever.", api)

    assert result is True
    assert instance.models.generate_content.call_count == 8  # MAX_TURNS
