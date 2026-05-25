"""Security hardening regression tests:
- Slug validation on read endpoints (path-traversal class).
- Upload size + magic-bytes guard on PDF upload.
- Expensive-op rate limit (briefing / report / upload / etc).
- Security headers when toggled on.
- Docs are hidden when expose_docs=False.
"""

from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient


def _rebuild_app() -> object:
    from claude_coach import config as config_mod

    importlib.reload(config_mod)
    for mod_name in (
        "claude_coach.db.session",
        "claude_coach.services.exercise_catalog",
        "claude_coach.services.plan_repo",
        "claude_coach.services.profile",
        "claude_coach.services.weekly_report",
        "claude_coach.services.garmin_sync",
        "claude_coach.adapters.garmin",
        "claude_coach.api.security",
        "claude_coach.api.admin",
        "claude_coach.api.auth",
        "claude_coach.api.briefing",
        "claude_coach.api.garmin",
        "claude_coach.api.plans",
        "claude_coach.api.reports",
    ):
        importlib.reload(importlib.import_module(mod_name))
    auth_mod = importlib.import_module("claude_coach.api.auth")
    auth_mod._attempts.clear()
    sec_mod = importlib.import_module("claude_coach.api.security")
    sec_mod._buckets.clear()

    from claude_coach import main as main_mod

    importlib.reload(main_mod)

    # Fresh in-memory schema.
    from claude_coach.db import session as db_session
    from claude_coach.db.base import Base

    Base.metadata.create_all(db_session.engine)
    return main_mod.app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_PASSWORD", raising=False)  # auth disabled
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EXPOSE_DOCS", "false")
    monkeypatch.setenv("ADD_SECURITY_HEADERS", "true")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")  # 1 KB cap for fast tests
    monkeypatch.setenv("EXPENSIVE_OP_MAX_PER_WINDOW", "2")
    (tmp_path / "garmin_tokens").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    return TestClient(_rebuild_app())  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_after(monkeypatch):
    yield
    for k in (
        "APP_PASSWORD",
        "DATA_DIR",
        "EXPOSE_DOCS",
        "ADD_SECURITY_HEADERS",
        "MAX_UPLOAD_BYTES",
        "EXPENSIVE_OP_MAX_PER_WINDOW",
    ):
        monkeypatch.delenv(k, raising=False)
    _rebuild_app()


def test_docs_are_hidden_when_expose_docs_false(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_security_headers_are_added(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("strict-transport-security")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in {k.lower() for k in r.headers}


@pytest.mark.parametrize(
    "bad_slug,expected_codes",
    [
        # URL-normalized away by Starlette → reaches a different route → 404
        ("../../etc", {400, 404, 405}),
        ("..", {400, 404, 405}),
        (".", {200, 400, 404, 405}),  # `.` normalizes to /api/plans/ → list
        # These reach our handler as the literal slug → 400 from validator
        ("with space", {400}),
        ("UpperCase", {400}),
        ("-leading-dash", {400}),
        ("x" * 65, {400}),
        # ? is treated as query string by curl/httpx
        ("weird?chars", {400, 404}),
    ],
)
def test_plan_get_rejects_unsafe_slug(client, bad_slug, expected_codes):
    r = client.get(f"/api/plans/{bad_slug}")
    assert r.status_code in expected_codes, (bad_slug, r.status_code, r.text)


def test_plan_review_rejects_unsafe_slug(client):
    r = client.get("/api/plans/..%2F..%2Fetc/review")
    # URL normalization sends this to the SPA catchall (200) or 400 from validator
    assert r.status_code in (400, 404)


def test_upload_rejects_oversized(client):
    blob = b"%PDF-1.4 " + b"x" * 2048  # exceeds 1 KB cap
    r = client.post(
        "/api/plans/upload",
        files={"pdf": ("p.pdf", io.BytesIO(blob), "application/pdf")},
        data={"skip_schedule": "true"},
    )
    assert r.status_code == 413


def test_upload_rejects_missing_pdf_magic(client):
    r = client.post(
        "/api/plans/upload",
        files={"pdf": ("p.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
        data={"skip_schedule": "true"},
    )
    assert r.status_code == 422
    assert "magic" in r.json()["detail"].lower()


def test_upload_rejects_wrong_content_type(client):
    r = client.post(
        "/api/plans/upload",
        files={"pdf": ("p.pdf", io.BytesIO(b"%PDF-1.4 ok"), "image/png")},
        data={"skip_schedule": "true"},
    )
    assert r.status_code == 422


def test_expensive_op_rate_limit_triggers_429(client, monkeypatch):
    # Stub the parser so upload doesn't actually call OpenAI.
    from claude_coach.api import plans as plans_mod
    from claude_coach.adapters.pdf_parser import ParseOutput
    from claude_coach.domain.plan import (
        ExerciseRef,
        MetaRepsBlock,
        Plan,
        RestSpec,
        WorkoutTemplate,
    )

    fake_plan = Plan(
        name="x",
        templates={
            "A": WorkoutTemplate(
                template_id="A",
                name="A",
                kind="strength",
                blocks=[
                    MetaRepsBlock(
                        exercise=ExerciseRef(raw_name="ex"),
                        sets=1,
                        reps=1,
                        rest=RestSpec(seconds=1),
                    )
                ],
            )
        },
        schedule={},
    )

    def fake_parse_pdf(pdf_path, plan_dir, **kwargs):
        return ParseOutput(
            plan=fake_plan,
            review_md="x",
            raw_response_text="{}",
            raw_response_path=plan_dir / "raw.json",
        )

    monkeypatch.setattr(plans_mod, "parse_pdf", fake_parse_pdf)

    def do_upload():
        return client.post(
            "/api/plans/upload",
            files={"pdf": ("p.pdf", io.BytesIO(b"%PDF-1.4 ok"), "application/pdf")},
            data={"skip_schedule": "true"},
        )

    assert do_upload().status_code == 201
    assert do_upload().status_code == 201
    # Third request hits the limit (window = 2)
    third = do_upload()
    assert third.status_code == 429
    assert "rate limited" in third.json()["detail"].lower()


def test_login_session_secret_falls_back_to_password(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", "hunter2")
    monkeypatch.delenv("APP_SESSION_SECRET", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "garmin_tokens").mkdir(parents=True, exist_ok=True)
    c = TestClient(_rebuild_app())  # type: ignore[arg-type]
    # Auth still works; session signing key derives from password as documented.
    r = c.post("/api/auth/login", json={"password": "hunter2"})
    assert r.status_code == 200
    assert "cc_session" in c.cookies
