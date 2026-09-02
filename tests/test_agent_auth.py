import uuid
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

SKU = "SKU-CLOUD-CREDITS"


def test_register_issues_real_random_key_not_derived_from_agent_id():
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert res.status_code == 201
    body = res.json()
    assert body["agent_id"] == agent_id
    key = body["agent_key"]
    # Real secret: long, and NOT the old guessable default "ak_{agent_id}"
    assert len(key) >= 32
    assert key != f"ak_{agent_id}"
    assert agent_id not in key


def test_registering_same_agent_twice_is_rejected_not_reissued():
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    first = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert first.status_code == 201
    first_key = first.json()["agent_key"]

    second = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert second.status_code == 409
    # Original key must remain valid and unrotated
    verify = client.post("/api/negotiate", json={
        "sku": SKU,
        "requested_discount_pct": 5.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }, headers={"X-Agent-Key": first_key})
    assert verify.status_code == 200


def test_reproduction_spoofed_identity_now_returns_401():
    """
    Exact reproduction from the A1 bug report:
    1. Register agent_id=X (issues a real key).
    2. A second, unrelated request reuses agent_id=X with NO key.
    Before the fix this returned 200 and inherited X's trust score.
    After the fix it must return 401.
    """
    agent_id = f"agent_spoof_target_{uuid.uuid4().hex[:8]}"

    reg = client.post("/api/agents/register", json={"agent_id": agent_id})
    assert reg.status_code == 201

    spoofed = client.post("/api/negotiate", json={
        "sku": SKU,
        "requested_discount_pct": 5.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
        # deliberately NO X-Agent-Key header
    })
    assert spoofed.status_code == 401
    assert "X-Agent-Key" in spoofed.json()["detail"]


def test_wrong_key_for_existing_agent_is_rejected():
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    client.post("/api/agents/register", json={"agent_id": agent_id})

    res = client.post("/api/checkout", json={
        "sku": SKU,
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": f"idemp_{uuid.uuid4().hex}"
    }, headers={"X-Agent-Key": "totally-wrong-guessed-key"})
    assert res.status_code == 401


def test_first_touch_via_negotiate_without_prior_registration_still_provisions_a_real_key():
    """
    An agent that skips /api/agents/register and just calls /api/negotiate
    with a brand-new agent_id and no key must still get a freshly minted,
    non-guessable key back (not silently authenticated with a derived default).
    """
    agent_id = f"agent_firsttouch_{uuid.uuid4().hex[:8]}"

    first = client.post("/api/negotiate", json={
        "sku": SKU,
        "requested_discount_pct": 5.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    })
    assert first.status_code == 200
    issued_key = first.json()["issued_agent_key"]
    assert issued_key
    assert issued_key != f"ak_{agent_id}"

    # A follow-up call with no key must now be rejected, not silently trusted.
    second_no_key = client.post("/api/negotiate", json={
        "sku": SKU,
        "requested_discount_pct": 5.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    })
    assert second_no_key.status_code == 401

    # The correct issued key still works.
    second_with_key = client.post("/api/negotiate", json={
        "sku": SKU,
        "requested_discount_pct": 5.0,
        "quantity": 1,
        "agent_id": agent_id,
        "actor_type": "ai_agent"
    }, headers={"X-Agent-Key": issued_key})
    assert second_with_key.status_code == 200
    # Key is only issued once - a repeat authenticated call must not reissue it
    assert second_with_key.json()["issued_agent_key"] is None


def test_checkout_also_enforces_agent_identity():
    agent_id = f"agent_checkout_{uuid.uuid4().hex[:8]}"
    reg = client.post("/api/agents/register", json={"agent_id": agent_id})
    key = reg.json()["agent_key"]

    ok = client.post("/api/checkout", json={
        "sku": SKU,
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": f"idemp_{uuid.uuid4().hex}"
    }, headers={"X-Agent-Key": key})
    assert ok.status_code == 200

    spoofed = client.post("/api/checkout", json={
        "sku": SKU,
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "actor_type": "ai_agent",
        "agent_id": agent_id,
        "idempotency_key": f"idemp_{uuid.uuid4().hex}"
    })
    assert spoofed.status_code == 401
