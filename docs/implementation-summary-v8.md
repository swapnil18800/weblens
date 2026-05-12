# Implementation Summary — v8

v8 fixes the operational issues surfaced after v7 traces landed in LangSmith, plus a few high-leverage cleanups. The pipeline architecture and the metric set are unchanged from v7 — this round is about making the existing work observable, well-behaved, and clean.

For *why* the v7 architecture exists at all, see [`implementation-summary-v6.md`](./implementation-summary-v6.md) and the v7 work captured in [`../evals/docs/implementation-summary-v7.md`](../evals/docs/implementation-summary-v7.md). For evaluation philosophy, see [`EVALUATION.md`](./EVALUATION.md).

---

## What changed in v8

### 1. LangSmith traces gain proper run-type spans (no more "everything is a chain")

**Problem.** v7 wired the whole pipeline through LangGraph; LangSmith captured the runs, but every span showed the chain icon. There was no way to tell at a glance which step was an LLM call, which was retrieval, which was a tool.

**Fix.** Each pipeline operation now goes through a small `@traceable`-wrapped helper in [`pipeline/graph.py`](../pipeline/graph.py) that pins the right `run_type`:

| Stage | Wrapper | LangSmith run_type |
|---|---|---|
| Analyze (route + decompose) | `_traced_analyze` | `llm` |
| Cache lookup (pgvector ANN) | `_traced_cache_lookup` | `retriever` |
| Web search (Tavily) | `_traced_discover_urls` | `tool` |
| Page extraction (Jina + trafilatura) | `_traced_extract_pages` | `tool` |
| Chunking | `_traced_chunk_pages` | `parser` |
| Hybrid retrieve (BM25 + dense + RRF + rerank) | `_traced_retrieve` | `retriever` |
| Generate sub-answer | `langsmith.trace(name=..., run_type="llm")` context manager (preserves token streaming) | `llm` |
| Synthesize final answer | same | `llm` |
| Cache insert | `_traced_cache_insert` | `tool` |

Streaming LLM calls don't use `@traceable` (it would block the SSE token flow); they use the `langsmith.trace()` context manager instead, which opens a span, lets the tokens stream through unchanged, and closes the span with the collected output via `run.add_outputs(...)`.

### 2. Semantic cache: now actually works end-to-end

Three bugs were in the way before v8:

1. **`query_cache.lookup` and `.insert` gated on `settings.semantic_cache_enabled`** — that override killed any per-request flag the eval harness or admin endpoints tried to set. Both functions now leave the gating decision entirely to the caller (the LangGraph node does it).
2. **`semantic_cache_lookup_timeout_ms` was 250ms** — too tight for a Supabase + PgBouncer + asyncpg round-trip (the first prepared-statement compile alone often takes ~300–500ms). Bumped to **1500ms**. A miss now costs at most 1.5s; a hit saves 20–60s.
3. **No per-request toggle.** The server now reads an `X-Semantic-Cache: on|off` header and threads it as `cache_enabled` through `GraphState`. The eval harness uses this to:
   - Send `cache=off` for every category except `paraphrase_cache` (no leakage between categories or eval runs).
   - Send `cache=on` only for `paraphrase_cache`, so `pc2` can hit `pc1`'s freshly-cached answer.

### 3. Eval cleanup phase

`evals/run_eval.py` gained a new Phase 5 that runs after the report files are written:

- Calls `DELETE /api/eval/sessions` to wipe all `eval-*` sessions from the DB. The chat sidebar stays clean and re-running an eval can't pick up history from the previous run.
- Calls `POST /api/admin/query_cache/delete` for each `paraphrase_cache` question's rewritten query to scrub the entries this run created.

### 4. Eval sessions stop polluting the chat sidebar

The chat sidebar now filters by `session_id NOT LIKE 'eval-%'`. New endpoint `GET /api/eval/sessions` returns the eval-prefixed ones for the Eval tab. New endpoint `DELETE /api/eval/sessions` wipes them all (used by the eval harness cleanup).

### 5. Cache TTLs tightened, stale rows cleaned up

- `page_cache` TTL default: **24h → 2h**.
- `query_cache` TTL default: **6h → 2h**.
- `db/setup.py` now runs a one-shot cleanup on each invocation: caps existing rows to the new TTL ceiling, then deletes anything already expired. The user's DB had ~1000 stale `page_cache` rows; after the cleanup, 820 were dropped.
- `app.py` starts a background task (`_cleanup_cache_periodic`) on startup that drops expired rows every 30 min so the tables can't grow unbounded.

### 6. New admin / cache smoke endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/eval/sessions` | List sessions with `eval-` prefix (for the Eval page sidebar) |
| `DELETE /api/eval/sessions` | Wipe all eval sessions |
| `DELETE /api/admin/query_cache` | Wipe the entire query cache (used to start a clean eval baseline) |
| `POST /api/admin/query_cache/delete` `{query: "..."}` | Delete one cache row by query text (used by per-question eval cleanup) |

### 7. Cache smoke test

[`evals/cache_smoke.py`](../evals/cache_smoke.py) is a standalone smoke test that:

1. Sends the same query twice with `X-Semantic-Cache: on`.
2. First call: expects `mode=search` (full pipeline).
3. Second call: expects `mode=cache` and <5s wall clock.
4. Cleans up the cache row it created.

Run with `python evals/cache_smoke.py --url http://localhost:8000`. Exits 0 on pass, 1 on fail.

### 8. Eval per-question JSON shape — frontend parity

The eval-results frontend (`QuestionDetail.tsx`) already imported `ReasoningTrace` and rendered it via the `evalQuestionToTurn` adapter — but the v7 JSON shape mismatched what the adapter expected. v8 adds legacy fields to each per-question record so the existing adapter renders the full trace UI for eval results, identical to chat:

- `q.timing.latency_breakdown`, `q.timing.total_latency_ms`, `q.timing.pipeline_s` — for stage chips and totals.
- `q.metrics.m1_factual_correctness` (aliased from `answer_correctness`), `m3_retrieval_recall` (from `context_recall`), `m7_judge_score` (from `aggregate`) — for the verdict chips.
- `q.judge_reasoning` (pulled from the faithfulness / precision / correctness judge's reasoning) — for the "Judge reasoning" section.
- `pipeline.urls` are kept as objects (`{url, title, snippet}`) so the trace's source-list rows render correctly.

---

## Files changed (v8)

### Modified
- `pipeline/graph.py` — `@traceable` wrappers; `ls_trace()` for streaming ops; `cache_enabled` field threaded through `GraphState`; `cache_lookup`/`cache_insert` honor per-request override.
- `pipeline/query_cache.py` — dropped redundant `settings.semantic_cache_enabled` gates; added `delete_by_query_text`, `delete_expired`, `clear_all`; small lookup/insert logging.
- `pipeline/runtime.py` — no functional change (already had what was needed).
- `app.py` — `X-Semantic-Cache` header parsing; `cache_override` parameter on `_pipeline_stream`; `/api/eval/sessions` (GET + DELETE); `/api/admin/query_cache` (DELETE + POST/delete by query); periodic cache-cleanup task in lifespan.
- `db/sessions.py` — `list_sessions` filters out `eval-*` by default; `list_eval_sessions` + `delete_eval_sessions` helpers.
- `db/schema.sql` — `page_cache` default TTL `24h → 2h`; `query_cache` default TTL `6h → 2h`.
- `db/setup.py` — one-shot cleanup query for existing rows.
- `config.py` — `semantic_cache_ttl_hours: 6 → 2`; `semantic_cache_lookup_timeout_ms: 250 → 1500`.
- `evals/run_eval.py` — `cache` parameter threaded; per-category cache policy (off everywhere except `paraphrase_cache`); Phase 5 cleanup; per-question JSON now emits `q.timing`, legacy `m1/m3/m7` aliases, `q.judge_reasoning`.

### New
- `evals/cache_smoke.py` — standalone cache smoke test.
- `docs/implementation-summary-v8.md` (this file).
- `evals/docs/improvement-summary-v8.md` — run-by-run numbers + interpretation.

### Untouched
- All linear pipeline stages (`pipeline/{search,extract,chunk,retrieve,embed,generate}.py`).
- Frontend (`evalQuestionToTurn` adapter already handled the v6/v7 JSON shape; v8 JSON adds the fields it expects).
- Benchmark data (`evals/question_dataset/{benchmark,multiturn}.json`).

---

## Verification

- `python evals/cache_smoke.py` — **PASS** (miss → 24.5s, hit → 3.3s, mode=cache on 2nd call).
- LangSmith traces under project `weblens` now display per-node spans with `llm` / `retriever` / `tool` / `parser` icons.
- `curl /api/sessions` → 0 `eval-*` leaks in the chat sidebar.
- `curl /api/eval/sessions` → only eval sessions (used by the Eval tab).
- `python db/setup.py` — 820 stale `page_cache` rows dropped on first run.
- Eval `--smoke` produces `summary.json`, `report.md`, `failures.md`; the Phase 5 cleanup deletes both eval sessions and `paraphrase_cache` rows.

---

## Knobs (current values)

| Setting | Default | Override |
|---|---|---|
| `SEMANTIC_CACHE_ENABLED` | `false` | per-request `X-Semantic-Cache: on/off` |
| `SEMANTIC_CACHE_SIM_THRESHOLD` | `0.92` | env |
| `SEMANTIC_CACHE_TTL_HOURS` | `2` | env |
| `SEMANTIC_CACHE_LOOKUP_TIMEOUT_MS` | `1500` | env |
| `LANGSMITH_TRACING` | `false` | per-request `X-Langsmith-Trace: true` |
| `HISTORY_MAX_TURNS` | `4` | env |
| `HISTORY_MAX_CHARS` | `2000` | env |

---

## Known gaps (deferred)

- **Pipeline LLM cost tracking still shows `cost_usd: 0`.** The `TokenTracker` is wired into the eval and into `RuntimeContext`, but no LLM client calls `tracker.record()` after a completion. A small change to `llm/openai_client.py` (consume the `usage` block from each response) would close this.
- **Judge cost tracking similarly $0.0000.** Same fix shape — consume `usage` from each judge response in `_judge_json`.
- **No per-question token streaming UI for parametric responses.** The replay chunks are 8 chars each; fine for short answers, but a parametric answer of 600 chars yields 75 sub_answer_token events which is more than necessary.

None of these affect the metrics. Documented for the next pass.
