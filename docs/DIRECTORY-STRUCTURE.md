# Directory Structure — WebLens

> Current as of v9 (2026-05-11). For architectural context see [ARCHITECTURE.md](./ARCHITECTURE.md). For version-by-version change history see the `implementation-summary-v*.md` series.

---

## Repository Map

```
web-search-rag/
│
├── app.py                          ← FastAPI entrypoint and SSE orchestrator
├── config.py                       ← Env-driven configuration (all settings in one place)
├── requirements.txt
├── runtime.txt                     ← Python version pin (Railway / nixpacks)
├── nixpacks.toml                   ← Railway build config
├── railway.toml                    ← Railway service + deploy config
├── Procfile                        ← Process declaration (uvicorn)
├── .env.example                    ← Reference env var template
│
├── pipeline/                       ← RAG pipeline (one file per stage + orchestration)
│   ├── graph.py                    ← LangGraph StateGraph: 13 nodes, conditional routing
│   ├── runtime.py                  ← RuntimeContext (SSE queue, token tracker, timing) via contextvars
│   ├── token_tracker.py            ← Thread-safe LLM cost/token accumulator
│   ├── analyze.py                  ← Rewrite + route classify + decompose (LLM)
│   ├── query_cache.py              ← Semantic cache: pgvector ANN over MiniLM query embeddings
│   ├── search.py                   ← Stage 1: Tavily URL discovery (parallel per sub-query)
│   ├── extract.py                  ← Stage 2: Jina Reader + trafilatura + page_cache I/O + normalization
│   ├── chunk.py                    ← Stage 3: Heading-aware markdown chunker + garbage filter
│   ├── embed.py                    ← Stage 4: MiniLM batch encode (asyncio executor)
│   ├── retrieve.py                 ← Stages 5–6: BM25 + dense → RRF → TinyBERT cross-encoder
│   ├── generate.py                 ← Stages 7–8: streaming generation + synthesis + history injection
│   ├── followups.py                ← Post-answer: 3 suggested follow-up questions (LLM)
│   └── title.py                    ← Background: LLM-upgrade the session title
│
├── llm/                            ← Vendor-agnostic LLM protocol + implementations
│   ├── base.py                     ← LLM protocol: acomplete() + astream()
│   ├── deepseek.py                 ← DeepSeek V3 client (default)
│   └── openai_client.py            ← OpenAI client (fallback)
│
├── db/                             ← PostgreSQL access layer (asyncpg + Supabase)
│   ├── client.py                   ← Async connection pool wrapper
│   ├── schema.sql                  ← Authoritative DDL (all tables + indexes)
│   ├── setup.py                    ← One-shot schema apply + stale-row cleanup
│   ├── sessions.py                 ← save_message / get_session / list_sessions / recent_turns / delete_session
│   ├── migrate_sessions.py         ← Migration helper for older session shapes
│   └── check_tables.py             ← Quick connectivity + table existence diagnostic
│
├── frontend/                       ← React 18 + Vite + TypeScript SPA
│   ├── package.json
│   ├── tailwind.config.js          ← Design tokens (bg, accent, good/warn/bad/info)
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx                ← React root + Router
│       ├── App.tsx                 ← Route definitions (ChatPage, EvalPage)
│       ├── components/             ← All UI components (see below)
│       ├── pages/
│       │   ├── ChatPage.tsx        ← Main chat route
│       │   └── EvalPage.tsx        ← Dev-only eval inspector
│       ├── state/
│       │   └── chatStore.ts        ← Single Zustand store: turns, SSE handlers, rehydrateSteps
│       ├── lib/
│       │   ├── api.ts              ← Fetch wrappers for /api/* endpoints
│       │   ├── sse.ts              ← streamSearch SSE consumer
│       │   ├── types.ts            ← Shared TypeScript types
│       │   ├── format.ts           ← Number / time / hostname formatters
│       │   ├── eval-adapter.ts     ← Adapts persisted eval JSON into Turn shape
│       │   └── useNow.ts           ← Re-rendering hook for live elapsed timers
│       └── styles/
│           └── index.css           ← Tailwind base + @layer components
│
├── evals/                          ← Evaluation harness and benchmark data
│   ├── run_eval.py                 ← CLI runner: 5 core metrics, async concurrent, --smoke/--full/--multiturn
│   ├── benchmark.json              ← Root copy of canonical 30-question benchmark
│   ├── cache_smoke.py              ← Standalone semantic cache smoke test
│   ├── smoke_conversation_history.py ← Multi-turn anaphora smoke test
│   ├── langsmith_smoke.py          ← LangSmith connectivity check (generates one trace)
│   ├── question_dataset/
│   │   ├── benchmark.json          ← Canonical 30-question single-turn benchmark (source of truth)
│   │   ├── multiturn.json          ← 5 multi-turn scenarios (~12 turns each)
│   │   └── legacy/                 ← Pre-v7 question files (v1, v2, v6 .txt sets)
│   └── results/                    ← Timestamped run artifacts (one dir per run)
│       └── <UTC_TS>_<mode>/
│           ├── per_question/       ← One JSON per question (metrics + judge + trace)
│           ├── summary.json        ← Aggregate metrics + category breakdown
│           ├── report.md           ← Human-readable score table
│           ├── failures.md         ← Worst-N questions with auto-classified probable cause
│           └── eval.log            ← Raw pipeline + judge output
│
├── dev/                            ← Local dev convenience scripts
│   ├── run_backend.bat             ← Start FastAPI on localhost:8765
│   └── run_frontend.bat            ← Start Vite dev server on localhost:5174
│
└── docs/                           ← All project documentation
    ├── ARCHITECTURE.md             ← System architecture (this version)
    ├── DIRECTORY-STRUCTURE.md      ← This file
    ├── RAG-MODEL-PIPELINE.md       ← Deep-dive retrieval pipeline
    ├── EVALUATION.md               ← Evaluation philosophy, metrics, how-to
    ├── DEPLOYMENT.md               ← Railway, env vars, public mode, ops runbook
    ├── evaluation-results-summary.md ← Consolidated eval results v1 → v9
    ├── implementation-summary-v1.md
    ├── implementation-summary-v3.md
    ├── implementation-summary-v4.md
    ├── implementation-summary-v5.md
    ├── implementation-summary-v6.md
    ├── implementation-summary-v7.md ← LangGraph, parametric routing, semantic cache, eval rewrite
    ├── implementation-summary-v8.md ← LangSmith spans, cache fixes, admin endpoints
    ├── implementation-summary-v9.md ← Node restructure, chunking, benchmark calibration, public mode
    └── commands.sh                 ← Useful one-off diagnostic commands
```

---

## Directory Responsibilities

### `pipeline/` — The retrieval and generation pipeline

Each file is one stage or one orchestration concern. The boundary rule: pipeline modules are pure — they take inputs, return outputs, and write log lines. They never write directly to the SSE response stream.

| File | Responsibility | Why separate |
|---|---|---|
| `graph.py` | LangGraph `StateGraph` definition; all 13 nodes; conditional routing edges; `@traceable` wrappers | Orchestration logic isolated from business logic; enables LangSmith observability without modifying stage files |
| `runtime.py` | `RuntimeContext` dataclass (SSE queue, token tracker, timing) accessed via `contextvars.ContextVar` | Keeps `GraphState` serializable; async context propagates automatically within `ainvoke` |
| `token_tracker.py` | Thread-safe LLM token/cost accumulator | Separate concern; used by graph, available for future cost dashboards |
| `analyze.py` | Query rewrite (history-aware) + route classification + decompose, all in one LLM call | Pre-pipeline decision; clean separation from search stages |
| `query_cache.py` | pgvector ANN lookup + insert; hash-based exact-match fast path | Cache is a cross-cutting concern that touches the DB, not a pipeline stage |
| `search.py` | Tavily API calls, parallel per sub-query; returns `(urls, url_to_subqueries)` | External I/O isolated; easy to swap search provider |
| `extract.py` | Jina Reader + trafilatura fallback + `page_cache` read/write + unicode normalization + boilerplate stripping | Full-page extraction + caching are tightly coupled; normalization is pre-storage not post |
| `chunk.py` | Heading-aware markdown splitter; garbage filter; returns `(chunks, global_stats, per_url_stats)` | Chunking strategy is independently tunable and testable |
| `embed.py` | MiniLM batch encode in `run_in_executor`; returns `(chunks_with_embeddings, device)` | Sync model inference isolated from async event loop |
| `retrieve.py` | BM25 → dense → RRF → TinyBERT cross-encoder → dedup + per-URL cap | All retrieval signals in one module; RRF fusion is an internal implementation detail |
| `generate.py` | Streaming LLM generation per sub-query (concurrent); synthesis; citation alignment | Generation logic separate from retrieval; prompt building and streaming in one place |
| `followups.py` | LLM-generated follow-up suggestions (post-answer, non-critical) | Background, non-blocking; decoupled from answer stream |
| `title.py` | LLM-upgraded session title (background, fire-and-forget) | Latency-irrelevant; should never block answer delivery |

**Scalability note:** adding a new retrieval signal (e.g., a re-ranking model, a second search provider) requires modifying one or two pipeline files. The LangGraph node structure means you can add a new stage node without touching any other node's logic.

---

### `llm/` — Vendor abstraction layer

The `LLM` protocol (`base.py`) defines two methods: `acomplete()` (single response) and `astream()` (async iterator of tokens). All pipeline modules call `get_llm()` from `config.py` — they never instantiate a vendor client directly.

**Why this matters operationally:** switching from DeepSeek to OpenAI (or adding a new provider) requires zero changes to `pipeline/`. The abstraction also enables per-request model selection when the fallback path is needed.

---

### `db/` — Data access layer

All public functions in `db/sessions.py` are fire-and-forget safe: they log on failure and never raise. This is an explicit design choice — a DB write failure should never interrupt an in-flight SSE stream.

| File | Responsibility |
|---|---|
| `client.py` | Async `asyncpg` connection pool; single pool instance shared across requests |
| `schema.sql` | Single source of truth for all DDL; includes indexes |
| `setup.py` | One-shot: applies schema.sql + runs expired-row cleanup |
| `sessions.py` | All CRUD for sessions, messages, eval sessions; `recent_turns()` for history injection |

**`schema.sql` as source of truth:** the schema is never generated from ORM models. This avoids schema drift and makes it auditable and portable. Any schema change requires updating `schema.sql` and a migration path.

---

### `frontend/src/` — React SPA

The frontend is organized by concern, not by page:

| Directory | Responsibility |
|---|---|
| `components/` | All UI components; no business logic; components read from `chatStore` |
| `pages/` | Route-level shells; thin wrappers that compose components |
| `state/chatStore.ts` | Single Zustand store; all SSE handlers; `rehydrateSteps` for session reload |
| `lib/` | Pure utility modules: API wrappers, SSE consumer, type definitions, formatters |
| `styles/` | Tailwind base + reusable @layer components (chip, surface, hairline) |

**`chatStore.ts` as the single state owner:** all SSE events from `sse.ts` are routed to `chatStore` actions. Components read via Zustand selectors. No component manages its own async state. This makes the state lifecycle fully predictable and testable independently of the UI.

**`rehydrateSteps`** reconstructs the same `ReasoningStep[]` shape from persisted JSONB traces that live SSE handlers build incrementally. This is the critical invariant that makes session reload produce an identical trace panel to the live stream.

---

### `evals/` — Evaluation harness

The eval harness is a production-grade CLI tool, not a notebook or throwaway script.

| File | Responsibility |
|---|---|
| `run_eval.py` | Full async concurrent runner; 5 core + 2 diagnostic metrics; LLM-as-judge; Phase 5 cleanup |
| `question_dataset/benchmark.json` | 30 canonical questions; 10 categories; `expected_mode` per question; `key_facts` per question |
| `question_dataset/multiturn.json` | 5 multi-turn scenarios for anaphora, refinement, topic-switch testing |
| `cache_smoke.py` | Standalone: proves cache miss → hit cycle with cleanup |
| `smoke_conversation_history.py` | Standalone: proves multi-turn anaphora resolution |
| `results/<ts>/failures.md` | Auto-classified failure analysis; the primary debugging surface |

**`benchmark.json` design principles:**
- No single domain exceeds 20% of questions
- Each question has `expected_mode` (parametric/search/either), `key_facts` (ground truth), `expected_count` (single/multi)
- `key_facts` are deliberately coarse — they test whether the answer addresses the question, not whether it uses exact wording

**Phase 5 cleanup:** after every eval run, `run_eval.py` deletes all `eval-*` sessions from the DB and removes any `query_cache` rows created during the run (tracked via snapshot/diff endpoints). The chat sidebar never shows eval artifacts.

---

## How the Directories Relate at Runtime

```
                  ┌─────────────────────────┐
                  │  frontend/ (Vite SPA)   │
                  └────────────┬────────────┘
                               │  HTTP + SSE
                               ▼
                  ┌─────────────────────────┐
                  │   app.py (FastAPI)      │
                  └────────────┬────────────┘
         ┌──────────────────────┼─────────────────────┐
         ▼                      ▼                      ▼
    ┌──────────┐          ┌──────────┐          ┌──────────┐
    │pipeline/ │          │  llm/    │          │   db/    │
    │graph.py  │          │ base.py  │          │client.py │
    └────┬─────┘          └────┬─────┘          └────┬─────┘
         │                     │                      │
    Tavily / Jina          DeepSeek /           Supabase +
    trafilatura             OpenAI              pgvector
```

- `app.py` is the only file that orchestrates across layers — it calls `pipeline/graph.py:run_pipeline()`, reads from `db/`, and emits SSE to the client.
- `pipeline/` modules never import from `db/` directly — `graph.py` passes DB handles as arguments or reads them from `RuntimeContext`.
- `llm/` modules are adapters — they own vendor SDK instantiation and streaming protocol; pipeline modules call `get_llm()`.
- `db/` modules wrap `asyncpg` — all are async, all failures are logged not raised.
- `frontend/src/state/chatStore.ts` is the single source of truth for UI state — components are pure view functions over Zustand selectors.

---

## File Count Snapshot (May 2026)

| Area | Files | Approx. lines |
|---|---|---|
| Backend (`app.py` + `pipeline/` + `db/` + `llm/` + `config.py`) | 20 | ~3,200 |
| Frontend (`src/**/*.{ts,tsx}` + `index.css`) | 28 | ~4,100 |
| SQL schema | 1 | ~90 |
| Eval harness | 8 + run results | ~600 |
| Docs | 16 | — |

Backend line count is deliberately low: each pipeline stage is one focused module, and the LangGraph graph replaces what was a 500-line procedural coroutine. `chatStore.ts` (~900 lines) is the heaviest single file — it carries every SSE handler plus the full session rehydration path.
