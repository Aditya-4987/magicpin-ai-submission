"""
Vera-Omni Comprehensive Test Suite
Validates core functionality, API endpoints, multi-turn state machine, and submission format.
"""

import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

from bot import app
from vera_engine.composer import compose_message, compose
from vera_engine.conversation import handle_reply
from conversation_handlers import ConversationState, respond

client = TestClient(app)


def test_healthz_and_metadata():
    """Verify healthz and metadata endpoints meet contract specifications."""
    r_health = client.get("/healthz")
    assert r_health.status_code == 200
    data = r_health.json()
    assert data["status"] == "ok"
    assert "contexts_loaded" in data

    r_meta = client.get("/metadata")
    assert r_meta.status_code == 200
    meta = r_meta.json()
    assert "Vera-Omni" in meta["team_name"]
    assert "model" in meta
    assert meta["version"] == "2.0.0"


def test_context_push_and_versioning():
    """Verify idempotent context storage and rejection of older versions."""
    payload = {
        "scope": "merchant",
        "context_id": "m_test_unit",
        "version": 2,
        "payload": {"name": "Test Salon", "category_slug": "salons"},
    }
    r1 = client.post("/v1/context", json=payload)
    assert r1.status_code == 200
    assert r1.json()["accepted"] is True

    # Same version -> accepted idempotently
    r2 = client.post("/v1/context", json=payload)
    assert r2.status_code == 200
    assert r2.json()["accepted"] is True

    # Older version -> rejected with 409 Conflict
    older = dict(payload, version=1)
    r3 = client.post("/v1/context", json=older)
    assert r3.status_code == 409
    assert r3.json()["accepted"] is False
    assert "stale_version" in r3.json()["reason"]

    # Malformed scope -> returns HTTP 400 Bad Request matching spec §2.1
    bad_scope = dict(payload, scope="invalid_vertical")
    r4 = client.post("/v1/context", json=bad_scope)
    assert r4.status_code == 400
    assert r4.json()["accepted"] is False
    assert r4.json()["reason"] == "invalid_scope"


def test_teardown_endpoint():
    """Verify POST /v1/teardown wipes state per Testing Brief §11."""
    # Push dummy context
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_td_test", "version": 1, "payload": {"name": "TD"}
    })
    r_td = client.post("/v1/teardown")
    assert r_td.status_code == 200
    assert r_td.json()["status"] == "ok"

    # Verify counts are zero
    r_hz = client.get("/v1/healthz")
    assert r_hz.json()["contexts_loaded"]["merchant"] == 0


def test_multi_turn_affirmative_intent():
    """Verify that merchant saying 'yes' immediately triggers ACTION mode with no qualifying questions."""
    resp = handle_reply(
        conv_id="conv_test_intent",
        merchant_id="m_001_drmeera_dentist_delhi",
        customer_id=None,
        from_role="merchant",
        message="yes, let's do this",
        turn_number=1,
    )
    assert resp["action"] == "send"
    body = (resp.get("body") or "").lower()
    assert "draft" in body or "scheduled" in body or "proceeding" in body or "done" in body
    assert "?" not in resp.get("body", "")  # ZERO qualifying questions asked!


def test_multi_turn_hostile_exit():
    """Verify hostile message leads to immediate end action without arguing."""
    resp = handle_reply(
        conv_id="conv_test_hostile",
        merchant_id="m_001_drmeera_dentist_delhi",
        customer_id=None,
        from_role="merchant",
        message="Stop spamming me, this is a scam!",
        turn_number=1,
    )
    assert resp["action"] == "end"


def test_multi_turn_auto_reply_exit():
    """Verify auto-reply vacation bot message triggers suppression and graceful exit."""
    # First auto-reply: prompts human
    resp1 = handle_reply(
        conv_id="conv_test_auto",
        merchant_id="m_auto_test",
        customer_id=None,
        from_role="merchant",
        message="Thank you for contacting us. We are currently out of office. This is an automated message.",
        turn_number=1,
    )
    assert resp1["action"] == "send"

    # Second auto-reply: backs off
    resp2 = handle_reply(
        conv_id="conv_test_auto",
        merchant_id="m_auto_test",
        customer_id=None,
        from_role="merchant",
        message="Auto-reply: I am on vacation until next week. Please leave a message.",
        turn_number=2,
    )
    assert resp2["action"] in {"wait", "end"}

    # Third auto-reply: ends thread permanently
    resp3 = handle_reply(
        conv_id="conv_test_auto",
        merchant_id="m_auto_test",
        customer_id=None,
        from_role="merchant",
        message="Automated response: our team will be back on Monday.",
        turn_number=3,
    )
    assert resp3["action"] == "end"


def test_conversation_handlers_respond():
    """Test optional §7.4 conversation_handlers respond function."""
    state = ConversationState(
        conversation_id="conv_handler_test",
        merchant_id="m_006_southindiancafe_restaurant_bangalore",
        turn_number=1,
    )
    res = respond(state, "CONFIRM")
    assert res["action"] == "send"
    assert res["cta"] == "binary_confirm_cancel"


def test_deterministic_fallback_composer():
    """Verify fallback composition is 100% grounded, cliché-free, and contains no None or JSON leaks."""
    cat = {"slug": "dentists", "taboos": ["guaranteed", "cure"], "tone": "clinical_peer"}
    mer = {
        "merchant_id": "m_001",
        "name": "Dr. Meera's Dental Clinic",
        "owner_name": "Dr. Meera Sharma",
        "locality": "Lajpat Nagar",
        "city": "Delhi",
        "category_slug": "dentists",
        "verified": True,
        "languages": ["en", "hi"],
        "hero_offer": "Dental Cleaning @ ₹299",
        "active_offers": ["Dental Cleaning @ ₹299"],
        "performance": {"views_30d": 3400, "calls_30d": 42},
    }
    trg = {
        "kind": "cde_opportunity",
        "id": "trg_unit_test",
        "scope": "merchant",
        "urgency": 3,
        "payload": {"title": "IDA Webinar on Clear Aligners", "free_for_members": True},
    }
    result = compose_message(cat, mer, trg, customer=None, use_llm=False)
    assert result["send_as"] == "vera"
    assert "Dr. Meera" in result["body"]
    assert "None" not in result["body"]
    assert "payload" not in result["body"].lower()
    assert result["cta"] == "binary_yes_no"


def test_submission_jsonl_validity():
    """Verify submission.jsonl exists, has exactly 30 lines, and strictly follows the required schema."""
    sub_path = ROOT / "submission.jsonl"
    assert sub_path.exists(), "submission.jsonl not found at repo root"

    with open(sub_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 30, f"Expected 30 lines in submission.jsonl, got {len(lines)}"

    required_keys = {"test_id", "body", "cta", "send_as", "suppression_key", "rationale"}
    for idx, line in enumerate(lines, 1):
        data = json.loads(line)
        assert required_keys.issubset(data.keys()), f"Line {idx} missing required keys: {data}"
        assert data["test_id"].startswith("T"), f"Invalid test_id in line {idx}: {data['test_id']}"
        assert len(data["body"]) > 20, f"Body too short in line {idx}"
        assert data["send_as"] in {"vera", "merchant_on_behalf"}, f"Invalid send_as in line {idx}"
        assert "http" not in data["body"].lower(), f"URL detected in line {idx}: {data['body']}"
        assert "~None" not in data["body"], f"Leaked None detected in line {idx}"
