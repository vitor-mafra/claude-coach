"""Smoke tests for admin + plan upload endpoints. Heavy I/O (real Garmin SSO,
real LLM call for PDF parse) is monkeypatched."""

from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient


def _rebuild_app() -> object:
    """Reload config + every module that captured `settings` at import time so
    fresh env vars take effect."""
    from claude_coach import config as config_mod

    importlib.reload(config_mod)

    # Modules that did `from claude_coach.config import settings` at top level.
    from claude_coach.db import session as db_session_mod
    from claude_coach.api import (
        admin as admin_mod,
        auth as auth_mod,
        garmin as garmin_api_mod,
        plans as plans_api_mod,
    )
    from claude_coach.services import (
        exercise_catalog as ec_mod,
        garmin_sync as gs_mod,
        plan_repo as pr_mod,
        profile as pf_mod,
        weekly_report as wr_mod,
    )
    from claude_coach.adapters import garmin as garmin_adapter_mod

    for mod in (
        db_session_mod,
        ec_mod,
        pr_mod,
        pf_mod,
        wr_mod,
        gs_mod,
        garmin_adapter_mod,
        admin_mod,
        auth_mod,
        garmin_api_mod,
        plans_api_mod,
    ):
        importlib.reload(mod)
    auth_mod._attempts.clear()

    from claude_coach import main as main_mod

    importlib.reload(main_mod)
    return main_mod.app


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Auth disabled (no APP_PASSWORD), data_dir pointed at tmp,
    schema created on a fresh SQLite at $tmp_path/metrics.db."""
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GARMIN_EMAIL", "user@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "secret")
    (tmp_path / "garmin_tokens").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    app = _rebuild_app()

    # The fresh SQLite has no tables — create them from models.
    from claude_coach.db import session as db_session
    from claude_coach.db.base import Base

    Base.metadata.create_all(db_session.engine)
    return TestClient(app)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_after(monkeypatch):
    yield
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    _rebuild_app()


def test_system_status_reports_initial_empty_state(client, tmp_path):
    r = client.get("/api/admin/system")
    assert r.status_code == 200
    body = r.json()
    assert body["data_dir"] == str(tmp_path)
    assert body["profile_configured"] is False
    assert body["plans_count"] == 0
    assert body["garmin_connected"] is False
    assert body["garmin_credentials_present"] is True
    assert body["db_sessions"] == 0


def test_garmin_status_starts_disconnected(client):
    r = client.get("/api/admin/garmin/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False
    assert r.json()["has_oauth2_token"] is False


def test_garmin_connect_success(client, monkeypatch, tmp_path):
    calls = []

    def fake_login(email, password, *, prompt_mfa=None):
        calls.append((email, password, prompt_mfa))
        # Simulate persisting tokens to the configured dir.
        (tmp_path / "garmin_tokens" / "oauth2_token.json").write_text("{}")

    from claude_coach.api import admin as admin_mod

    monkeypatch.setattr(admin_mod, "garmin_login", fake_login)

    r = client.post("/api/admin/garmin/connect", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True
    assert body["needs_mfa"] is False
    assert calls == [("user@example.com", "secret", None)]

    # Status now reflects connected.
    r = client.get("/api/admin/garmin/status")
    assert r.json()["connected"] is True


def test_garmin_connect_mfa_required_returns_422_like(client, monkeypatch):
    from claude_coach.adapters.garmin_login import LoginError
    from claude_coach.api import admin as admin_mod

    def fake_login(email, password, *, prompt_mfa=None):
        raise LoginError("MFA required but no prompt callback provided")

    monkeypatch.setattr(admin_mod, "garmin_login", fake_login)

    r = client.post("/api/admin/garmin/connect", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["needs_mfa"] is True


def test_garmin_connect_passes_mfa_code(client, monkeypatch, tmp_path):
    received = {}

    def fake_login(email, password, *, prompt_mfa=None):
        received["code"] = prompt_mfa() if prompt_mfa else None
        (tmp_path / "garmin_tokens" / "oauth2_token.json").write_text("{}")

    from claude_coach.api import admin as admin_mod

    monkeypatch.setattr(admin_mod, "garmin_login", fake_login)

    r = client.post("/api/admin/garmin/connect", json={"mfa_code": "987654"})
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert received["code"] == "987654"


def test_garmin_connect_missing_credentials_is_422(client, monkeypatch):
    # Empty strings override any .env values and read as falsy in the endpoint.
    monkeypatch.setenv("GARMIN_EMAIL", "")
    monkeypatch.setenv("GARMIN_PASSWORD", "")
    c = TestClient(_rebuild_app())  # type: ignore[arg-type]
    r = c.post("/api/admin/garmin/connect", json={})
    assert r.status_code == 422


def test_garmin_disconnect_removes_token_files(client, tmp_path):
    tokens = tmp_path / "garmin_tokens"
    (tokens / "oauth1_token.json").write_text("{}")
    (tokens / "oauth2_token.json").write_text("{}")
    assert client.get("/api/admin/garmin/status").json()["connected"] is True

    r = client.delete("/api/admin/garmin/tokens")
    assert r.status_code == 204
    assert client.get("/api/admin/garmin/status").json()["connected"] is False


def test_plan_upload_runs_parser_and_persists(client, monkeypatch):
    from claude_coach.api import plans as plans_mod
    from claude_coach.adapters.pdf_parser import ParseOutput
    from claude_coach.domain.plan import (
        MetaRepsBlock,
        Plan,
        WorkoutTemplate,
        ExerciseRef,
        RestSpec,
    )

    fake_plan = Plan(
        name="Stub Plan",
        level="Test",
        weeks_duration=1,
        templates={
            "A": WorkoutTemplate(
                template_id="A",
                name="Treino A",
                kind="strength",
                blocks=[
                    MetaRepsBlock(
                        exercise=ExerciseRef(raw_name="Supino reto"),
                        sets=3,
                        reps=10,
                        rest=RestSpec(seconds=60),
                    )
                ],
            )
        },
        schedule={},
    )

    def fake_parse_pdf(pdf_path, plan_dir, **kwargs):
        return ParseOutput(
            plan=fake_plan,
            review_md="# REVIEW\nAll good",
            raw_response_text="{}",
            raw_response_path=plan_dir / "raw_response.json",
        )

    monkeypatch.setattr(plans_mod, "parse_pdf", fake_parse_pdf)
    # Skip schedule inference (no profile + no LLM key needed)
    files = {"pdf": ("my-plan.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    r = client.post(
        "/api/plans/upload",
        files=files,
        data={"skip_schedule": "true"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "my-plan"
    assert body["plan_yaml_path"].endswith("my-plan/plan.yaml")
    assert body["scheduled"] is False

    # And it shows up in the listing.
    r2 = client.get("/api/plans")
    assert "my-plan" in r2.json()


def test_plan_upload_rejects_non_pdf(client):
    files = {"pdf": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    r = client.post("/api/plans/upload", files=files)
    assert r.status_code == 422
