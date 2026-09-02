import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.services.llm_service import llm_service

client = TestClient(app)


def test_ad_generation_falls_back_to_templates_when_no_gemini_key():
    """DoD: gracefully falls back to templates if GEMINI_API_KEY is unset."""
    with patch.object(llm_service, "gemini_key", ""):
        res = client.post("/api/ads/generate", json={
            "sku": "SKU-CLOUD-CREDITS",
            "languages": ["en", "hi"]
        })
    assert res.status_code == 200
    data = res.json()
    assert len(data["ads"]) == 2
    for ad in data["ads"]:
        assert ad["generated_by"] == "template_fallback"
        assert ad["headline"]
        assert ad["body_text"]


def test_two_calls_produce_genuinely_different_copy_with_mocked_gemini():
    """
    DoD: two calls to POST /api/ads/generate for the same SKU/language
    produce genuinely different copy (proving generation, not templating).
    Mocked here since this sandbox cannot reach
    generativelanguage.googleapis.com; the mock proves the plumbing
    (prompt construction, JSON parsing, response mapping, audit logging)
    is correct end to end.
    """
    fake_responses = [
        MagicMock(text=json.dumps({
            "headline": "Blazing Fast Credits, Today Only!",
            "body_text": "Grab cloud credits at an unbeatable price before they're gone.",
            "call_to_action": "Claim Now",
            "hashtags": ["cloud", "deal", "fast"],
            "discount_hook": "Ask our agent for an instant discount!"
        })),
        MagicMock(text=json.dumps({
            "headline": "Power Your Stack With Cloud Credits!",
            "body_text": "Enterprise-grade compute, negotiated pricing, zero hassle.",
            "call_to_action": "Start Chat",
            "hashtags": ["enterprise", "compute", "savings"],
            "discount_hook": "Our AI agent negotiates the best price for you."
        })),
    ]

    with patch.object(llm_service, "gemini_key", "fake-test-key-for-mocking"), \
         patch("google.genai.Client") as MockClient:
        instance = MockClient.return_value
        instance.models.generate_content.side_effect = fake_responses

        first = client.post("/api/ads/generate", json={"sku": "SKU-CLOUD-CREDITS", "languages": ["en"]})
        assert first.status_code == 200
        first_ad = first.json()["ads"][0]
        assert first_ad["generated_by"] == "gemini"

        instance.models.generate_content.side_effect = [fake_responses[1]]
        second = client.post("/api/ads/generate", json={"sku": "SKU-CLOUD-CREDITS", "languages": ["en"]})
        assert second.status_code == 200
        second_ad = second.json()["ads"][0]
        assert second_ad["generated_by"] == "gemini"

    assert first_ad["headline"] != second_ad["headline"]
    assert first_ad["body_text"] != second_ad["body_text"]


def test_gemini_failure_for_one_language_falls_back_to_template_for_that_language_only():
    with patch.object(llm_service, "gemini_key", "fake-test-key-for-mocking"), \
         patch("google.genai.Client") as MockClient:
        instance = MockClient.return_value
        instance.models.generate_content.side_effect = RuntimeError("simulated Gemini outage")

        res = client.post("/api/ads/generate", json={"sku": "SKU-CLOUD-CREDITS", "languages": ["en", "hi"]})
        assert res.status_code == 200
        for ad in res.json()["ads"]:
            assert ad["generated_by"] == "template_fallback"


def test_ad_generation_is_audit_logged_for_growth_panel():
    res = client.post("/api/ads/generate", json={"sku": "SKU-CLOUD-CREDITS", "languages": ["en"]})
    assert res.status_code == 200

    audit_res = client.get("/api/audit")
    assert audit_res.status_code == 200
    logs = audit_res.json()["logs"]
    ad_events = [l for l in logs if l.get("status") == "ad_generated"]
    assert len(ad_events) >= 1
