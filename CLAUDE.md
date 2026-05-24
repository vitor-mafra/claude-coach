# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projeto

Claude Coach é um agente pessoal para gerenciar treinos híbridos (musculação + corrida) integrado ao Garmin. Lê treinos prescritos por um profissional (Time Híbrido), puxa dados do Garmin (treinos, sono, body battery, stress, peso) via `garth`, registra desempenho real do usuário e gera insights (briefing pré-treino sob demanda, relatório semanal automático). Usuário único (dono do repo).

## Stack

- **Backend**: Python 3.11+ com FastAPI servindo API JSON. Types do TS gerados automaticamente do OpenAPI via `openapi-typescript`.
- **Frontend**: Vite + React 18 + TypeScript + Tailwind CSS + shadcn/ui + TanStack Query + TanStack Router + Recharts + `vite-plugin-pwa`. Mobile-first.
- **Persistência**:
  - **Markdown/YAML em git** (`data/plans/`, `data/exercises/`, `data/reports/`, `data/profile.yaml`) — planos parseados, catálogo de exercícios, relatórios, perfil estático.
  - **SQLite** (`data/metrics.db`, gitignored) — time-series: métricas Garmin, sessions, sets, llm_calls, sync_runs.
- **Garmin**: `garth` (não-oficial). Login CLI persistente (tokens em `data/garmin_tokens/`). Sync diário 7h + on-demand. Dump completo: `raw_payload` JSON + colunas tipadas pro que consumimos.
- **LLM**: camada de abstração com router por `task_id` (`config/llm_routing.yaml`). Providers: Claude (Anthropic), OpenAI. Default Claude Sonnet 4.6. Logging de custo em tabela `llm_calls`.
- **Scheduler**: APScheduler in-process (portável local → Railway).
- **E-mail**: Resend (relatório semanal).
- **Secrets**: `.env` + `pydantic-settings`. Nunca commitar.

## Convenções

- **Adapter pattern obrigatório**: nada importa `garth`, SDKs de LLM, ou `pdfplumber` direto fora de `backend/claude_coach/adapters/`. Resto do código fala com `GarminAdapter`, `LLMRouter`, `PDFParser`.
- **Alembic desde dia 1**. `create_all()` é proibido. Toda mudança de schema é uma migration.
- **Backend só fala JSON**. Sem templates server-side. Frontend consome via OpenAPI client gerado.
- **Catálogo de exercícios canônico**: `exercises/<exercise_id>.yaml` com `name`, `aliases[]`, `muscle_group`, `equipment`. Parser usa LLM pra matchar strings novas; baixa confiança pede confirmação humana via `REVIEW.md`.
- **Logging estruturado** com `structlog` (JSON em prod, console em dev).
- **Testes mínimos viáveis**: pytest cobre parser, LLM router, regras de matching session↔activity, cálculos (Epley, Tanaka). UI é testada manualmente. CI só quando subir pro Railway.

## Fases

1. **Fase 0 — Alinhamento** (concluída): este arquivo + `@docs/architecture.md`.
2. **Fase 1 — Esqueleto**: monorepo, pyproject, alembic, .env, Makefile, FastAPI hello-world, Vite app vazio, frontend↔backend conectados.
3. **Fase 2 — Perfil + PDF parser**: onboarding wizard, parser LLM-vision, catálogo seed, REVIEW.md flow.
4. **Fase 3 — Garmin sync**: adapter `garth`, login CLI, sync diário + on-demand, schema `daily_metrics` + `garmin_activities`.
5. **Fase 4 — Sessions**: UI de log set-a-set com pre-fill, nota livre, auto-match com activity Garmin.
6. **Fase 5 — Briefing pré-treino**: endpoint on-demand, contexto histórico (últimas 2-3 sessões do exercício + Garmin do dia), prompt Claude.
7. **Fase 6 — Relatório semanal**: scheduler, prompt Claude, persistência híbrida, envio via Resend.
8. **Fase 7 — Deploy Railway**: auth simples (password + cookie HttpOnly), env vars produção, PWA install.

## MVP (pilares)

1. Importar e estruturar treinos do PDF (parser LLM-vision)
2. Sync automático do Garmin
3. Registro de desempenho do treino (set-a-set, nota livre)
4. Análise/insights (briefing on-demand + relatório semanal)

Sem auto-progressão de carga no MVP. Sugestões de carga aparecem dentro do briefing.

## Documentação viva

- Arquitetura, decisões e roadmap em `@docs/architecture.md`.
- PDF original do plano em `time-hibrido-5531999669820 (1).pdf` (será movido pra `data/plans/raw/` na Fase 2).
