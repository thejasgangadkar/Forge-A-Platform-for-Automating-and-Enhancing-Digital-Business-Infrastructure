"""Multi-provider LLM service.

Two logical roles, each independently configurable via env:
  - "chat"  -> cheap, fast conversational model, used for intent routing, the
               workspace assistant and every customer-facing agent turn.
               Default: OpenRouter DeepSeek V4 Flash.
  - "build" -> strong coding model with a high output ceiling, used to compile
               multi-page websites. Default: OpenRouter DeepSeek V4 Pro.

Providers supported (all OpenAI-compatible): "openrouter", "groq", "gemini",
"nvidia". OpenRouter leads both chains on paid credit; the three free providers
sit behind it, so exhausted credit or an outage degrades to free inference
instead of taking the platform down.

Everything is model-agnostic: change CHAT_MODEL / BUILD_MODEL in
forge.config.env, no code edits. See provider_chain() for the fallback order.

NVIDIA NIM uses only models exposed on the free endpoint menu at build.nvidia.com
(served via https://integrate.api.nvidia.com/v1).
"""
import json
import os
import time

from dotenv import load_dotenv

load_dotenv()
# Load the documented control panel (forge.config.env) with priority — this is
# the single place the user edits keys/models. Falls back to .env values.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "forge.config.env"), override=True)

# ─── config ─────────────────────────────────────────────────────────
# Chat is the highest-volume role, so it runs the cheapest model that still
# handles RAG grounding and tool-call emission: DeepSeek V4 Flash.
CHAT_PROVIDER = os.getenv("CHAT_PROVIDER", "openrouter").lower()
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek/deepseek-v4-flash")
# Building runs DeepSeek V4 Pro: 384K max output is what makes one-shot
# multi-page generation possible, and its output tokens are ~4x cheaper than
# the nearest comparable coder model.
BUILD_PROVIDER = os.getenv("BUILD_PROVIDER", "openrouter").lower()
BUILD_MODEL = os.getenv("BUILD_MODEL", "deepseek/deepseek-v4-pro")

# Per-provider fallback models. Kept separate from the primaries so switching a
# primary never silently changes what the fallbacks use. Each role names its own
# model per provider, because a coder model is a poor conversationalist and a
# chat model is a poor page builder — sharing one entry across roles was a bug.
BUILD_GROQ_MODEL = os.getenv("BUILD_GROQ_MODEL", "openai/gpt-oss-120b")
BUILD_GEMINI_MODEL = os.getenv("BUILD_GEMINI_MODEL", "gemini-2.5-flash")
# openai/gpt-oss-120b was retired from NVIDIA; the DeepSeek family it now serves
# matches the paid primary, so a failover keeps output behaviour consistent.
BUILD_NVIDIA_MODEL = os.getenv("BUILD_NVIDIA_MODEL", "deepseek-ai/deepseek-v4-pro-0813")
BUILD_MODEL_FALLBACK = os.getenv("BUILD_MODEL_FALLBACK", "z-ai/glm-5.2:free")
# A second PAID OpenRouter model for the build role, tried straight after the
# primary. Added 2026-10-30: the build primary became z-ai/glm-5.3 (much faster
# on the direct page prompt), and the previous primary is the natural backup -
# it is slower but it works, and keeping it on the same paid provider means a
# transient upstream error does not drop the build to a free tier.
BUILD_MODEL_ALT = os.getenv("BUILD_MODEL_ALT", "")

CHAT_GROQ_MODEL = os.getenv("CHAT_GROQ_MODEL", "openai/gpt-oss-120b")
CHAT_GEMINI_MODEL = os.getenv("CHAT_GEMINI_MODEL", "gemini-2.5-flash")
# meta/llama-3.3-70b-instruct was retired from NVIDIA; NVIDIA now serves the
# same DeepSeek family free, keeping the fallback behaviourally close to primary.
CHAT_NVIDIA_MODEL = os.getenv("CHAT_NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash-0731")
CHAT_MODEL_FALLBACK = os.getenv("CHAT_MODEL_FALLBACK", "minimax/minimax-m3:free")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
# Google exposes an OpenAI-compatible surface, so Gemini needs no special client.
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Per-request timeout for every provider client.
# The OpenAI SDK default is 600s. A legitimate one-shot 4-page build
# (~45-50K output tokens) can brush against that, while a stalled upstream
# would tie up the request for ten minutes before the fallback chain got a
# chance to run. 900s leaves headroom for a slow-but-alive provider and still
# fails over eventually. Override with LLM_TIMEOUT_SECONDS if a deployment
# needs different headroom.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "900"))

_PROVIDER_KEYS = {
    "groq": GROQ_API_KEY,
    "nvidia": NVIDIA_API_KEY,
    "gemini": GEMINI_API_KEY,
    "openrouter": OPENROUTER_API_KEY,
}


def _has_key(provider: str) -> bool:
    return bool(_PROVIDER_KEYS.get(provider))


def provider_chain(role: str) -> list[tuple[str, str]]:
    """Ordered (provider, model) candidates to try for a role.

    Returning an explicit chain — rather than the nest of "have I already tried
    X?" flags this used to use — means adding a provider is one list entry, and
    the runtime order is readable at a glance.

    Providers without a configured key are dropped, and duplicates are removed so
    a provider is never retried with the same model twice.
    """
    # The primary is whatever the role is configured to use. Behind it sit the
    # three free providers, then a free OpenRouter model as the last resort — so
    # exhausted paid credit degrades to free inference rather than an outage.
    if role == "build":
        primary = BUILD_NVIDIA_MODEL if BUILD_PROVIDER == "nvidia" else BUILD_MODEL
        candidates = [
            (BUILD_PROVIDER, primary),
            # Second paid model on the same provider (see BUILD_MODEL_ALT).
            (BUILD_PROVIDER, BUILD_MODEL_ALT),
            ("groq", BUILD_GROQ_MODEL),         # free, fast (Groq LPU)
            ("gemini", BUILD_GEMINI_MODEL),     # free, no output cap
            ("nvidia", BUILD_NVIDIA_MODEL),     # free, slower
            ("openrouter", BUILD_MODEL_FALLBACK),   # free tier, rate-limited
        ]
    else:
        primary = CHAT_NVIDIA_MODEL if CHAT_PROVIDER == "nvidia" else CHAT_MODEL
        candidates = [
            (CHAT_PROVIDER, primary),
            ("groq", CHAT_GROQ_MODEL),          # free, fast (Groq LPU)
            ("gemini", CHAT_GEMINI_MODEL),      # free, fast (1.2s)
            ("nvidia", CHAT_NVIDIA_MODEL),      # free
            ("openrouter", CHAT_MODEL_FALLBACK),    # free tier, rate-limited
        ]

    chain, seen = [], set()
    for provider, model in candidates:
        provider = (provider or "").lower()
        if not provider or not model or not _has_key(provider):
            continue
        if (provider, model) in seen:
            continue
        seen.add((provider, model))
        chain.append((provider, model))
    return chain


# Error signatures that mean "this provider/model will not work" — move on
# rather than burning retries on it.
_PERMANENT = ("401", "403", "404", "410", "unauthorized", "not found",
              "end of life", "gone", "does not exist", "invalid_request",
              "insufficient", "credit", "402", "quota")
# Signatures that mean "try again shortly" or "send less".
_TRANSIENT = ("429", "rate", "503", "overloaded", "high demand", "timeout",
              "timed out", "502", "504")
_TOO_LARGE = ("413", "too large", "reduce")


# ─── lazy clients (OpenAI-compatible SDK for both) ──────────────────
_clients = {}


def _client(provider: str):
    if provider in _clients:
        return _clients[provider]
    from openai import OpenAI  # openai SDK speaks to Groq + OpenRouter too

    if provider == "groq":
        c = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1",
                   timeout=LLM_TIMEOUT)
    elif provider == "openrouter":
        c = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE,
            timeout=LLM_TIMEOUT,
            default_headers={
                "HTTP-Referer": "http://localhost",
                "X-Title": "Forge",
            },
        )
    elif provider == "nvidia":
        c = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE, timeout=LLM_TIMEOUT)
    elif provider == "gemini":
        c = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE, timeout=LLM_TIMEOUT)
    else:
        raise ValueError(f"Unknown provider: {provider}")
    _clients[provider] = c
    return c


# ─── core call ──────────────────────────────────────────────────────
def _complete_ex(provider, model, messages, max_tokens, temperature, json_mode):
    """Run a completion and report why it stopped.

    The finish reason matters because reasoning models (DeepSeek V4 Flash, for
    one) spend tokens on hidden reasoning before emitting any answer. If the
    budget runs out during that phase the API returns success with
    `content=None` and `finish_reason="length"`. Callers need to tell that apart
    from a genuine empty answer, so both values are returned.

    The request is made in STREAMING mode. That is a large, measured speed
    win on long generations: the same landing page took 152 s as a single
    non-streaming call but 39 s streamed, because a non-streaming request
    waits for the provider to assemble the entire response (and OpenRouter
    buffers long completions) before returning anything, while a streamed one
    delivers tokens as they are produced. The assembled text is identical.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Cap the REASONING budget separately from the output budget.
    #
    # This is the fix for the build being randomly 14 minutes instead of 2.
    # A reasoning model sometimes decides to deliberate for tens of thousands
    # of tokens before writing anything, which consumes the entire request
    # budget and returns no HTML at all. Measured on the same page prompt:
    #   no cap          -> 104 s, 16,000 reasoning tokens, 0 chars of HTML
    #   max_tokens=1024->   23 s, 1 reasoning token, 16,569 chars of HTML
    # The cap does not stop the model from thinking - it stops it from
    # THINKING INSTEAD OF ANSWERING, which is what a page-generation request
    # never needs.
    reasoning_cap = int(os.getenv("REASONING_MAX_TOKENS", "1024"))
    if reasoning_cap > 0:
        # OpenRouter takes provider-specific parameters in extra_body. The
        # OpenAI SDK itself does not know the "reasoning" field, so it has to
        # be passed that way or the SDK rejects the call.
        extra = kwargs.setdefault("extra_body", {})
        extra["reasoning"] = {"max_tokens": reasoning_cap}

    client = _client(provider)
    stream = client.chat.completions.create(**kwargs)

    parts = []
    finish = ""
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        choice = chunk.choices[0]
        if getattr(choice, "finish_reason", None):
            finish = choice.finish_reason
        delta = getattr(choice, "delta", None)
        content = getattr(delta, "content", None) if delta else None
        if content:
            parts.append(content)

    return ("".join(parts), finish)


def _complete(provider, model, messages, max_tokens, temperature, json_mode):
    """Back-compatible wrapper returning just the text (used by guardrails)."""
    content, _ = _complete_ex(provider, model, messages, max_tokens,
                              temperature, json_mode)
    return content


def llm(messages, role: str = "chat", max_tokens: int = 2048,
        temperature: float = 0.7, json_mode: bool = False,
        max_retries: int = 2) -> str:
    """Run a chat completion, walking the provider chain until one succeeds.

    `role` selects the chain ('chat' or 'build'). Within each provider the call
    is retried for transient problems (rate limits, overload, oversized request);
    a permanent problem (bad key, retired model, exhausted credit) moves straight
    to the next provider instead of wasting retries.
    """
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]

    chain = provider_chain(role)
    if not chain:
        raise RuntimeError(
            f"No provider configured for role '{role}'. Set an API key in "
            "forge.config.env (GROQ_API_KEY, NVIDIA_API_KEY, GEMINI_API_KEY "
            "or OPENROUTER_API_KEY)."
        )

    last_err: Exception | None = None
    attempted: list[str] = []

    for index, (provider, model) in enumerate(chain):
        tokens = max_tokens
        if index > 0:
            print(f"[llm] {role} fallback {index}/{len(chain) - 1} -> {provider}/{model}")
        attempted.append(f"{provider}/{model}")

        for attempt in range(max_retries + 1):
            try:
                content, finish = _complete_ex(provider, model, messages, tokens,
                                               temperature, json_mode)
                if content.strip():
                    return content

                # An empty body is NOT success. Returning it here would hand
                # callers a blank website or a blank agent reply while every
                # error path stayed silent, and call_json() would degrade it
                # further into an empty dict.
                if finish == "length":
                    # A reasoning model burned the whole budget before answering.
                    #
                    # Growing the budget is the right instinct, but the old
                    # growth (x4, capped at 256K) was actively harmful: on the
                    # website build it produced a 256K-token request that spent
                    # 14 minutes reasoning and still returned nothing, while the
                    # useful retry is a fresh attempt at a budget that fits the
                    # answer, not an ever-larger one.
                    #
                    # So the growth is now modest and bounded, and it never
                    # exceeds what the caller asked for by much.
                    grown = min(int(tokens * 1.5) + 4096, 128000)
                    if grown > tokens and attempt < max_retries:
                        tokens = grown
                        print(f"[llm] {model} returned only reasoning; "
                              f"raising max_tokens to {tokens}")
                        continue
                print(f"[llm] {provider}/{model} returned an empty body "
                      f"(finish={finish or 'unknown'}); trying the next provider")
                break  # next provider

            except Exception as e:
                last_err = e
                msg = str(e).lower()

                # Some providers state exactly what budget is affordable.
                afford = _parse_affordable(str(e))
                if afford and afford > 512 and afford - 64 < tokens:
                    tokens = max(512, afford - 64)
                    print(f"[llm] credit-limited; retrying {model} at max_tokens={tokens}")
                    continue

                if any(s in msg for s in _TOO_LARGE):
                    shrunk = max(1500, int(tokens * 0.6))
                    if shrunk < tokens:
                        tokens = shrunk
                        print(f"[llm] request too large; shrinking to {tokens}")
                        continue
                    break  # cannot shrink further, try the next provider

                if any(s in msg for s in _PERMANENT):
                    print(f"[llm] {provider}/{model} unusable: {str(e)[:110]}")
                    break  # next provider

                if any(s in msg for s in _TRANSIENT):
                    if attempt < max_retries:
                        wait = (2 ** attempt) * 1.5  # quick retry, not 6s
                        print(f"[llm] {provider} busy (try {attempt + 1}); sleep {wait:.0f}s")
                        time.sleep(wait)
                        continue
                    break  # give this provider up, try the next

                # Unrecognised error: one short retry, then move on.
                if attempt < max_retries:
                    time.sleep(1.2)
                    continue
                break

    raise RuntimeError(
        f"LLM failed for role '{role}' after trying {', '.join(attempted)}: {last_err}"
    )


def _parse_affordable(err: str):
    import re
    m = re.search(r"can only afford (\d+)", err)
    return int(m.group(1)) if m else None


# ─── convenience wrappers (back-compat + JSON) ──────────────────────
def _call_with_retry(prompt: str, max_retries: int = 3, max_tokens: int = 2048,
                     temperature: float = 0.7, json_mode: bool = False,
                     role: str = "chat") -> str:
    """Back-compatible helper used across the codebase."""
    return llm(prompt, role=role, max_tokens=max_tokens,
               temperature=temperature, json_mode=json_mode, max_retries=max_retries)


def call_json(prompt, role: str = "chat", max_tokens: int = 2048,
              temperature: float = 0.4) -> dict:
    # Don't use json_mode=True — many models (gpt-oss-120b, qwen3.6) either
    # refuse or produce empty output with strict JSON mode. Instead rely on
    # the prompt asking for JSON and _safe_json extracting it from free text.
    raw = llm(prompt, role=role, max_tokens=max_tokens,
              temperature=temperature, json_mode=False)
    return _safe_json(raw)


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks some models emit before the real answer."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _repair_truncated_json(text: str):
    """Best-effort recovery of JSON that was cut off mid-object.

    A reasoning model asked for a JSON answer can hit its token cap partway
    through, and the raw string then fails json.loads(). Rather than returning
    an empty dict (which the caller reads as "the model said nothing"), this
    closes whatever brackets are still open and discards the last incomplete
    key/value pair. Returns None when nothing sensible can be recovered.
    """
    import re as _re
    s = text.strip()
    # Work from the first brace/bracket so any prose around it is ignored.
    start = min([i for i in (s.find("{"), s.find("[")) if i != -1], default=-1)
    if start == -1:
        return None
    s = s[start:]

    # Drop a trailing incomplete pair: ..., "key": "value   -> cut back to the
    # last comma so the remaining object is still valid.
    s = _re.sub(r",\s*\"[^\"]*\"\s*:\s*[^,}\]]*$", "", s)
    s = _re.sub(r",\s*\"[^\"]*\"\s*:\s*$", "", s)
    s = _re.sub(r"\{\s*\"[^\"]*\"\s*:\s*[^,}\]]*$", "{", s)

    # Close any open brackets, respecting quotes so a brace inside a string
    # does not count.
    stack = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\":
            if in_str:
                esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    if not stack:
        return None
    for ch in reversed(stack):
        s += "}" if ch == "{" else "]"
    try:
        return json.loads(s)
    except Exception:
        return None


def _safe_json(text: str):
    if not text:
        return {}
    s = _strip_thinking(text).strip()
    if "```json" in s:
        s = s.split("```json", 1)[1].split("```", 1)[0].strip()
    elif s.startswith("```"):
        s = s.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(s)
    except Exception:
        for opener, closer in (("{", "}"), ("[", "]")):
            i, j = s.find(opener), s.rfind(closer)
            if i != -1 and j > i:
                try:
                    return json.loads(s[i:j + 1])
                except Exception:
                    continue
        # Truncated JSON: the model hit its token cap mid-object. Close the
        # open brackets and drop any trailing incomplete key/value pair, so a
        # cut-off response still yields the part that was complete instead of
        # an empty dict.
        repaired = _repair_truncated_json(s)
        if repaired is not None:
            return repaired
        return {}
