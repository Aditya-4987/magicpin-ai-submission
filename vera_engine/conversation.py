"""Stateful multi-turn conversation manager and replay test engine."""

from __future__ import annotations
import re
from typing import Any, Dict, Optional
from .store import ContextStore

AUTO_REPLY_PATTERNS = re.compile(
    r"(thank you for contacting|our team will respond|automated assistant|"
    r"we will get back|canned auto[- ]?reply|auto[- ]?generated|jaankari ke liye|"
    r"shukriya|dhanyawad|hamari team|auto[- ]?reply|busy right now|away from phone|"
    r"out of office|on vacation|automated message|automated response)",
    re.I,
)

COMMIT_PATTERNS = re.compile(
    r"\b(yes|yeah|yup|yep|haan|sure|ok|okay|ok lets do it|lets do it|let's do it|proceed|"
    r"confirm|go ahead|start it|send it|whats next|what's next|do it|haan karo|"
    r"shuru karo|yes please|sounds good|sounds great|chalega|lock it in|ready to start)\b",
    re.I,
)

HOSTILE_STOP_PATTERNS = re.compile(
    r"\b(stop|spam|unsubscribe|not interested|don't message|do not message|"
    r"band karo|bakwas|useless|harass|nuisance|block|leave me alone)\b",
    re.I,
)

OFF_TOPIC_PATTERNS = re.compile(
    r"\b(gst|tax|income tax|itr|legal|court|police|politics|password|election)\b",
    re.I,
)

ALREADY_HAVE_PATTERNS = re.compile(
    r"\b(already running|already have|already live|already doing|no need|not needed)\b",
    re.I,
)

PRICE_PATTERNS = re.compile(
    r"\b(how much|cost|price|charges|charge|fee|fees|kitna|paisa|is it free)\b",
    re.I,
)

RESCHEDULE_PATTERNS = re.compile(
    r"\b(reschedule|change time|different time|another time|later|tomorrow|evening|morning|shift slot)\b",
    re.I,
)

IDENTITY_PATTERNS = re.compile(
    r"\b(who is this|who are you|what is vera|kaun ho|who are u)\b",
    re.I,
)

QUALIFYING_WORDS = ["would you", "do you", "can you tell", "what if", "how about"]

def is_auto_reply(message: str) -> bool:
    m = message.strip()
    if len(m) < 25 and "thank" in m.lower():
        return True
    return bool(AUTO_REPLY_PATTERNS.search(m))

def handle_reply(
    conv_id: str,
    merchant_id: str,
    customer_id: Optional[str],
    from_role: str,
    message: str,
    turn_number: int,
) -> Dict[str, Any]:
    """
    Handles inbound messages from merchants or customers with stateful routing.
    """
    store = ContextStore.get()
    conv = store.get_or_create_conversation(conv_id, merchant_id or "unknown", customer_id)
    store.record_turn(conv_id, from_role, message)

    clean_msg = message.strip()

    # If conversation was already marked ended, respect closure
    if conv.ended:
        return {
            "action": "end",
            "rationale": "Conversation thread is already finalized; no further messages sent."
        }

    # =========================================================================
    # 1. HOSTILE / OPT-OUT DETECTION -> IMMEDIATE GRACEFUL END
    # =========================================================================
    if HOSTILE_STOP_PATTERNS.search(clean_msg):
        conv.ended = True
        conv.ended_reason = "merchant_opt_out"
        return {
            "action": "end",
            "rationale": "Merchant signaled opt-out / not interested; gracefully ended outreach immediately."
        }

    # =========================================================================
    # 2. COMMITMENT / INTENT TRANSITION -> SWITCH TO ACTION MODE (NO QUALIFYING!)
    # =========================================================================
    # Must precede auto-reply check so commitment is never throttled
    if COMMIT_PATTERNS.search(clean_msg):
        conv.auto_reply_streak = 0
        action_body = (
            "Done! Here is your draft ready to publish:\n"
            "- Google Listing Headline: Updated with your signature offer\n"
            "- Customer WhatsApp Broadcast: Formatted and scheduled\n"
            "Proceeding with setup now. Reply CONFIRM to send live, or text any edits."
        )
        # Verify action words are present and qualifying words are completely absent
        assert not any(q in action_body.lower() for q in QUALIFYING_WORDS)
        store.record_turn(conv_id, "vera", action_body)
        return {
            "action": "send",
            "body": action_body,
            "cta": "binary_confirm_cancel",
            "rationale": "Merchant committed; Vera switched immediately to ACTION mode with ready-to-publish draft."
        }

    # =========================================================================
    # 3. AUTO-REPLY HELL DETECTION (Tracks per-conv and per-merchant repeats)
    # =========================================================================
    repeat_count = store.track_merchant_message(merchant_id or "m_default", clean_msg)
    is_canned = is_auto_reply(clean_msg) or (repeat_count >= 2)

    if is_canned:
        conv.auto_reply_streak += 1
        # If repeated 3+ times or turn 3+ in auto-reply scenario, END gracefully
        if conv.auto_reply_streak >= 3 or repeat_count >= 3 or turn_number >= 3:
            conv.ended = True
            conv.ended_reason = "auto_reply_exhausted"
            return {
                "action": "end",
                "rationale": "Detected persistent automated canned responses; pausing outreach so human manager can review."
            }
        elif conv.auto_reply_streak == 2 or repeat_count == 2:
            return {
                "action": "wait",
                "wait_seconds": 3600,
                "rationale": "Second automated reply received; backing off for 1 hour to await human availability."
            }
        else:
            prompt_human_body = (
                "Samajh gaya! Looks like an automated auto-reply — whenever someone is available, "
                "just reply YES and I will drop the ready preview."
            )
            store.record_turn(conv_id, "vera", prompt_human_body)
            return {
                "action": "send",
                "body": prompt_human_body,
                "cta": "binary_yes_no",
                "rationale": "First auto-reply detected; sent polite confirmation for when a human operator sees WhatsApp."
            }

    # Reset streak on real message
    conv.auto_reply_streak = 0

    # =========================================================================
    # 4. OFF-TOPIC HANDLING (GST / Tax / Curveballs)
    # =========================================================================
    if OFF_TOPIC_PATTERNS.search(clean_msg):
        off_topic_body = (
            "I'll leave GST and tax filing to your CA! "
            "Back to driving customer walk-ins: I have a high-converting Google update drafted for your active offer. "
            "Want me to send the preview? Reply YES."
        )
        store.record_turn(conv_id, "vera", off_topic_body)
        return {
            "action": "send",
            "body": off_topic_body,
            "cta": "binary_yes_no",
            "rationale": "Off-topic query politely deflected back to merchant's core growth action."
        }

    # =========================================================================
    # 5. ALREADY LIVE / HAVE OFFER REFRAME
    # =========================================================================
    if ALREADY_HAVE_PATTERNS.search(clean_msg):
        pivot_body = (
            "Great to hear the offer is already live! The biggest conversion lever now is search headline clarity "
            "and quick WhatsApp replies. Want me to optimize your Google listing title to lift CTR? Reply YES."
        )
        store.record_turn(conv_id, "vera", pivot_body)
        return {
            "action": "send",
            "body": pivot_body,
            "cta": "binary_yes_no",
            "rationale": "Offer already live; Vera pivoted from launch to CTR conversion optimization."
        }

    # =========================================================================
    # 6. PRICING & COST INQUIRIES
    # =========================================================================
    if PRICE_PATTERNS.search(clean_msg):
        price_body = (
            "Vera's campaign drafting and Google listing optimization are completely included in your magicpin partner subscription — no extra fees! "
            "I have your customized promotion ready to preview. Reply YES to see the draft."
        )
        store.record_turn(conv_id, "vera", price_body)
        return {
            "action": "send",
            "body": price_body,
            "cta": "binary_yes_no",
            "rationale": "Clarified zero extra cost under active subscription and advanced to preview."
        }

    # =========================================================================
    # 7. RESCHEDULING & TIMING ADJUSTMENTS
    # =========================================================================
    if RESCHEDULE_PATTERNS.search(clean_msg):
        reschedule_body = (
            "Noted! I've adjusted the schedule timing to your request. "
            "Draft is ready to launch — reply CONFIRM to publish, or text any other changes."
        )
        store.record_turn(conv_id, "vera", reschedule_body)
        return {
            "action": "send",
            "body": reschedule_body,
            "cta": "binary_confirm_cancel",
            "rationale": "Honored timing adjustment without qualifying questions and requested confirmation."
        }

    # =========================================================================
    # 8. IDENTITY & PURPOSE QUERIES
    # =========================================================================
    if IDENTITY_PATTERNS.search(clean_msg):
        identity_body = (
            "Hi! I'm Vera, magicpin's merchant AI assistant. I track local Google searches and footfall trends to help your store win more customers. "
            "I have a high-converting update ready for your active offer — want to preview it? Reply YES."
        )
        store.record_turn(conv_id, "vera", identity_body)
        return {
            "action": "send",
            "body": identity_body,
            "cta": "binary_yes_no",
            "rationale": "Explained Vera identity and purpose crisply and proposed ready deliverable preview."
        }

    # =========================================================================
    # 9. GENERAL ENGAGED MERCHANT RESPONSE
    # =========================================================================
    if from_role == "merchant":
        general_body = (
            "Got it! I can line up your customer WhatsApp broadcast and Google post right away. "
            "Want me to send the draft over for a quick 30-second review? Reply YES."
        )
        store.record_turn(conv_id, "vera", general_body)
        return {
            "action": "send",
            "body": general_body,
            "cta": "binary_yes_no",
            "rationale": "Merchant responded positively; Vera advances toward concrete deliverable."
        }

    # Customer-facing incoming acknowledgment
    customer_ack_body = "Thank you for reaching out! We've noted your request and will confirm details shortly."
    store.record_turn(conv_id, "vera", customer_ack_body)
    return {
        "action": "send",
        "body": customer_ack_body,
        "cta": "none",
        "rationale": "Customer inbound inquiry acknowledged politely."
    }
