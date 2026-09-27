"""
Vera-Omni: Optional Conversation Handlers
Implements Challenge Brief §7.4 multi-turn conversation handler tiebreaker.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from vera_engine.conversation import handle_reply


class ConversationState(BaseModel):
    """Conversation state representation matching Challenge Brief §7.4."""
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    turn_number: int = 1
    turns: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def respond(state: ConversationState | Dict[str, Any], merchant_message: str) -> Dict[str, Any]:
    """
    Given the conversation so far + the merchant's latest message, produce the reply.
    Implements Challenge Brief §7.4:
    - Recognizes merchant affirmations ('yes', 'sure', 'confirm') and switches to ACTION mode.
    - Gracefully exits on hostile / stop messages ('fraud', 'scam', 'stop').
    - Detects automated vacation/out-of-office loops and suppresses infinite chatter.
    - Deflects off-topic queries (e.g. California taxes) back to local store operations.
    """
    if isinstance(state, dict):
        conv_id = state.get("conversation_id", "conv_default")
        mer_id = state.get("merchant_id")
        cus_id = state.get("customer_id")
        turn_num = state.get("turn_number", 1)
    else:
        conv_id = state.conversation_id
        mer_id = state.merchant_id
        cus_id = state.customer_id
        turn_num = state.turn_number

    resp = handle_reply(
        conv_id=conv_id,
        merchant_id=mer_id or "unknown",
        customer_id=cus_id,
        from_role="merchant",
        message=merchant_message,
        turn_number=turn_num,
    )

    return resp
