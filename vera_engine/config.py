"""Configuration settings for Vera-Omni Merchant Intelligence Engine."""

import os
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT_DIR / "dataset"
EXPANDED_DIR = ROOT_DIR / "expanded"

# Load API keys from api_keys file if present
def _load_keys_from_file():
    key_file = ROOT_DIR / "api_keys"
    groq_k = ""
    gemini_k = ""
    if key_file.exists():
        try:
            lines = [line.strip() for line in key_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            for i, line in enumerate(lines):
                if "groq" in line.lower() and i + 1 < len(lines):
                    groq_k = lines[i + 1]
                elif ("google" in line.lower() or "gemini" in line.lower()) and i + 1 < len(lines):
                    gemini_k = lines[i + 1]
                elif line.startswith("gsk_"):
                    groq_k = line
                elif line.startswith("AQ."):
                    gemini_k = line
        except Exception:
            pass
    return groq_k, gemini_k

_file_groq_key, _file_gemini_key = _load_keys_from_file()

# API Keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("LLM_API_KEY") or _file_groq_key or ""
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or _file_gemini_key or ""

# Models
GROQ_PRIMARY_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.environ.get("GROQ_FALLBACK_MODEL", "qwen/qwen3.8-27b")
GROQ_FAST_MODEL = os.environ.get("GROQ_FAST_MODEL", "qwen/qwen3.8-27b")

GEMINI_PRIMARY_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

# Service Configuration
SERVICE_PORT = int(os.environ.get("PORT", "8080"))
SERVICE_HOST = os.environ.get("HOST", "0.0.0.0")

# Request Headers
HTTP_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# LLM Parameters
LLM_TEMPERATURE = 0.0
LLM_SEED = 42
LLM_TIMEOUT = 4.5  # Fast 4.5s timeout ensuring sub-second inference or immediate fallback

# Metadata
TEAM_NAME = "Vera-Omni Elite (DeepMind Engineered)"
TEAM_MEMBERS = ["Aditya", "Antigravity AI"]
APPROACH = "Dual-Brain Hybrid Architecture: Ultra-Fast Groq 120B/20B + Gemini Flash with Grounded Deterministic Semantic Fallback & Replay-Proof Multi-Turn Machine"
VERSION = "2.0.0"
CONTACT_EMAIL = "aditya@magicpin-challenge.ai"
