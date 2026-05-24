from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from claude_coach import __version__
from claude_coach.api import (
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


app = FastAPI(title="Claude Coach", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(auth.auth_middleware)

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
