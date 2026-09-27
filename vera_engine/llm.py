"""Multi-tier LLM Client with ultra-fast Groq and Gemini Flash providers."""

from __future__ import annotations
import json
import logging
import re
import time
from urllib import request as urlrequest, error as urlerror
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    GROQ_API_KEY,
    GROQ_PRIMARY_MODEL,
    GROQ_FALLBACK_MODEL,
    GROQ_FAST_MODEL,
    GEMINI_API_KEY,
    GEMINI_PRIMARY_MODEL,
    HTTP_USER_AGENT,
    LLM_TIMEOUT,
    LLM_TEMPERATURE,
    LLM_SEED,
)

logger = logging.getLogger("vera.llm")

class LLMClient:
    _instance: Optional[LLMClient] = None

    @classmethod
    def get(cls) -> LLMClient:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.groq_key = GROQ_API_KEY
        self.gemini_key = GEMINI_API_KEY

    def _call_groq(self, prompt: str, system: Optional[str], model: str, json_mode: bool = True) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        user_content = prompt if "json" in prompt.lower() else f"{prompt}\nReturn JSON format."
        messages.append({"role": "user", "content": user_content})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "seed": LLM_SEED,
            "max_tokens": 1200,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
            "User-Agent": HTTP_USER_AGENT,
        }
        req = urlrequest.Request("https://api.groq.com/openai/v1/chat/completions", data=body, headers=headers)
        
        for attempt in range(2):
            try:
                with urlrequest.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["choices"][0]["message"]["content"]
            except urlerror.HTTPError as e:
                if e.code == 429 and attempt < 1:
                    time.sleep(0.5)
                    continue
                raise

    def _call_gemini(self, prompt: str, system: Optional[str], model: str) -> str:
        full_text = f"{system}\n\n{prompt}" if system else prompt
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}"
        payload = {
            "contents": [{"parts": [{"text": full_text}]}],
            "generationConfig": {
                "temperature": LLM_TEMPERATURE,
                "maxOutputTokens": 1200,
                "responseMimeType": "application/json",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": HTTP_USER_AGENT,
        }
        req = urlrequest.Request(url, data=body, headers=headers)
        with urlrequest.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def complete_json(self, prompt: str, system: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Executes multi-tier LLM generation and returns parsed JSON.
        Returns: (parsed_dict, provider_model_used)
        """
        # Tier 1: Groq with Primary Model (openai/gpt-oss-120b - fastest 120B in 0.6s)
        if self.groq_key:
            for model_name in [GROQ_PRIMARY_MODEL, GROQ_FALLBACK_MODEL, GROQ_FAST_MODEL]:
                try:
                    t0 = time.time()
                    raw = self._call_groq(prompt, system, model_name, json_mode=True)
                    parsed = self._extract_json(raw)
                    if parsed:
                        latency = (time.time() - t0) * 1000
                        return parsed, f"groq:{model_name}:{latency:.0f}ms"
                except urlerror.HTTPError as e:
                    if e.code == 429:
                        logger.warning("Groq rate limit 429 reached. Switching immediately to Gemini Tier.")
                        break
                    logger.warning(f"Groq {model_name} HTTP {e.code}: {e}")
                except Exception as e:
                    logger.warning(f"Groq {model_name} failed: {e}")
                    continue

        # Tier 2: Google AI Studio Gemini (gemini-flash-lite-latest in ~1.9s)
        if self.gemini_key:
            try:
                t0 = time.time()
                raw = self._call_gemini(prompt, system, GEMINI_PRIMARY_MODEL)
                parsed = self._extract_json(raw)
                if parsed:
                    latency = (time.time() - t0) * 1000
                    return parsed, f"gemini:{GEMINI_PRIMARY_MODEL}:{latency:.0f}ms"
            except Exception as e:
                logger.warning(f"Gemini {GEMINI_PRIMARY_MODEL} failed: {e}")

        return None, "fallback:none"

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        # Direct parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # Markdown block extraction ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        # Regex scan for first balanced JSON object
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass

        return None
