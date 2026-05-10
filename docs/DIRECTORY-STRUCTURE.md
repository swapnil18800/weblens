# Directory Structure

A map of the repo with a one-line purpose for every file. For higher-level
context see [ARCHITECTURE.md](./ARCHITECTURE.md). For the version-by-version
change history see [OVERALL-IMPROVEMENT-SUMMARY.md](./OVERALL-IMPROVEMENT-SUMMARY.md).

```
web-search-rag/
├── app.py                  ← FastAPI entrypoint + the SSE pipeline orchestrator
├── config.py               ← Env-driven config (API keys, model selection, ports, dev_mode)
├── requirements.txt        ← Python deps
├── runtime.txt             ← Python version pin (Railway / nixpacks)
├── nixpacks.toml           ← Build config for Railway
├── railway.toml            ← Railway service config
├── Procfile                ← Deployment process declaration
├── README.md               ← Project README
├── LICENSE
├── server.log, server_err.log, server_out.log   ← Runtime log files (gitignored)
│
├── db/                     ← Postgres / Supabase access layer
│   ├── __init__.py
│   ├── client.py           ← Async pool wrapper (asyncpg via PgBouncer)
│   ├── schema.sql          ← Authoritative DDL: page_cache, web_chunks, rag_sessions, rag_session_messages
│   ├── setup.py            ← One-shot: applies schema.sql to the configured DB
│   ├── migrate_sessions.py ← Migration helper for older session shapes
│   ├── check_tables.py     ← Quick "do my tables exist?" diagnostic
│   └── sessions.py         ← save_message / get_session / list_sessions / recent_turns / delete_session
│
├── pipeline/               ← The 8-stage RAG pipeline (each file = one stage or helper)
│   ├── __init__.py
│   ├── decompose.py        ← Stage 0: rewrite (history-aware) + decompose, both LLM-only, date-injected
│   ├── search.py           ← Stage 1: Tavily URL discovery
│   ├── extract.py          ← Stage 2: Jina Reader + trafilatura fallback + page_cache I/O
│   ├── chunk.py            ← Stage 3: heading-aware chunker; returns (chunks, global_stats, per_url_stats)
│   ├── embed.py            ← Stage 4: MiniLM embed + cross-encoder helpers (executor-backed)
│   ├── retrieve.py         ← Stages 5-6: BM25 + dense → RRF → cross-encoder → dedup + per-URL cap
│   ├── generate.py         ← Stages 7-8: streaming generation + synthesis; round-robin source packing
│   ├── followups.py        ← Post-answer: 3 suggested follow-up questions (LLM)
│   └── title.py            ← Background: LLM-upgrade the auto-derived session title
│
├── llm/                    ← Vendor-agnostic LLM abstraction
│   ├── __init__.py
│   ├── base.py             ← `LLM` protocol: acomplete(...) + astream(...)
│   ├── deepseek.py         ← DeepSeek V3 client (default)
│   └── openai_client.py    ← OpenAI client (fallback)
│
├── frontend/               ← Vite + React 18 + TypeScript SPA
│   ├── package.json        ← Frontend deps (react, zustand, framer-motion, lucide-react, tailwind, ...)
│   ├── tailwind.config.js  ← Theme: bg, accent, good (#10b981), warn (#f59e0b), bad (#f43f5e), info (#0ea5e9)
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx        ← React root + Router setup
│       ├── App.tsx         ← Top-level route definition (ChatPage, EvalPage)
│       │
│       ├── components/     ← All UI components
│       │   ├── Header.tsx              ← Top bar: logo, examples, eval link, github, about
│       │   ├── Logo.tsx                ← WebLens glyph
│       │   ├── Sidebar.tsx             ← Session list, drag-resizable, collapsible
│       │   ├── Hero.tsx                ← Empty-state landing copy + example prompts
│       │   ├── ExamplesDropdown.tsx    ← Header → "Examples" menu
│       │   ├── InfoPopover.tsx         ← About / info modal
│       │   ├── ChatInput.tsx           ← Composer (textarea + send / stop)
│       │   ├── ChatThread.tsx          ← Scrollable thread; new-question scroll snap; tail spacer
│       │   ├── ChatTurn.tsx            ← One Q+A: question bubble + trace + sub-answers + final + toolbar + followups
│       │   ├── Answer.tsx              ← Markdown answer renderer with inline [N] citation buttons
│       │   ├── ReasoningTrace.tsx      ← Collapsible per-turn pipeline trace (host for SubqueryTrace)
│       │   ├── SubqueryTrace.tsx       ← One sub-query's expandable steps panel
│       │   ├── PipelineStep.tsx        ← One step row + payload renderer (search urls, extract chips, rerank top-N)
│       │   ├── MiniTrackerRow.tsx      ← In-progress sub-answer mini status row
│       │   ├── CitationList.tsx        ← Citation list rendering helpers
│       │   ├── CitationPreview.tsx     ← Slide-in side panel: drill into a single citation
│       │   ├── RetrievedDataPanel.tsx  ← Slide-in side panel: full retrieved-chunks browser
│       │   ├── ChunkBody.tsx           ← Chunk-rendering helper used inside the data panel
│       │   └── eval/                   ← Eval-page sub-components
│       │       └── QuestionDetail.tsx
│       │
│       ├── pages/
│       │   ├── ChatPage.tsx            ← Main chat route: Header + Sidebar + (Hero | ChatThread) + ChatInput
│       │   └── EvalPage.tsx            ← Dev-only eval inspector (gated by /api/health.dev_mode)
│       │
│       ├── state/
│       │   └── chatStore.ts            ← Single Zustand store: turns[], session list, SSE handlers, rehydrateSteps
│       │
│       ├── lib/
│       │   ├── api.ts                  ← Fetch wrappers for /api/* endpoints
│       │   ├── sse.ts                  ← `streamSearch` SSE consumer
│       │   ├── types.ts                ← Shared TypeScript types (SseEvent, Turn, ReasoningStep, PerSubquery*, etc.)
│       │   ├── format.ts               ← Number / time / hostname helpers (chars, ms, shortHost)
│       │   ├── eval-adapter.ts         ← Adapts persisted eval JSON into Turn shape
│       │   └── useNow.ts               ← `useNow(ms)` hook that re-renders periodically (for live elapsed tags)
│       │
│       └── styles/
│           └── index.css               ← Tailwind base + a few @layer components (chip, surface, hairline, scroll-fat)
│
├── evals/                  ← Evaluation harness
│   ├── run_eval.py         ← CLI: run a question file end-to-end + score with judge LLM
│   ├── question_v1.txt     ← Eval question sets (smoke / full per version)
│   ├── question_v1_smoke.txt
│   ├── question_v2.txt
│   ├── question_v6.txt
│   ├── question_v6_smoke.txt
│   ├── v6_full_run.log     ← Latest full-run log
│   ├── v6_smoke_run.log    ← Latest smoke-run log
│   └── results/            ← Timestamped run artefacts, one folder per run
│       └── 20260507T*/
│
├── dev/                    ← Local dev convenience scripts
│   ├── run_backend.bat     ← Windows: start FastAPI on localhost:8765
│   └── run_frontend.bat    ← Windows: start Vite dev server on localhost:5174
│
└── docs/                   ← All project docs
    ├── ARCHITECTURE.md             ← Current system architecture (this version)
    ├── DIRECTORY-STRUCTURE.md      ← This file
    ├── OVERALL-IMPROVEMENT-SUMMARY.md  ← Consolidated v1 → v6 change history
    ├── DEPLOYMENT.md               ← Railway / env vars / nixpacks notes
    ├── INTERVIEW.md                ← Interview-prep deep dive
    ├── how-to-run.md               ← Local dev quickstart
    ├── launch.md                   ← Original launch checklist
    ├── implementation-summary-v1.md  ← v1 (initial) detailed summary
    ├── implementation-summary-v3.md  ← v3 (Vite/React rewrite + parallel SQ gen)
    ├── implementation-summary-v4.md  ← v4 (loading + nav, branding, sidebar)
    ├── implementation-summary-v5.md  ← v5 (sidebar polish, tag chips, persistence)
    ├── implementation-summary-v6.md  ← v6 (chat UX + trace honesty + decompose + persistence parity)
    └── commands.sh                 ← Useful one-off commands
```

---

## How the directories relate at runtime

```
                  ┌────────────────────────┐
                  │  frontend/ (Vite SPA)  │
                  └───────────┬────────────┘
                              │  HTTP + SSE
                              ▼
                  ┌────────────────────────┐
                  │   app.py (FastAPI)     │
                  └───────────┬────────────┘
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐          ┌──────────┐          ┌──────────┐
   │ pipeline│          │   llm/   │          │   db/    │
   └────┬────┘          └────┬─────┘          └────┬─────┘
        │                    │                     │
        │ Tavily / Jina      │ DeepSeek / OpenAI   │ Supabase / pgvector
        ▼                    ▼                     ▼
     external             external               external
```

- `app.py` is the only file that orchestrates — it calls into `pipeline/`,
  `llm/`, and `db/` and emits SSE.
- `pipeline/` modules are pure: they take inputs, return outputs, and emit
  log lines. They never write to the response stream directly.
- `llm/` modules are vendor adapters; pipeline modules call `get_llm()`,
  never the vendor SDK directly.
- `db/` modules wrap asyncpg. All public functions are fire-and-forget
  safe (log on failure, never raise).
- `frontend/src/state/chatStore.ts` is the single source of truth for the
  React UI; all components read from it via Zustand selectors.

---

## File-count snapshot (May 2026)

| Area | Files | Approx. lines |
|---|---|---|
| Backend (`app.py` + `pipeline/` + `db/` + `llm/` + `config.py`) | 18 | ~2,500 |
| Frontend (`src/**/*.{ts,tsx}` + `index.css`) | 27 | ~3,800 |
| SQL schema | 1 | 67 |
| Eval harness | 6 + run results | ~300 |
| Docs | 11 | — |

Backend stays small on purpose: each pipeline stage is one focused module.
Frontend is heavier mostly because `chatStore.ts` (~820 lines) carries every
SSE handler plus the rehydration path.
