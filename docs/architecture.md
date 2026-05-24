# Arquitetura — Claude Coach

Documento vivo. Atualizar conforme decisões mudam.

## Visão de produto

Agente pessoal para treino híbrido (musculação 4x/sem + corrida). O ciclo é:

1. **Importar** plano prescrito pelo Time Híbrido (PDF) → estrutura canônica em git.
2. **Sincronizar** dados do Garmin (corridas, sono, body battery, stress, peso, HRV, training readiness, etc.) — diariamente + sob demanda.
3. **Registrar** execução real dos treinos de musculação (set-a-set, nota livre subjetiva). Corrida vem 100% do Garmin.
4. **Briefing pré-treino sob demanda** ("vou treinar agora"): recap do que vai treinar, últimas cargas, leitura do estado fisiológico do dia (Garmin), sugestões pontuais de carga.
5. **Relatório semanal automático** (segunda 8h, via e-mail + UI): adesão, métricas agregadas, análise interpretativa, alertas (sono caindo, stress alto, estagnação de carga).

Sem auto-geração de progressão no MVP. O Coach observa e sugere; quem decide carga é o usuário (apoiado em Epley estimado a partir do log + observações do briefing).

## Decisões consolidadas (entrevista de alinhamento)

| # | Decisão |
|---|---------|
| 1 | Hosting: local no Mac primeiro; Railway depois (sem refator de scheduler porque APScheduler é in-process). |
| 2 | Ground truth do desempenho de força = log manual. Garmin = dado objetivo de cardio/recuperação. |
| 3 | Plano = template fixo (1 semana do PDF) repetido por ~1 mês; futuro = novos PDFs do mesmo time, schema versionado. |
| 4 | Sem auto-progressão no MVP. Briefing escopo completo (recap + métricas Garmin do dia + contexto histórico das últimas 2-3 sessões + sugestões pontuais), disparo on-demand. |
| 5 | Treinos B e D do PDF são idênticos → tratar como mesmo `template_id` compartilhado. |
| 6 | Log de musculação: set-a-set explícito com carga do 1º set pré-preenchida nos demais (user ajusta); nota livre por exercício; sem RPE. Corrida = 100% Garmin (sem confirmação bloco-a-bloco). |
| 7 | Catálogo canônico de exercícios com atributos (`muscle_group`, `equipment`). Parser usa LLM pra matching; confiança baixa → confirmação humana via `REVIEW.md`. |
| 8 | Frontend: Vite + React 18 + TS + Tailwind + shadcn/ui + TanStack (Query/Router) + Recharts + PWA. Backend: FastAPI JSON puro, types TS autogerados do OpenAPI. |
| 9 | PDF parser: LLM-vision (Claude Sonnet 4.6) + schema Pydantic + REVIEW.md commitado + cache de imagens em `data/plans/<plan>/raw/`. |
| 10 | Garmin: login CLI persistente, dump completo via `garth` (`raw_payload` JSON + colunas tipadas), sync diário 7h + on-demand, auto-match session↔activity com desfazer, `valid_as_of_timestamp` em `daily_metrics`. |
| 11 | Relatório semanal: escopo completo, default seg 8h (configurável), UI + e-mail via Resend, persistência DB + markdown commitado em `data/reports/<year>/<week>.md`. |
| 12 | Perfil: estático em `data/profile.yaml`, dinâmico no SQLite (peso diário manual, % gordura quando medir, FCmáx via Tanaka mas wizard checa Garmin), 1RM calculado via Epley do log + override `tested_1rm` opcional. |
| 13 | LLM abstraction: router por `task_id` + `config/llm_routing.yaml`, logging em `llm_calls`, streaming opt-in, retry, cache por hash de input, dry-run mode. |
| 14 | Scheduler APScheduler in-process. E-mail via Resend. Secrets `.env` + `pydantic-settings`. Garmin password apagado do .env após primeiro login (tokens persistem). |
| 15 | Repo: monorepo (backend/ + frontend/ + data/ + docs/ + scripts/), Alembic desde dia 1, auth diferida pro Railway (password único + cookie HttpOnly), testes pytest mínimos (parser, router, cálculos), structlog + tabela `sync_runs`. |

## Estrutura do repo

```
claude_coach/
├── backend/
│   ├── pyproject.toml
│   ├── claude_coach/
│   │   ├── api/                  # rotas FastAPI
│   │   ├── domain/               # modelos Pydantic, serviços
│   │   ├── adapters/
│   │   │   ├── garmin.py         # wraps garth
│   │   │   ├── llm/              # router, providers, cache, logging
│   │   │   └── pdf_parser.py     # LLM-vision parser
│   │   ├── db/                   # SQLAlchemy models + sessão
│   │   ├── scheduler/            # APScheduler tasks (daily sync, weekly report)
│   │   └── config.py             # pydantic-settings
│   ├── alembic/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── routes/
│       ├── components/
│       ├── api/                  # cliente gerado do OpenAPI
│       └── lib/
├── data/                         # COMMITADO (exceto subpastas em .gitignore)
│   ├── plans/                    # planos parseados (.yaml + REVIEW.md)
│   ├── exercises/                # catálogo canônico (.yaml)
│   ├── reports/                  # relatórios semanais (.md)
│   ├── profile.yaml              # perfil estático do usuário
│   ├── metrics.db                # gitignored
│   ├── garmin_raw/               # gitignored, cache de payloads
│   └── garmin_tokens/            # gitignored, tokens garth
├── config/
│   └── llm_routing.yaml          # task_id → provider + model
├── docs/
│   └── architecture.md           # este arquivo
├── scripts/                      # one-shots: garmin_login.py, parse_pdf.py, seed_exercises.py
├── .env / .env.example
├── .gitignore
├── CLAUDE.md
├── Makefile                      # make dev, test, migrate, sync, parse, report
└── README.md
```

## Componentes

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend (Vite + React + TS + Tailwind + shadcn)                │
│  Routes: /, /plan, /session/new, /session/:id, /history,         │
│          /metrics, /reports, /settings                           │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ JSON (OpenAPI)
┌────────────────────────────────▼─────────────────────────────────┐
│  FastAPI                                                          │
│  routers: plans, workouts, sessions, metrics, briefing, reports,  │
│           profile, garmin                                         │
│                                                                   │
│  ┌──────────────┬──────────────┬──────────────┬───────────────┐  │
│  │ Domain svc   │ LLM Router   │ Garmin Adpt  │ PDF Parser    │  │
│  │ (Pydantic    │ (task_id →   │ (garth)      │ (LLM-vision   │  │
│  │  + business  │  provider)   │              │  + Pydantic)  │  │
│  │  rules)      │              │              │               │  │
│  └──────┬───────┴──────┬───────┴──────┬───────┴───────┬───────┘  │
│         │              │              │               │           │
│         │              │              │               │           │
│   ┌─────▼──────────────▼──────────────▼───────────────▼──────┐   │
│   │  SQLAlchemy / SQLite                                      │   │
│   │  Tables: daily_metrics, garmin_activities, sessions,      │   │
│   │          session_sets, insights, llm_calls, sync_runs,    │   │
│   │          tested_1rm, body_metrics                         │   │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │  APScheduler (in-process)                                  │  │
│   │  - daily_sync (7h)                                         │  │
│   │  - weekly_report (seg 8h)                                  │  │
│   └────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ External                    │
                  │ - Anthropic / OpenAI APIs   │
                  │ - Garmin Connect (garth)    │
                  │ - Resend (e-mail)           │
                  └─────────────────────────────┘
```

## Modelo de dados

### Markdown/YAML (commitado)

- `data/profile.yaml` — perfil estático:
  ```yaml
  name: Vitor Mafra
  birthdate: 1999-XX-XX
  sex: M
  height_cm: ...
  fc_max_source: tanaka  # ou "garmin", ou "tested"
  fc_max_bpm: 187        # calculado ou inserido
  training_days: [mon, tue, wed, thu, fri, sun]  # rough schedule
  ```
- `data/plans/<plan-slug>/plan.yaml` — plano parseado, contendo `Plan { name, level, week: { weekday: WorkoutTemplate | RunTemplate } }`. Versionado.
- `data/plans/<plan-slug>/REVIEW.md` — output do parser pra revisão humana (exercícios novos, baixa confiança).
- `data/plans/<plan-slug>/raw/page_*.png` — cache de imagens (gitignored).
- `data/exercises/<exercise_id>.yaml` — `{ id, name, aliases[], muscle_group, equipment, video_url? }`.
- `data/reports/<year>/<week>.md` — relatório semanal versionado.

### SQLite (`data/metrics.db`)

| Tabela | Conteúdo |
|--------|----------|
| `daily_metrics` | `date PK, sleep_score, sleep_duration_min, body_battery_start, body_battery_end, stress_avg, weight_kg, hrv_avg, training_readiness, valid_as_of_timestamp, raw_payload JSON` |
| `garmin_activities` | `activity_id PK, date, sport_type, duration_s, distance_km, hr_avg, hr_max, training_effect_aerobic, training_effect_anaerobic, raw_payload JSON` |
| `body_metrics` | `id PK, date, weight_kg, body_fat_pct, lean_mass_kg, source (manual/garmin)` |
| `sessions` | `id PK, plan_slug, workout_template_id, date, status (planned/done/skipped), garmin_activity_id?, note, started_at, finished_at` |
| `session_sets` | `id PK, session_id FK, block_idx, exercise_id, set_idx, planned_reps, actual_reps, actual_weight_kg, is_warmup, is_dropset_continuation, note?` |
| `tested_1rm` | `id PK, exercise_id, date, weight_kg, reps_done, estimated_1rm (Epley), source (test/derived)` |
| `insights` | `id PK, type (briefing/weekly_report), generated_at, week_start?, week_end?, content_md, llm_provider, llm_model, input_context_hash` |
| `llm_calls` | `id PK, task_id, provider, model, input_tokens, output_tokens, cost_usd_estimate, duration_ms, success, error?, created_at` |
| `sync_runs` | `id PK, ran_at, source (garmin/manual), status, items_pulled, error?` |

## Fluxos principais

### 1. Onboarding (uma vez)
1. Wizard pergunta nome, nascimento, sexo, altura. Tenta puxar `maxHR` do Garmin (via garth). Fallback Tanaka.
2. Escreve `data/profile.yaml`.
3. Pede pra importar primeiro PDF.

### 2. Import de PDF
1. User faz upload (ou drop em `data/plans/raw/`).
2. Parser converte PDF → imagens página a página (cache em `data/plans/<slug>/raw/`).
3. LLM-vision (Claude Sonnet 4.6) recebe imagens + schema Pydantic alvo, retorna estrutura.
4. Parser faz exercise matching contra catálogo: confiança ≥ 0.9 auto, 0.6-0.9 pendente, < 0.6 propõe criar novo.
5. Escreve `plan.yaml` + `REVIEW.md`.
6. User revisa REVIEW.md, confirma. Plano fica `active`.

### 3. Sync diário (cron 7h)
1. APScheduler chama `GarminAdapter.sync(date=yesterday)`.
2. Adapter pula activities, sleep, body battery, stress, HRV, etc. via `garth`.
3. UPSERT em `daily_metrics`, `garmin_activities`, `body_metrics`.
4. Auto-match activity↔session pendente.
5. Loga em `sync_runs`.

### 4. Registrar sessão de musculação (UI)
1. User abre `/session/new?date=today` — pré-popula com workout do dia segundo `plan.yaml`.
2. UI mostra blocos. User toca exercício → set 1 (peso + reps) → carga é replicada nos demais sets automaticamente.
3. User ajusta sets individuais e adiciona nota se quiser.
4. POST `/sessions` salva `sessions` + `session_sets`.
5. Background: estima 1RM via Epley pro melhor set, grava em `tested_1rm` com `source=derived`.

### 5. Briefing pré-treino (on-demand)
1. User toca botão "vou treinar agora" em `/`.
2. Backend pull on-demand do Garmin (refresh body battery, sleep do dia).
3. Backend monta contexto: workout do dia + últimas 2-3 sessões de cada exercício desse workout + métricas Garmin de hoje + notas livres dos últimos treinos relacionados.
4. LLM Router (`task_id=briefing`) → Claude Haiku ou Sonnet com prompt.
5. Resposta em markdown renderizado na UI. Persistido em `insights` com `type=briefing`.

### 6. Relatório semanal (cron seg 8h)
1. APScheduler chama `WeeklyReportService.generate(week_end=last_sunday)`.
2. Coleta: todas sessões da semana, todas activities, daily_metrics, comparações com semana anterior, progressões de carga por exercício.
3. LLM Router (`task_id=weekly_report`) → Claude Sonnet, prompt longo com contexto estruturado.
4. Salva em `insights` + `data/reports/<year>/<week>.md`.
5. Envia via Resend pro e-mail configurado.

## Camada de abstração de LLM

```
backend/claude_coach/adapters/llm/
├── __init__.py
├── base.py          # Protocol: complete(), complete_structured(), complete_with_vision()
├── providers/
│   ├── claude.py
│   └── openai.py
├── router.py        # lê llm_routing.yaml, escolhe provider/model por task_id
├── cache.py         # hash de input → resposta (opt-in)
└── logging.py       # grava em llm_calls
```

`config/llm_routing.yaml` (exemplo):
```yaml
default: { provider: claude, model: claude-sonnet-4-6 }
tasks:
  pdf_parse:        { provider: claude, model: claude-sonnet-4-6, vision: true, max_tokens: 8000 }
  briefing:         { provider: claude, model: claude-haiku-4-5, max_tokens: 1500 }
  weekly_report:    { provider: claude, model: claude-sonnet-4-6, max_tokens: 4000 }
  exercise_match:   { provider: openai, model: gpt-4o-mini, max_tokens: 500 }
```

## Tipos de bloco (extraídos do PDF Time Híbrido)

| Tipo | Semântica |
|------|-----------|
| `warmup` | Marca "feito/skip". Sem log de carga. |
| `meta_reps` | N sets × reps fixo, carga livre. Log set-a-set com carga única padrão (1º set replica). |
| `pyramid` | N sets com reps decrescentes (15-12-10-8), carga geralmente progride. Log set-a-set, cargas independentes. |
| `biset` | 2 exercícios alternados sem descanso. Logados como rounds (round 1 = ex1 + ex2; round 2 = ...). |
| `dropset` | Set inicial até falha + drops com peso reduzido. Log do set inicial + agregado dos drops + carga final. |
| `tabata` | HIIT 20s on / 10s off. Marca "feito" + RPE final opcional. |
| `interval_run` | Corrida: N×[distância|duração] @ zona FC. Vem do Garmin. |
| `continuous_run` | Corrida contínua em zona única. Vem do Garmin. |
| `fartlek` | Corrida com variações de pace. Vem do Garmin. |

## Roadmap detalhado

### Fase 1 — Esqueleto (objetivo: app rodando vazio)
- `backend/pyproject.toml` com FastAPI, SQLAlchemy, alembic, pydantic-settings, structlog, anthropic, openai, garth, resend, apscheduler.
- `frontend/package.json` com Vite, React, TS, Tailwind, shadcn-cli, TanStack Query/Router, Recharts.
- Alembic init + primeira migration (tabelas vazias mas schema definido).
- Makefile: `make dev`, `make test`, `make migrate`, `make sync`, `make parse`, `make report`.
- `.env.example` com todas as chaves.
- Hello-world: FastAPI responde `/health`, frontend chama, mostra na tela.

### Fase 2 — Perfil + PDF parser
- Onboarding wizard frontend (3-4 telas).
- `data/profile.yaml` schema + leitura no startup.
- `scripts/parse_pdf.py` CLI: `python scripts/parse_pdf.py path/to/plan.pdf`.
- LLM-vision parser com schema Pydantic strict.
- Catálogo seed em `data/exercises/` (~50 exercícios cobrindo o PDF do Time Híbrido).
- REVIEW.md generator + UI de confirmação.

### Fase 3 — Garmin sync
- `scripts/garmin_login.py` CLI interativo (MFA-aware).
- `GarminAdapter` com métodos `fetch_activities`, `fetch_sleep`, `fetch_body_battery`, `fetch_stress`, `fetch_weight`, `fetch_hrv`, `fetch_training_readiness`.
- Migration adicionando tabelas Garmin.
- Endpoint manual `POST /garmin/sync?date=X`.
- APScheduler job diário 7h.

### Fase 4 — Sessions
- UI `/session/new` com pré-popularização do workout do dia.
- Lógica do log set-a-set com pre-fill.
- Auto-match com activity Garmin (banner desfazível).
- Histórico em `/history`.

### Fase 5 — Briefing pré-treino
- Endpoint `POST /briefing/today` (on-demand).
- Builder de contexto (queries de últimas sessões + Garmin do dia).
- Prompt Claude.
- UI: botão "vou treinar agora" → modal/page com markdown render.

### Fase 6 — Relatório semanal
- `WeeklyReportService` com builder de contexto amplo.
- Prompt Claude Sonnet.
- Persistência híbrida (insights + arquivo markdown).
- Integração Resend pra envio.
- Job APScheduler segunda 8h.

### Fase 7 — Deploy Railway
- Auth simples (env var password + cookie HttpOnly).
- Dockerfile + railway.toml.
- PWA manifest + service worker.
- Migrar tokens Garmin pra secret no Railway.

## Decisões adiadas (resolver na própria fase)

- Provider LLM exato pra cada task: ajustar `llm_routing.yaml` na Fase 5/6 com dados reais de custo/latência/qualidade.
- Estética visual / paleta / layouts de tela: começa shadcn default, refina na Fase 4 quando UI tomar forma.
- Estratégia exata de prompt do briefing e do relatório: itera com exemplos reais a partir da Fase 5.
- Notificação push (PWA): considerar na Fase 7 se relatório por e-mail não for suficiente.
- Estratégia de re-import quando plano muda (mantém histórico de planos antigos pra correlacionar sessões antigas).
