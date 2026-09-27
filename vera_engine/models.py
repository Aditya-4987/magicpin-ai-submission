"""Data models and schemas for Vera-Omni engine."""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class ContextPushRequest(BaseModel):
    scope: Literal["category", "merchant", "customer", "trigger"]
    context_id: str
    version: int = Field(ge=1)
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None

class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None

class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)

class ActionItem(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: List[str] = Field(default_factory=list)
    body: str
    cta: str
    suppression_key: str
    rationale: str

class TickResponse(BaseModel):
    actions: List[ActionItem]

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: Optional[str] = None
    turn_number: int = 1

class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: int
    contexts_loaded: Dict[str, int]

class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str

class ComposedMessage(BaseModel):
    body: str
    cta: str = "open_ended"
    send_as: Literal["vera", "merchant_on_behalf"] = "vera"
    suppression_key: str
    rationale: str
    template_name: str = "vera_composer_v2"
    template_params: List[str] = Field(default_factory=list)
