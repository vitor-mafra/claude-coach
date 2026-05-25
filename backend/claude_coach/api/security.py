"""Shared security primitives:
- Response middleware adding hardening headers.
- A per-IP rate limiter for "expensive" operations (LLM calls, uploads,
  external API hammering). Login has its own limiter in `auth.py`.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from claude_coach.config import settings


# ─── Security headers ─────────────────────────────────────────────────────────

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # CSP intentionally permissive on script-src for Vite chunked SPA + same-origin
    # API. No third-party scripts allowed.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


async def security_headers_middleware(request: Request, call_next: Callable):
    response = await call_next(request)
    if not settings.add_security_headers:
        return response
    for k, v in _SECURITY_HEADERS.items():
        # Don't clobber if upstream already set one.
        response.headers.setdefault(k, v)
    return response


# ─── Expensive-op rate limiter ────────────────────────────────────────────────

_buckets: dict[str, deque[float]] = {}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_expensive(name: str):
    """Returns a FastAPI dependency that throttles `name` per IP."""

    def dep(request: Request) -> None:
        key = f"{name}:{_client_ip(request)}"
        now = time.time()
        cutoff = now - settings.expensive_op_window_seconds
        bucket = _buckets.setdefault(key, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= settings.expensive_op_max_per_window:
            raise HTTPException(
                429,
                f"rate limited: too many '{name}' calls; wait a minute",
            )
        bucket.append(now)

    return dep
