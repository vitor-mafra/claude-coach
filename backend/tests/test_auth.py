from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


def _rebuild_app() -> object:
    """Reload config + auth + main so the module-level `settings` picks up
    fresh env vars. Needed because `config.settings = get_settings()` is
    computed once on import."""
    from claude_coach import config as config_mod

    importlib.reload(config_mod)
    from claude_coach.api import auth as auth_mod

    importlib.reload(auth_mod)
    auth_mod._attempts.clear()
    from claude_coach import main as main_mod

    importlib.reload(main_mod)
    return main_mod.app


@pytest.fixture
def client_with_password(monkeypatch):
    """Build a fresh TestClient where APP_PASSWORD is configured."""
    monkeypatch.setenv("APP_PASSWORD", "hunter2")
    monkeypatch.setenv("APP_SESSION_SECRET", "test-secret")
    return TestClient(_rebuild_app())  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_settings_after(monkeypatch):
    yield
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("APP_SESSION_SECRET", raising=False)
    _rebuild_app()


def test_health_is_public(client_with_password):
    r = client_with_password.get("/api/health")
    assert r.status_code == 200


def test_protected_route_without_cookie_is_401(client_with_password):
    r = client_with_password.get("/api/sessions")
    assert r.status_code == 401
    assert r.json()["detail"] == "not_authenticated"


def test_login_wrong_password_is_401(client_with_password):
    r = client_with_password.post("/api/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


def test_login_correct_password_sets_cookie_and_protects(client_with_password):
    c = client_with_password
    r = c.post("/api/auth/login", json={"password": "hunter2"})
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    assert "cc_session" in c.cookies

    # Now protected route works.
    r = c.get("/api/sessions")
    assert r.status_code == 200

    # And /api/auth/me reports authed.
    r = c.get("/api/auth/me")
    assert r.json()["authenticated"] is True


def test_logout_clears_cookie(client_with_password):
    c = client_with_password
    c.post("/api/auth/login", json={"password": "hunter2"})
    assert c.get("/api/sessions").status_code == 200

    c.post("/api/auth/logout")
    # Cookie cleared → protected route 401 again
    r = c.get("/api/sessions")
    assert r.status_code == 401


def test_rate_limit_kicks_in_after_5_bad_attempts(client_with_password):
    c = client_with_password
    for _ in range(5):
        r = c.post("/api/auth/login", json={"password": "x"})
        assert r.status_code == 401
    r = c.post("/api/auth/login", json={"password": "x"})
    assert r.status_code == 429


def test_no_password_configured_means_no_auth_required(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    c = TestClient(_rebuild_app())  # type: ignore[arg-type]

    r = c.get("/api/auth/me")
    assert r.json()["auth_required"] is False
    assert r.json()["authenticated"] is True

    # Protected route is open.
    r = c.get("/api/sessions")
    assert r.status_code == 200
