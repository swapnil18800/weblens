# Implementation Summary — v7

This is a record of what changed in the v7 pass: pipeline foundations (LangGraph, parametric routing, semantic cache, history-in-generation), and a full rewrite of the evaluation framework.

For the architectural diagrams, see [`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) and [`../../docs/RAG-MODEL-PIPELINE.md`](../../docs/RAG-MODEL-PIPELINE.md). For evaluation philosophy + how-to, see [`../../docs/EVALUATION.md`](../../docs/EVALUATION.md). For per-run numbers, see [`improvement-summary.md`](improvement-summary.md).

---

## Why v7

Three architectural gaps and one evaluation gap made it impossible to stress-test the system:

1. **No agentic orchestration** — the pipeline was a 500-line `_pipeline_stream` coroutine in `app.py`. Hard to extend with reflection, retry, branching, or new agentic patterns.
2. **No parametric routing** — every "what is 12 squared?" forced a full ~25-second web pipeline.
3. **No semantic caching** — paraphrases (`"What is RRF?"` vs `"How does RRF work?"`) paid the full pipeline cost.
4. **Evaluation was narrow** — three regex/judge metrics on RAG-trivia and SEC-filing questions; no failure analysis; no domain breadth; sequential runner.

v7 closes all four.

---

## What landed

### A1 — LangGraph orchestration

| File | Change |
|---|---|
| `pipeline/graph.py` *(new, ~700 lines)* | Builds a `StateGraph` with 7 nodes and 3 conditional edges. Single source of truth for pipeline flow. |
| `pipeline/runtime.py` *(new)* | `RuntimeContext` dataclass (event queue, token tracker, timing) accessed via `contextvars.ContextVar`. Kept out of `GraphState` so state stays serializable — deliberately avoiding AlphaLens's callbacks-in-state anti-pattern. |
| `pipeline/token_tracker.py` *(new)* | Thread-safe LLM cost / token accumulator. Pattern borrowed from AlphaLens. |
| `app.py:_pipeline_stream` | Shrank from ~500 lines to ~40 — now a thin driver that runs the graph and forwards SSE events. The old `_PipelineState` enum and `_generate_subquery_task` helper are gone. |

**Design choice — node granularity.** The plan called for 12 separate node files. The actual implementation groups the linear `search → extract → chunk → retrieve → generate → synthesize` flow into one `search_pipeline` node, with separate nodes only for the routing decisions (`analyze`, `cache_lookup`, `cache_replay`, `parametric_answer`, `cache_insert`, `emit_done`). Reasoning: the orchestration value of LangGraph lives in the routing decisions ABOVE the linear flow, not in atomizing every linear stage. Splitting them would have been ~450 lines of mostly-empty boilerplate without changing any behavior. The linear stages remain in `pipeline/{search,extract,chunk,retrieve,generate}.py` exactly as they were.

**LangSmith tracing.** Auto-instruments when `LANGSMITH_TRACING=true`. Each node name (`analyze`, `cache_lookup`, …) becomes a span label. Eval runs tag traces with `eval/<mode>/<timestamp>` for filtering.

**Behavior preserved.** Every SSE event type is byte-identical to v6. The frontend was not changed.

### A2 — Parametric routing (analyze step)

| File | Change |
|---|---|
| `pipeline/analyze.py` *(new, replaces `decompose.py`)* | Single LLM call returns `{mode: parametric|search, sub_queries, answer, rationale}`. Heavy "default to search" bias in the system prompt; parametric few-shots limited to arithmetic, basic geography, classic literature, fundamental CS. |
| `pipeline/decompose.py` | Left in place as the legacy module — no longer imported by `app.py`. Can be deleted in a future cleanup. |

**Verified at runtime.** "What is 12 squared?" → `mode=parametric`, total ~2.5s, no search/extract events. "What is the current population of Brazil?" → `mode=search` despite being a fact the LLM may "know" — because population numbers drift.

### A3 — Semantic query cache

| File | Change |
|---|---|
| `pipeline/query_cache.py` *(new)* | pgvector ANN over MiniLM query embeddings. Hard 250ms timeout. Exact-hash fast path. |
| `db/schema.sql` | Added `query_cache` table + ivfflat index on the embedding column + index on `expires_at`. |
| `config.py` | Added `semantic_cache_enabled`, `semantic_cache_sim_threshold` (0.92), `semantic_cache_ttl_hours` (6), `semantic_cache_lookup_timeout_ms` (250). |

**Default-off** during dev (`SEMANTIC_CACHE_ENABLED=false`) so prompt iteration isn't poisoned by stale cached answers. Flip the env var to enable.

### A4 — History into generate

| File | Change |
|---|---|
| `pipeline/generate.py` | `generate_stream` and `synthesize_stream` now accept a `history` arg. Adds a bracketed "Recent conversation context (do NOT cite — only sources)" block to the user prompt when history is provided. |
| `pipeline/graph.py:node_search_pipeline` | Threads `state["history"]` into both. |

**Existing rewriter behavior preserved byte-for-byte.** This is purely additive — the LLM doing the final generation now sees the same prior turns the rewriter sees.

### B — Evaluation framework

| File | Change |
|---|---|
| `evals/run_eval.py` | Full rewrite. 5 core + 2 diagnostic metrics. Async-concurrent (default 4 pipelines + 8 judge calls). `--smoke` / `--full` / `--multiturn` / `--all`. `--trace on|off` toggles LangSmith for the run. `--judge deepseek|openai`. Multi-turn scenarios serial within a session, parallel across scenarios. |
| `evals/question_dataset/benchmark.json` *(new)* | 30 single-turn questions across 10 categories. Domain mix spans AI, sports, science, geopolitics, finance, culture, society, health, foundational. **No single domain >20% of the set.** |
| `evals/question_dataset/multiturn.json` *(new)* | 5 multi-turn scenarios (~12 turns): anaphora, refinement, topic-switch leakage, drill-down, citation followup. |
| `evals/benchmark.json` | Copy of the canonical benchmark at evals root for visibility. |
| `evals/question_dataset/legacy/` | Pre-v7 question files moved here for reference (`question_v1.txt`, `v1_smoke`, `v2`, `v6`, `v6_smoke`, `question_examples.json`, `question-examples-with-categories-1.txt`). |

**Output per run:** `evals/results/<UTC_TS>_<mode>/{per_question/, summary.json, report.md, failures.md, eval.log}`.

**`failures.md`** is the unique value-add over v6 — for the worst 5–10 questions it shows the question, which metrics dropped, the judge's reasoning, the retrieved URLs + key_fact hit/miss matrix, and an **auto-classified probable cause** (`retrieval_miss`, `hallucination`, `wrong_route`, `over_decomposition`, `under_decomposition`, `citation_theater`, `noisy_retrieval`, `refusal_failure`, `pipeline_error`, `low_quality`). The top of the file shows the failure-mode distribution across the run.

---

## Knobs introduced

| Env / setting | Default | What it controls |
|---|---|---|
| `SEMANTIC_CACHE_ENABLED` | `false` | Turn the query cache on |
| `SEMANTIC_CACHE_SIM_THRESHOLD` | `0.92` | Cosine threshold for a cache hit |
| `SEMANTIC_CACHE_TTL_HOURS` | `6` | TTL on cached answers |
| `SEMANTIC_CACHE_LOOKUP_TIMEOUT_MS` | `250` | Hard cap on cache lookup |
| `HISTORY_MAX_TURNS` | `4` | How many prior turns the rewriter + generator see |
| `HISTORY_MAX_CHARS` | `2000` | Char cap on history block |
| `LANGSMITH_TRACING` | `false` | Enable per-node tracing |
| `LANGSMITH_PROJECT` | `weblens` | Trace bucket |
| `WEBLENS_EVAL_JUDGE` | (auto) | Override judge provider via env (`--judge` CLI takes precedence) |
| `EVAL_RUN_ID`, `EVAL_MODE` | (set by harness) | Injected as LangSmith trace metadata |

---

## Files touched (summary)

| Category | Files |
|---|---|
| New | `pipeline/{graph, runtime, token_tracker, analyze, query_cache}.py`, `evals/question_dataset/{benchmark, multiturn}.json`, `evals/benchmark.json`, `docs/EVALUATION.md`, `evals/docs/{implementation-summary-v7, improvement-summary}.md` |
| Rewritten | `evals/run_eval.py`, `app.py:_pipeline_stream` |
| Modified | `pipeline/generate.py` (history arg), `db/schema.sql` (query_cache table), `db/setup.py` (verify new tables), `config.py` (new settings), `docs/{ARCHITECTURE, DIRECTORY-STRUCTURE, RAG-MODEL-PIPELINE}.md` (v7 sections prepended) |
| Moved | Pre-v7 question files → `evals/question_dataset/legacy/` |
| Untouched | All linear pipeline stages (`pipeline/{search, extract, chunk, retrieve, embed}.py`), DB session layer, frontend |

---

## Deviations from the plan

1. **Node granularity** — single `search_pipeline` node instead of 6 separate nodes for the linear stages. Reasoning above.
2. **RuntimeContext threading** — used a `contextvars.ContextVar` rather than passing via `RunnableConfig`. LangGraph's signature introspection wouldn't reliably inject the config dict with the lenient typing the rest of the codebase uses; `contextvars` are propagated automatically across asyncio tasks within the same `ainvoke`, which is exactly the semantics we need.
3. **Token tracking** — the `TokenTracker` infrastructure is wired but not yet called from the LLM client (the `llm/openai_client.py` wrapper would need a small change). Per-question `token_cost` snapshots therefore show zeros in v7 outputs. Cost tracking for the judge LLM was also not added — would need to consume the `usage` block from each judge response.

Both gaps are non-blocking for the metrics. Documented here so the next pass can close them.
