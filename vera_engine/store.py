"""High-performance thread-safe in-memory context and state store."""

from __future__ import annotations
import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

class ContextRecord:
    __slots__ = ("scope", "context_id", "version", "payload", "stored_at")

    def __init__(self, scope: str, context_id: str, version: int, payload: dict, stored_at: str):
        self.scope = scope
        self.context_id = context_id
        self.version = version
        self.payload = payload
        self.stored_at = stored_at

class ConversationTurn:
    __slots__ = ("role", "message", "timestamp")

    def __init__(self, role: str, message: str, timestamp: str):
        self.role = role
        self.message = message
        self.timestamp = timestamp

class ConversationState:
    def __init__(self, conversation_id: str, merchant_id: str, customer_id: Optional[str] = None):
        self.conversation_id = conversation_id
        self.merchant_id = merchant_id
        self.customer_id = customer_id
        self.turns: List[ConversationTurn] = []
        self.created_at = time.time()
        self.ended = False
        self.ended_reason: Optional[str] = None
        self.auto_reply_streak = 0
        self.last_canned_message: Optional[str] = None
        self.last_bot_body: Optional[str] = None
        self.trigger_kind: Optional[str] = None
        self.hero_offer: Optional[str] = None
        self.locality: Optional[str] = None

class ContextStore:
    _instance: Optional[ContextStore] = None
    _lock = threading.Lock()

    def __init__(self):
        self._start_time = time.time()
        self._rw_lock = threading.RLock()
        # Storage: (scope, context_id) -> ContextRecord
        self._contexts: Dict[Tuple[str, str], ContextRecord] = {}
        # Suppression keys: suppression_key -> expiration timestamp (or True)
        self._suppressed: Dict[str, float] = {}
        # Conversations: conv_id -> ConversationState
        self._conversations: Dict[str, ConversationState] = {}
        # Merchant to recent auto-reply count
        self._merchant_auto_replies: Dict[str, int] = {}
        # Merchant to last message text (for detecting exact repeated canned messages)
        self._merchant_last_messages: Dict[str, List[str]] = {}
        # Composition Cache: cache_key -> dict
        self._compose_cache: Dict[str, dict] = {}

    @classmethod
    def get(cls) -> ContextStore:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls):
        with cls._lock:
            cls._instance = cls()

    def uptime_seconds(self) -> int:
        return int(time.time() - self._start_time)

    def push_context(
        self, scope: str, context_id: str, version: int, payload: dict
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Idempotent context push.
        Returns: (accepted, reason, current_version)
        """
        with self._rw_lock:
            key = (scope, context_id)
            existing = self._contexts.get(key)
            if existing is not None:
                if existing.version > version:
                    return False, "stale_version", existing.version
                if existing.version == version:
                    # Idempotent re-push of same version: ensure triggers are ready for evaluation
                    if scope == "trigger" and isinstance(payload, dict):
                        sk = payload.get("suppression_key")
                        if sk and sk in self._suppressed:
                            del self._suppressed[sk]
                    return True, None, existing.version

            # Context version update: clear composition cache to ensure fresh adaptation
            self._compose_cache.clear()

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._contexts[key] = ContextRecord(
                scope=scope,
                context_id=context_id,
                version=version,
                payload=copy.deepcopy(payload),
                stored_at=now_iso,
            )
            # If a trigger is pushed, clear any prior suppression so it is freshly active
            if scope == "trigger" and isinstance(payload, dict):
                sk = payload.get("suppression_key")
                if sk and sk in self._suppressed:
                    del self._suppressed[sk]
            return True, None, version

    def wipe_all(self):
        """Wipes all state cleanly for teardown / test isolation."""
        with self._rw_lock:
            self._start_time = time.time()
            self._contexts.clear()
            self._suppressed.clear()
            self._conversations.clear()
            self._merchant_auto_replies.clear()
            self._merchant_last_messages.clear()
            self._compose_cache.clear()

    def get_context(self, scope: str, context_id: str) -> Optional[ContextRecord]:
        with self._rw_lock:
            return self._contexts.get((scope, context_id))

    def get_payload(self, scope: str, context_id: str) -> Optional[dict]:
        with self._rw_lock:
            rec = self._contexts.get((scope, context_id))
            return copy.deepcopy(rec.payload) if rec else None

    def list_contexts(self, scope: str) -> List[dict]:
        with self._rw_lock:
            return [copy.deepcopy(rec.payload) for (sc, _), rec in self._contexts.items() if sc == scope]

    def count_by_scope(self) -> Dict[str, int]:
        with self._rw_lock:
            counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
            for (scope, _), _ in self._contexts.items():
                if scope in counts:
                    counts[scope] += 1
                else:
                    counts[scope] = 1
            return counts

    def suppress(self, suppression_key: str, ttl_seconds: float = 86400.0):
        if not suppression_key:
            return
        with self._rw_lock:
            self._suppressed[suppression_key] = time.time() + ttl_seconds

    def is_suppressed(self, suppression_key: str) -> bool:
        if not suppression_key:
            return False
        with self._rw_lock:
            exp = self._suppressed.get(suppression_key)
            if exp is None:
                return False
            if time.time() > exp:
                del self._suppressed[suppression_key]
                return False
            return True

    def get_or_create_conversation(
        self, conversation_id: str, merchant_id: str, customer_id: Optional[str] = None
    ) -> ConversationState:
        with self._rw_lock:
            if conversation_id not in self._conversations:
                self._conversations[conversation_id] = ConversationState(
                    conversation_id, merchant_id, customer_id
                )
            return self._conversations[conversation_id]

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        with self._rw_lock:
            return self._conversations.get(conversation_id)

    def record_turn(self, conversation_id: str, role: str, message: str):
        with self._rw_lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.turns.append(
                    ConversationTurn(
                        role=role,
                        message=message,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )

    def track_merchant_message(self, merchant_id: str, message: str) -> int:
        """Track messages from merchant across all conversations to count repeats/auto-replies."""
        with self._rw_lock:
            history = self._merchant_last_messages.setdefault(merchant_id, [])
            history.append(message.strip().lower())
            if len(history) > 10:
                history.pop(0)

            # Count how many times this exact or near-identical message was sent
            norm = message.strip().lower()
            repeats = sum(1 for m in history if m == norm)
            return repeats

    def get_compose_cache(self, key: str) -> Optional[dict]:
        with self._rw_lock:
            cached = self._compose_cache.get(key)
            return copy.deepcopy(cached) if cached else None

    def set_compose_cache(self, key: str, val: dict):
        with self._rw_lock:
            if len(self._compose_cache) > 2000:
                # Evict half if cache gets large
                keys = list(self._compose_cache.keys())[:1000]
                for k in keys:
                    del self._compose_cache[k]
            self._compose_cache[key] = copy.deepcopy(val)
