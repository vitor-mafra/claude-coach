from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from claude_coach import __version__
from claude_coach.api import (
    admin,
    auth,
    briefing,
    dashboard,
    exercises,
    garmin,
    health,
    llm,
    plans,
    profile,
    reports,
    security,
    sessions,
)
from claude_coach.config import settings
from claude_coach.logging import configure_logging
from claude_coach.scheduler import shutdown as scheduler_shutdown, start as scheduler_start


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    configure_logging()
    scheduler_start()
    try:
        yield
    finally:
        scheduler_shutdown()


# Hide OpenAPI surface from unauthenticated visitors in prod.
_docs_kwargs = (
    {}
    if settings.expose_docs
    else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)

app = FastAPI(
    title="Claude Coach", version=__version__, lifespan=lifespan, **_docs_kwargs
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(auth.auth_middleware)
app.middleware("http")(security.security_headers_middleware)

app.include_router(auth.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(exercises.router, prefix="/api")
app.include_router(plans.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(garmin.router, prefix="/api")
app.include_router(sessions.workouts_router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(briefing.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


# ─── Serve frontend SPA when present (production single-container deploy) ─────
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    _INDEX_HTML = _STATIC_DIR / "index.html"

    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # Anything not /api/* falls through to here. Serve the static file
        # if present, else hand the SPA's index.html to the client router.
        candidate = _STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_INDEX_HTML)
