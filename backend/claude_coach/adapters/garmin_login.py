"""Custom Garmin login using curl_cffi for TLS fingerprint impersonation.

Garth's plain `requests`-based login is being blocked at the TLS layer by
Garmin's edge (Cloudflare-style) with 429s. We replicate the two SSO calls
using `curl_cffi` (which impersonates Chrome's TLS handshake), then transfer
cookies into garth's session and let it complete the OAuth1/OAuth2 exchange.

If/when garth or Garmin behavior changes, swap this back to `garth.login(...)`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import garth
from curl_cffi import requests as cffi_requests

from claude_coach.config import settings

CLIENT_ID = "GCM_ANDROID_DARK"
SSO_BASE = "https://sso.garmin.com"
SERVICE_URL = "https://mobile.integration.garmin.com/gcm/android"

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}


class LoginError(RuntimeError):
    pass


def _do_sso(
    email: str,
    password: str,
    prompt_mfa: Callable[[], str] | None,
) -> tuple[str, dict[str, str]]:
    """Do the two SSO calls via curl_cffi. Returns (service_ticket, cookie_jar_dict)."""
    sess = cffi_requests.Session(impersonate="chrome")
    sess.headers.update(_BROWSER_HEADERS)

    login_params = {"clientId": CLIENT_ID, "locale": "en-US", "service": SERVICE_URL}

    # 1) GET sign-in page to seed cookies.
    r = sess.get(
        f"{SSO_BASE}/mobile/sso/en/sign-in",
        params={"clientId": CLIENT_ID},
        headers={"Sec-Fetch-Site": "none"},
        timeout=15,
    )
    if r.status_code >= 400:
        raise LoginError(f"SSO sign-in page returned {r.status_code}")

    # 2) POST credentials to the mobile API endpoint.
    r = sess.post(
        f"{SSO_BASE}/mobile/api/login",
        params=login_params,
        json={
            "username": email,
            "password": password,
            "rememberMe": False,
            "captchaToken": "",
        },
        timeout=15,
    )
    if r.status_code >= 400:
        raise LoginError(
            f"SSO login returned {r.status_code}: {r.text[:200]}"
        )

    body: dict[str, Any] = r.json()
    status = body.get("responseStatus", {}) or {}
    resp_type = status.get("type")

    if resp_type == "MFA_REQUIRED":
        if not prompt_mfa:
            raise LoginError("MFA required but no prompt callback provided")
        mfa_info = body.get("customerMfaInfo") or {}
        mfa_method = mfa_info.get("mfaLastMethodUsed") or "email"
        code = prompt_mfa()
        r = sess.post(
            f"{SSO_BASE}/mobile/api/mfa/verifyCode",
            params=login_params,
            json={
                "mfaMethod": mfa_method,
                "mfaVerificationCode": code,
                "rememberMyBrowser": False,
                "reconsentList": [],
                "mfaSetup": False,
            },
            timeout=15,
        )
        if r.status_code >= 400:
            raise LoginError(f"MFA verify returned {r.status_code}: {r.text[:200]}")
        body = r.json()
        status = body.get("responseStatus", {}) or {}
        resp_type = status.get("type")

    if resp_type != "SUCCESSFUL":
        raise LoginError(f"Unexpected SSO response: {resp_type} {status.get('message', '')}")

    ticket = body.get("serviceTicketId")
    if not ticket:
        raise LoginError("Login succeeded but no serviceTicketId in response")

    cookies = {c.name: c.value for c in sess.cookies.jar}
    return ticket, cookies


def login(email: str, password: str, *, prompt_mfa: Callable[[], str] | None = None) -> None:
    """Authenticate with Garmin and persist OAuth tokens.

    On success, tokens are saved under `settings.garmin_tokens_dir` (created if
    missing). Raises `LoginError` on failure.
    """
    ticket, cookies = _do_sso(email, password, prompt_mfa)

    # garth.http.client holds the singleton requests.Session used for OAuth.
    client = garth.http.client
    for name, value in cookies.items():
        client.sess.cookies.set(name, value, domain=".garmin.com")

    # Hand off to garth: OAuth1 token exchange + OAuth2 token.
    from garth import sso as garth_sso

    oauth1 = garth_sso.get_oauth1_token(ticket, client)
    oauth2 = garth_sso.exchange(oauth1, client, login=True)
    client.oauth1_token = oauth1
    client.oauth2_token = oauth2

    settings.garmin_tokens_dir.mkdir(parents=True, exist_ok=True)
    garth.save(str(settings.garmin_tokens_dir))
