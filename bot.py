"""Vera-Omni: magicpin Merchant AI Assistant — Production FastAPI Service."""

from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Response, status, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from vera_engine.config import (
    TEAM_NAME,
    TEAM_MEMBERS,
    GROQ_PRIMARY_MODEL,
    APPROACH,
    CONTACT_EMAIL,
    VERSION,
)
from vera_engine.composer import compose_message, compose
from vera_engine.conversation import handle_reply
from vera_engine.models import (
    ContextPushRequest,
    TickRequest,
    ReplyRequest,
)
from vera_engine.store import ContextStore

app = FastAPI(title="Vera-Omni Merchant Engine", version=VERSION)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    reason = "malformed_request"
    for err in errors:
        loc = str(err.get("loc", []))
        if "scope" in loc:
            reason = "invalid_scope"
            break
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "accepted": False,
            "reason": reason,
            "details": str(errors),
        },
    )

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _is_expired(expires_at: Optional[str], now_str: Optional[str]) -> bool:
    if not expires_at or not now_str:
        return False
    try:
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now_dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
        return exp_dt < now_dt
    except Exception:
        return False

# =============================================================================
# 1. GET /v1/healthz & /healthz
# =============================================================================
@app.get("/v1/healthz")
@app.get("/healthz")
@app.get("/health")
async def healthz():
    store = ContextStore.get()
    return {
        "status": "ok",
        "uptime_seconds": store.uptime_seconds(),
        "contexts_loaded": store.count_by_scope(),
    }

# =============================================================================
# 2. GET /v1/metadata & /metadata
# =============================================================================
@app.get("/v1/metadata")
@app.get("/metadata")
async def metadata():
    return {
        "team_name": TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "model": GROQ_PRIMARY_MODEL,
        "approach": APPROACH,
        "contact_email": CONTACT_EMAIL,
        "version": VERSION,
        "submitted_at": _iso_now(),
    }

# =============================================================================
# 3. POST /v1/context
# =============================================================================
@app.post("/v1/context")
async def push_context(body: ContextPushRequest, response: Response):
    store = ContextStore.get()
    accepted, reason, cur_version = store.push_context(
        body.scope, body.context_id, body.version, body.payload
    )
    if not accepted:
        response.status_code = status.HTTP_409_CONFLICT
        return {
            "accepted": False,
            "reason": reason or "stale_version",
            "current_version": cur_version,
        }
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": _iso_now(),
    }

# =============================================================================
# 4. POST /v1/tick
# =============================================================================
@app.post("/v1/tick")
async def tick(body: TickRequest):
    store = ContextStore.get()
    actions: List[Dict[str, Any]] = []
    deadline = time.monotonic() + 18.0  # Guaranteed return under 20s, well inside 30s client timeout

    # Rank available triggers by urgency
    ranked_triggers = []
    for tid in body.available_triggers or []:
        trg = store.get_payload("trigger", tid)
        if not trg:
            continue
        urgency = int(trg.get("urgency", 3))
        ranked_triggers.append((urgency, tid, trg))

    ranked_triggers.sort(key=lambda x: -x[0])

    for urgency, tid, trg in ranked_triggers:
        if time.monotonic() > deadline or len(actions) >= 20:
            break

        sk = trg.get("suppression_key") or ""
        if sk and store.is_suppressed(sk):
            continue

        payload = trg.get("payload") or {}
        mid = trg.get("merchant_id") or payload.get("merchant_id")
        if not mid:
            continue

        merchant = store.get_payload("merchant", mid)
        if not merchant:
            continue

        category_slug = merchant.get("category_slug") or ""
        category = store.get_payload("category", category_slug)
        if not category:
            continue

        cid = trg.get("customer_id") or payload.get("customer_id")
        customer = store.get_payload("customer", cid) if cid else None

        conv_id = f"conv_{mid}_{tid}"

        time_left = deadline - time.monotonic()
        use_llm = time_left > 3.0

        try:
            composed = compose_message(
                category=category,
                merchant=merchant,
                trigger=trg,
                customer=customer,
                use_llm=use_llm,
                now_iso=body.now,
            )
        except Exception:
            continue

        if sk:
            store.suppress(sk)

        # Initialize conversation state with the initial outbound message
        conv_state = store.get_or_create_conversation(conv_id, mid, cid)
        conv_state.trigger_kind = trg.get("kind")
        conv_state.last_bot_body = composed.get("body", "")
        store.record_turn(conv_id, "vera", composed.get("body", ""))

        # Ensure template params are populated with concrete values
        template_params = composed.get("template_params") or []
        if not template_params:
            m_ident = merchant.get("identity") or {}
            owner = m_ident.get("owner_first_name") or m_ident.get("name") or "there"
            hero = m_ident.get("hero_offer") or "special offer"
            template_params = [str(owner), str(hero), composed.get("cta", "binary_yes_no")]

        actions.append({
            "conversation_id": conv_id,
            "merchant_id": mid,
            "customer_id": cid,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": tid,
            "template_name": composed.get("template_name", f"vera_{trg.get('kind', 'generic')}_v2"),
            "template_params": template_params,
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "binary_yes_no"),
            "suppression_key": composed.get("suppression_key") or sk,
            "rationale": composed.get("rationale", ""),
        })

    return {"actions": actions}

# =============================================================================
# 5. POST /v1/reply
# =============================================================================
@app.post("/v1/reply")
async def reply(body: ReplyRequest):
    return handle_reply(
        conv_id=body.conversation_id,
        merchant_id=body.merchant_id or "",
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        turn_number=body.turn_number,
    )

# =============================================================================
# 6. POST /v1/teardown & /teardown (Testing Brief §11 Compliance)
# =============================================================================
@app.post("/v1/teardown")
@app.post("/teardown")
async def teardown():
    store = ContextStore.get()
    store.wipe_all()
    return {"status": "ok", "message": "all state wiped"}

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
