"""Per-client rate limiting for the unauthenticated public endpoints.

The agent chat endpoint and the hosted chat page are deliberately public - a
business shares them with its customers, who must not need an account. That also
means anyone who learns a workspace id can call them in a loop and burn the
project's LLM quota, so both are metered per client IP.

Implementation is an in-process sliding window: no extra dependency, no Redis,
and sufficient for a single-instance deployment. If Forge is ever scaled to
multiple workers this needs to move to a shared store, since each process would
otherwise keep its own independent counter.
"""
import os
import threading
import time

from fastapi import HTTPException, Request

# window length in seconds, and the max requests allowed inside it
CHAT_LIMIT = int(os.getenv("RATE_LIMIT_CHAT", "20"))
CHAT_WINDOW = int(os.getenv("RATE_LIMIT_CHAT_WINDOW", "60"))
PAGE_LIMIT = int(os.getenv("RATE_LIMIT_PAGE", "60"))
PAGE_WINDOW = int(os.getenv("RATE_LIMIT_PAGE_WINDOW", "60"))

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()
_last_sweep = 0.0


def client_ip(request: Request) -> str:
    """Best-effort client identity, honouring the usual proxy headers."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    """Drop buckets that are entirely stale so memory cannot grow unbounded."""
    global _last_sweep
    if now - _last_sweep < 300:
        return
    _last_sweep = now
    longest = max(CHAT_WINDOW, PAGE_WINDOW)
    for key in [k for k, v in _hits.items() if not v or now - v[-1] > longest * 2]:
        _hits.pop(key, None)


def check(key: str, limit: int, window: int) -> tuple[bool, int]:
    """Record a hit. Returns (allowed, retry_after_seconds)."""
    now = time.time()
    with _lock:
        _sweep(now)
        bucket = [t for t in _hits.get(key, []) if now - t < window]
        if len(bucket) >= limit:
            _hits[key] = bucket
            retry = max(1, int(window - (now - bucket[0])) + 1)
            return False, retry
        bucket.append(now)
        _hits[key] = bucket
        return True, 0


def enforce(request: Request, scope: str, workspace_id: str = "") -> None:
    """Raise HTTP 429 when the caller has exceeded the limit for `scope`."""
    if os.getenv("RATE_LIMIT_ENABLED", "true").lower() not in ("true", "1", "yes"):
        return

    limit, window = (CHAT_LIMIT, CHAT_WINDOW) if scope == "chat" else (PAGE_LIMIT, PAGE_WINDOW)
    # Key on IP + scope + workspace so one busy workspace cannot starve another.
    key = f"{scope}:{workspace_id}:{client_ip(request)}"
    allowed, retry = check(key, limit, window)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(f"Too many requests. Please wait {retry}s before trying again."),
            headers={"Retry-After": str(retry)},
        )
