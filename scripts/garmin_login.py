"""Interactive Garmin login. Persists OAuth tokens under
`data/garmin_tokens/` so the adapter can `garth.resume(...)` later.

Uses curl_cffi to bypass Garmin's TLS fingerprinting of the default requests
client (which yields persistent 429s on /mobile/api/login).

Usage:
    cd backend && uv run python ../scripts/garmin_login.py
"""

from __future__ import annotations

import getpass
import sys

from claude_coach.adapters.garmin_login import LoginError, login
from claude_coach.config import settings


def _prompt_mfa() -> str:
    return input("Garmin MFA code: ").strip()


def main() -> int:
    email = settings.garmin_email or input("Garmin email: ").strip()
    password = settings.garmin_password or getpass.getpass("Garmin password: ")

    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        return 1

    print(f"Logging in as {email}...")
    try:
        login(email, password, prompt_mfa=_prompt_mfa)
    except LoginError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 3

    print(f"Tokens saved to {settings.garmin_tokens_dir}")
    print("You can now remove GARMIN_PASSWORD from .env (tokens persist).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
