.PHONY: help install dev backend frontend test lint format migrate migration parse garmin-login sync typegen clean

help:
	@echo "Targets:"
	@echo "  install              install backend (uv sync) and frontend (pnpm install)"
	@echo "  dev                  run backend and frontend in parallel"
	@echo "  backend              run backend only (port 8000)"
	@echo "  frontend             run frontend only (port 5173)"
	@echo "  test                 run pytest"
	@echo "  lint                 ruff check + tsc typecheck"
	@echo "  format               ruff format"
	@echo "  migrate              alembic upgrade head"
	@echo "  migration name='...' create new alembic revision (autogenerate)"
	@echo "  parse [pdf=PATH] [slug=NAME]"
	@echo "                       parse a training PDF (needs OPENAI_API_KEY)"
	@echo "  typegen              regenerate frontend/src/lib/api-generated.ts from /openapi.json"

install:
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	cd frontend && pnpm exec concurrently -n backend,frontend -c blue,magenta \
		"cd ../backend && uv run uvicorn claude_coach.main:app --reload --port 8000" \
		"pnpm dev"

backend:
	cd backend && uv run uvicorn claude_coach.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm exec tsc --noEmit

format:
	cd backend && uv run ruff format .

migrate:
	cd backend && uv run alembic upgrade head

migration:
	@test -n "$(name)" || (echo "Usage: make migration name='describe change'" && exit 1)
	cd backend && uv run alembic revision --autogenerate -m "$(name)"

parse:
	cd backend && uv run python ../scripts/parse_pdf.py $(if $(pdf),$(pdf)) $(if $(slug),--slug $(slug))

garmin-login:
	cd backend && uv run python ../scripts/garmin_login.py

sync:
	cd backend && uv run python -c "from claude_coach.db.session import SessionLocal; from claude_coach.services.garmin_sync import service; db=SessionLocal(); print(service.sync_day(db, day=$(if $(date),__import__('datetime').date.fromisoformat('$(date)'),None)).__dict__); db.close()"

typegen:
	@curl -sf http://localhost:8000/openapi.json -o /tmp/claude-coach-openapi.json \
		|| (echo "Backend must be running (make backend) for typegen" && exit 1)
	cd frontend && pnpm exec openapi-typescript /tmp/claude-coach-openapi.json -o src/lib/api-generated.ts
