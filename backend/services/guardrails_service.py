"""Responsible AI Guardrails Service.

Layered safety screening for agent interactions:
  - Layer 1: Fast regex blocklist (violence, self-harm, malware, PII)
  - Layer 2: NVIDIA NIM Llama Guard classification for ambiguous inputs

Handles Llama Guard unavailability gracefully (falls back to blocklist-only).
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# ─── Blocked patterns (regex) ───────────────────────────────────────
# Categories: violence, self-harm, malware/hacking, PII (credit card, SSN)
BLOCKED_PATTERNS = [
    # Violence / threats
    r"(?i)\b(kill|murder|assassinate|bomb|shoot|stab|attack)\s+(someone|people|him|her|them|a person)",
    r"(?i)\b(how to|ways to)\s+(kill|murder|poison|harm)\b",
    # Self-harm
    r"(?i)\b(suicide|self-harm|cut myself|end my life|kill myself)\b",
    r"(?i)\b(how to|ways to)\s+(hurt yourself|commit suicide|self-harm)\b",
    # Malware / hacking
    r"(?i)\b(write|create|generate|make)\s+(a\s+)?(virus|malware|ransomware|trojan|keylogger|phishing)\b",
    r"(?i)\b(exploit|hack into|bypass security|sql injection|xss attack)\b",
    # PII patterns — credit card numbers (13-19 digits)
    r"\b(?:\d[ -]*?){13,19}\b",
    # PII patterns — SSN (XXX-XX-XXXX)
    r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
]

# Soft-concern words: when present in long messages, escalate to Llama Guard
_SOFT_CONCERNS = [
    "weapon", "drug", "illegal", "hate", "racist", "sexist",
    "abuse", "threat", "harass", "steal", "fraud", "scam",
    "dangerous", "toxic", "extremist", "radical",
]


# ─── Public API ─────────────────────────────────────────────────────

def screen_input(message: str) -> dict:
    """Screen user input before agent processing.

    Returns: {"safe": bool, "reason": str}
    """
    # Layer 1: Fast blocklist check
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, message):
            return {"safe": False, "reason": "blocked_content"}

    # Layer 2: Llama Guard for ambiguous messages
    if _is_ambiguous(message):
        try:
            result = _classify_with_llama_guard(message)
            return result
        except Exception as e:
            logger.warning(f"Llama Guard unavailable, falling back to blocklist-only: {e}")
            return {"safe": True, "reason": "llama_guard_unavailable"}

    return {"safe": True, "reason": "passed"}


def screen_output(response: str) -> dict:
    """Screen agent output before delivering to user.

    Returns: {"safe": bool, "reason": str}
    """
    # Layer 1: Fast blocklist check
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, response):
            return {"safe": False, "reason": "blocked_content"}

    # Layer 2: Llama Guard for ambiguous responses
    if _is_ambiguous(response):
        try:
            result = _classify_with_llama_guard(response)
            return result
        except Exception as e:
            logger.warning(f"Llama Guard unavailable for output screening: {e}")
            return {"safe": True, "reason": "llama_guard_unavailable"}

    return {"safe": True, "reason": "passed"}


# ─── Internal helpers ───────────────────────────────────────────────

def _classify_with_llama_guard(text: str) -> dict:
    """Classify text safety using NVIDIA NIM Llama Guard 4 12B.

    Calls the model via the LLM service's _complete function.
    Returns: {"safe": bool, "reason": str}
    """
    from services.llm_service import _complete

    try:
        result = _complete(
            provider="nvidia",
            model=os.getenv("GUARDRAILS_MODEL", "meta/llama-guard-4-12b"),
            messages=[{"role": "user", "content": text}],
            max_tokens=50,
            temperature=0,
            json_mode=False,
        )
        is_safe = "safe" in result.lower()
        return {
            "safe": is_safe,
            "reason": "llama_guard_safe" if is_safe else "llama_guard_unsafe",
        }
    except Exception as e:
        logger.warning(f"Llama Guard classification failed: {e}")
        # Graceful degradation: if Llama Guard is unavailable, assume safe
        # (already passed blocklist)
        return {"safe": True, "reason": "llama_guard_unavailable"}


def _is_ambiguous(message: str) -> bool:
    """Heuristic to determine if a message needs Llama Guard review.

    A message is considered ambiguous if:
    - It is longer than 200 characters AND
    - It contains at least one "soft concern" word
    """
    if len(message) <= 200:
        return False

    message_lower = message.lower()
    return any(word in message_lower for word in _SOFT_CONCERNS)
