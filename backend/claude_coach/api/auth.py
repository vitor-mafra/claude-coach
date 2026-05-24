"""Single-password auth with signed HttpOnly cookie.

Design choices:
- One shared password (`APP_PASSWORD`). Single-user app, no user table needed.
- Signed cookie using `itsdangerous.URLSafeTimedSerializer` — expiry baked in.
- Cookie is HttpOnly + SameSite=Lax. `Secure` toggle via env (off for localhost,
  on in prod over HTTPS).
- Brute-force protection: in-memory sliding window per IP. Process-local; fine
  for single instance, would need Redis-ish for multi-replica.
- Public endpoints (no auth required): /api/health, /api/auth/*.
"""

from __future__ import annotations

import hmac
import time
from collections import deque
from collections.abc import Callable

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from claude_coach.config import settings

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_SALT = "claude-coach-session-v1"
_PUBLIC_PATH_PREFIXES = ("/api/auth", "/api/health")


# ─── Session token helpers ────────────────────────────────────────────────────


def _serializer() -> URLSafeTimedSerializer:
    secret = settings.app_session_secret or settings.app_password or "dev-secret"
    return URLSafeTimedSerializer(secret_key=secret, salt=_SESSION_SALT)


def make_session_token() -> str:
    return _serializer().dumps({"v": 1})


def verify_session_token(token: str) -> bool:
    try:
        _serializer().loads(token, max_age=settings.auth_cookie_max_age_seconds)
    except SignatureExpired:
        return False
    except BadSignature:
        return False
    return True


# ─── Brute-force limiter ──────────────────────────────────────────────────────

_attempts: dict[str, deque[float]] = {}


def _record_attempt(ip: str) -> None:
    now = time.time()
    bucket = _attempts.setdefault(ip, deque())
    bucket.append(now)
    cutoff = now - settings.auth_login_window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def _too_many(ip: str) -> bool:
    bucket = _attempts.get(ip)
    if not bucket:
        return False
    cutoff = time.time() - settings.auth_login_window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return len(bucket) >= settings.auth_login_max_attempts


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─── Middleware ───────────────────────────────────────────────────────────────


def is_public_path(path: str) -> bool:
    return any(path.startswith(p) for p in _PUBLIC_PATH_PREFIXES)


def request_is_authenticated(request: Request) -> bool:
    if settings.app_password is None:
        # Auth disabled (local dev / tests). Treat as authenticated.
        return True
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        return False
    return verify_session_token(token)


async def auth_middleware(request: Request, call_next: Callable):
    # Always allow OPTIONS (CORS preflight) and non-API routes.
    if request.method == "OPTIONS" or not request.url.path.startswith("/api"):
        return await call_next(request)
    if is_public_path(request.url.path):
        return await call_next(request)
    if request_is_authenticated(request):
        return await call_next(request)
    return JSONResponse({"detail": "not_authenticated"}, status_code=401)


# ─── Endpoints ────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    password: str


class AuthStatus(BaseModel):
    authenticated: bool
    auth_required: bool


@router.get("/me", response_model=AuthStatus)
def me(request: Request) -> AuthStatus:
    return AuthStatus(
        authenticated=request_is_authenticated(request),
        auth_required=settings.app_password is not None,
    )


@router.post("/login", response_model=AuthStatus)
def login(payload: LoginRequest, request: Request, response: Response) -> AuthStatus:
    if settings.app_password is None:
        # No password configured — treat as already authenticated.
        return AuthStatus(authenticated=True, auth_required=False)

    ip = _client_ip(request)
    if _too_many(ip):
        log.warning("auth.login.rate_limited", ip=ip)
        raise HTTPException(429, "too many attempts; try again later")

    # Constant-time comparison to thwart timing attacks.
    correct = hmac.compare_digest(payload.password, settings.app_password)
    if not correct:
        _record_attempt(ip)
        log.warning("auth.login.fail", ip=ip)
        raise HTTPException(401, "invalid password")

    token = make_session_token()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_cookie_max_age_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    log.info("auth.login.ok", ip=ip)
    return AuthStatus(authenticated=True, auth_required=True)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response) -> AuthStatus:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        samesite="lax",
    )
    return AuthStatus(
        authenticated=False,
        auth_required=settings.app_password is not None,
    )
