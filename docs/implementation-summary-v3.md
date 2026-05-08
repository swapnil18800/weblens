# Implementation Summary — v3.0.0

## What changed

### Backend
- **Port**: 8765 (was 8000, now reserved for AlphaLens). Config default updated in `config.py`.
- **CORS**: Explicit allow-list (`localhost:5174`, `localhost:5175`) — removed wildcard.
- **`/api/health`**: Now returns `{ok, dev_mode, version: "3.0.0"}`. `dev_mode` gates the Eval link in the frontend.
- **Parallel sub-query generation**: Replaced sequential `for` loop with `asyncio.Queue` multiplexing. All N sub-query coroutines start concurrently; main loop drains the queue and yields `sub_answer_token`/`sub_answer_done` events interleaved across sub-queries.
- **`run_in_executor`**: `SentenceTransformer.encode` and `CrossEncoder.predict` moved off the event loop via `asyncio.get_running_loop().run_in_executor(None, ...)`. New helpers: `embed_texts_async`, `cross_encoder_score_async` in `pipeline/embed.py`.
- **GPU path**: `_pick_device()` wraps `torch.cuda.is_available()` in try/except — CPU fallback if torch is missing or CUDA unavailable. Device logged once on startup.
- **Session delete**: `DELETE /api/sessions/{session_id}` added. `db/sessions.py` gains `delete_session()`.
- **Enriched SSE payloads**: See schema additions section below.

### Pipeline
- `pipeline/decompose.py`: Hard cap removed; soft cap 24. Prompt reworded — no fixed count bias, no seeded examples with specific counts.
- `pipeline/retrieve.py`: `EMBED_POOL` 20→24, `CE_POOL` 12→16, `TOP_K` 5→10.
- `pipeline/generate.py`: `_SYSTEM_PROMPT` targets 150–250 words/sub-answer with table when comparative; `_SYNTHESIS_SYSTEM` targets 350–500 words + mandatory comparison table for ≥2 entities + Key Takeaways bullets. `max_tokens` 600→900 (sub) and 800→1600 (synthesis). Per-URL truncation 3000→4000 chars.
- `pipeline/embed.py`: GPU device detection, two new async wrappers.

### Frontend (full rewrite)
The monolithic `frontend/index.html` (~1700 lines) is replaced by a proper `frontend/` Vite + React 18 + TypeScript + Tailwind project. Key files:

| Path | Purpose |
|---|---|
| `frontend/src/state/chatStore.ts` | Zustand store; handles all 12 SSE event types; `stop()` marks turn `stopped` and ignores further events |
| `frontend/src/lib/sse.ts` | `streamSearch()` via `fetch + ReadableStream`; POST body; AbortController for stop |
| `frontend/src/components/ReasoningTrace.tsx` | Outer collapsible with DecomposeBlock, per-subquery SubqueryTrace, SynthesisBlock, PipelineTotals |
| `frontend/src/components/SubqueryTrace.tsx` | One block per sub-query; shows all 9 pipeline steps independently collapsible |
| `frontend/src/components/CitationPreview.tsx` | Right slide-in (Framer Motion); shows full `chunk_text` untruncated; "Open source" + "Go to source chunk" |
| `frontend/src/components/Answer.tsx` | `react-markdown` with custom `[N]` renderer; opens CitationPreview on citation click |
| `frontend/src/components/Hero.tsx` | Empty-state landing; disappears on first turn; v6 question chips |
| `frontend/src/components/Sidebar.tsx` | Collapsible rail (56px) ↔ expanded (280px); grouped by date; per-row trash with inline confirm |
| `frontend/src/components/StopBadge.tsx` | "Generation stopped by user — partial answer below." banner |
| `frontend/src/pages/EvalPage.tsx` | RunList + QuestionDetail; final answer top, all sections collapsible, no sparse two-pane |

### Theme
- 3-color palette: `bg: #0b0d10`, `surface: #14171b`, `accent: #3b82f6`.
- Metric chips: `good/#16a34a`, `warn/#d97706`, `bad/#dc2626`, `info/#0891b2`.
- Typography: Inter body, JetBrains Mono for URLs/scores/latencies.
- Animations: Framer Motion height-auto for trace collapse, x-slide for citation pane, stagger on hero chips. `useReducedMotion()` guard.

### Dev infra
- `dev/run_backend.bat`: `uvicorn app:app --reload --port 8765`
- `dev/run_frontend.bat`: `cd frontend && npm install && npm run dev`
- `vite.config.ts`: proxy `/api` → `:8765`, dev server on `:5174`.

---

## Schema / SSE event additions

New events:
- `embed_done` — `{candidate_count, dim, latency_ms, device}` — emitted once per retrieve batch.
- `rerank_done` — `{per_subquery: [{index, candidates, top_k, max_score, min_score, latency_ms}]}` — one summary across all sub-queries.

Enriched existing events:
- `decompose_done` adds `original_query`, `mode` (`fast_path` | `llm`), `latency_ms`.
- `search_done` adds `per_subquery: [{subquery, urls: [{url, title, snippet}], latency_ms}]`.
- `extract_done` adds `pages: [{url, title, char_count, from_cache, status}]`.
- `chunk_done` adds `per_page: [{url, chunk_count}]`.
- `sub_answer_start` adds `bm25_top: [{url, score}]`, `dense_top: [{url, score}]` alongside existing `chunks`/`urls`.

---

## Retrieval & decomposition tuning

| Parameter | Old | New | Rationale |
|---|---|---|---|
| `EMBED_POOL` | 20 | 24 | Marginally more candidates; encode time stays <40ms on CPU |
| `CE_POOL` | 12 | 16 | Better recall headroom for cross-encoder scoring |
| `TOP_K` | 5 | 10 | Main change: lets LLM draw from more evidence; recall improves without blow-up |
| Per-URL truncation | 3000 chars | 4000 chars | Avoids truncating mid-sentence on long SEC filings |
| Sub-answer max_tokens | 600 | 900 | Needed for 150–250 word target |
| Synthesis max_tokens | 800 | 1600 | Required for 350–500 words + table + takeaways |
| Decompose soft cap | 12 | 24 | Removes artificial constraint; complex questions can fan out properly |

---

## Smoke results (v6-smoke, 5 questions)

| Run | Timestamp | avg M7 | Pass | Partial | Fail | avg latency |
|---|---|---|---|---|---|---|
| Baseline (v2) | 20260507T181518Z | 0.470 | 1 | 1 | 3 | 37.0s |
| **v3.0.0** | **20260508T041306Z** | **0.580** | **1** | **3** | **1** | **52.8s** |

**Observations:**
- M7 improved +23% (0.470 → 0.580). Three questions moved from fail → partial.
- Latency increased ~43% (37s → 52.8s). Primary driver: `TOP_K` 5→10 doubles cross-encoder pairs; `extract` is now the bottleneck for complex questions (one question spent 92s extracting 24 pages). The parallel sub-query gen reduces the generation component, but extraction is I/O-bound and sequential.
- Q2 (cross-company operating margin): unexpectedly scored fail (0.15). The decomposition isolated "quarterly breakdown" sub-questions but the synthesis prompt didn't aggregate into a direct comparison table. This is a prompt-tuning opportunity.
- Q1 (Apple FY2024 revenue): pass (0.95) — simple factual question, correctly cited.
- Q3/Q4/Q5: partial (0.60 each) — partial credit on all complex questions; answers contain correct data but miss some specifics.

---

## Known limitations

1. **Latency regression**: Going from TOP_K=5 to TOP_K=10 and CE_POOL=12 to CE_POOL=16 added ~16s/question vs baseline. Extract is the real bottleneck (up to 92s for 24-page fetches). A per-URL extract timeout or page-count cap would help.
2. **Cross-company table synthesis**: When decomposition isolates entities into independent sub-queries, synthesis sometimes fails to produce the requested comparison table. The synthesis prompt asks for this but the LLM doesn't always comply when the sub-answers are structured differently.
3. **Eval port**: `evals/run_eval.py` defaults to `:8000`; the backend is now canonical on `:8765`. Use `--url http://localhost:8765` or keep the old instance alive on 8000 for eval runs. Out of scope to modify the eval script.
4. **No visual smoke**: Chrome extension wasn't connected during testing; frontend verified via TypeScript check (`tsc --noEmit` clean), Vite production build (clean), and API endpoint tests. UI was not visually verified end-to-end.
5. **Hero GPU**: Machine has no CUDA; `_pick_device()` returns `cpu` as expected. CUDA path not verified in smoke.

---

## Scope of improvements (future iterations)

- **Latency**: Per-URL extract concurrency cap + timeout; reduce CE_POOL to 12 for faster rerank.
- **Synthesis table compliance**: More explicit synthesis prompt with required markdown table header when multi-entity.
- **Year-scoped grounding**: `filing_year_lookup` for year-filtered retrieval; currently scoring near 0 on year-scoped questions.
- **Transcript corpus**: Pre-indexed earnings transcripts to improve `transcript_grounding` category (currently scores 0.125 avg).
- **Eval metrics expansion**: Precision, faithfulness, hallucination scoring beyond M1/M3/M7.
- **Production build**: `npm run build` → `frontend/dist` → FastAPI `StaticFiles` mount for single-process deployment.
- **Conversational memory**: Each query is independently answered per design; cross-turn context not planned.

---

## Tradeoff decisions

- **Port 8765**: AlphaLens owns 8000. The eval script defaults to 8000 — a deliberate mismatch; eval can use `--url http://localhost:8765`.
- **Three-color palette**: High information density with low visual noise; metric chips are the only color injection.
- **Vite over bundler**: Vite's HMR and tree-shaking produced a 498KB JS bundle (155KB gzipped) vs the unmaintainable 1700-line monolith.
- **No hard decompose cap**: Removed the `[:12]` slice so complex multi-entity × multi-year questions can fully decompose. The soft cap of 24 prevents runaway decomposition.
- **Async embed/rerank off-loop**: `run_in_executor` ensures CPU-bound model work doesn't block the asyncio event loop when N sub-queries run concurrently.
