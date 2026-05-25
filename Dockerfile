# ─── Stage 1: build the frontend ─────────────────────────────────────────────
FROM node:22-alpine AS frontend

RUN corepack enable

WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc* frontend/pnpm-workspace.yaml* ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
# Vite must resolve API calls to same origin in prod (relative /api/*).
RUN pnpm build


# ─── Stage 2: backend + bundled static frontend ──────────────────────────────
FROM python:3.12-slim AS app

# uv for dependency install. Pinned for reproducibility.
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /usr/local/bin/uv

# System deps: libcurl for curl_cffi, build essentials for any wheels missing
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    libcurl4 \
    ca-certificates \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    DATA_DIR=/data \
    EXERCISES_DIR=/app/data/exercises

WORKDIR /app

# Install python deps first (better layer caching)
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev

# Copy backend source
COPY backend/ ./backend/
COPY config/ ./config/

# Copy seed data that is part of the image (catalog of exercises).
# Personal data (profile, plans, reports, db, tokens) lives in $DATA_DIR volume.
COPY data/exercises ./data/exercises

# Copy built frontend into the location FastAPI serves from.
COPY --from=frontend /app/dist /app/backend/claude_coach/static

# Create a non-root user and give it ownership of /app and /data.
# Volume permissions on Railway are inherited from the mount target — chowning
# /data here so the running user can write before any volume content exists.
RUN useradd --create-home --shell /bin/sh --uid 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /app /data

USER appuser
WORKDIR /app/backend

# Entry: apply migrations, then start uvicorn on Railway-provided $PORT
ENV PORT=8000
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn claude_coach.main:app --host 0.0.0.0 --port ${PORT}"]
