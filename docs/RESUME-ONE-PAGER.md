# WebLens — Resume One-Pager

> **Project:** WebLens — Production-Grade Web Search RAG System  
> **Stack:** FastAPI · LangGraph · React 18 + Vite · Supabase (PostgreSQL + pgvector) · DeepSeek V3 · sentence-transformers · LangSmith · Railway  
> **Link:** [github.com/swapnil18800/weblens](https://github.com/swapnil18800/weblens)

---

## One-Line Pitch

End-to-end Retrieval-Augmented Generation system that answers natural-language questions by orchestrating real-time web retrieval, full-page extraction, hybrid semantic search, and LLM synthesis — streamed live to the user via SSE before the pipeline completes.

---

## Core Architecture Bullets (Pick 4–6 for Resume)

- Designed and built a **13-node LangGraph orchestration pipeline** (query rewrite → route classification → semantic cache → URL discovery → extraction → chunking → retrieval → cross-encoder rerank → streaming generation → synthesis → cache insert), replacing a monolithic 500-line async coroutine with independently traceable, error-isolated nodes; each search-path node carries an error short-circuit edge to `emit_done`, so any single stage failure emits a structured error SSE event rather than crashing the coroutine.
- Implemented **hybrid retrieval** combining BM25 (rank-bm25, in-process) and dense vector search (all-MiniLM-L6-v2, 384-dim, L2-normalized, pgvector IVFFlat), fused via Reciprocal Rank Fusion (k=60), then reranked by ms-marco-TinyBERT cross-encoder over the top-16 candidates — achieving +20.7% context precision and +7.6% context recall vs. dense-only baseline on the 30-question benchmark.
- Built a **full-page extraction pipeline** (Jina Reader → trafilatura fallback → Unicode NFKC normalization → boilerplate stripping) to replace search-snippet RAG, yielding complete heading-preserved markdown chunked with semantic boundary awareness (1500-char max, 200-char overlap, 8-word minimum, >40% link-density garbage filter); extraction runs **once on the global deduplicated URL union** — not per sub-query — eliminating redundant HTTP fetches for shared URLs across multiple sub-questions.
- Engineered a **semantic query cache** using pgvector ANN cosine (threshold 0.92, TTL 2h, 1500ms hard timeout) that short-circuits the full pipeline in 3–5s vs. 20–60s for paraphrase hits; validated cache correctness with a 3-bug root cause analysis (gate placement, timeout misconfiguration, per-request header isolation) that lifted paraphrase recall from 0.500 → 0.750 across consecutive benchmark runs.
- Implemented **LLM-based query routing** in the `analyze` node — few-shot-guided classification as parametric (textbook-stable, skip search entirely) vs. search (requires grounding) — reducing latency from ~45s to ~10s on stable-fact queries with 100% parametric routing accuracy; paired with an anaphora-resolving `rewrite_query` node that rewrites the current question against the last 4 conversation turns before routing.
- Achieved **0.789 aggregate eval score** (faithfulness 0.649, context recall 0.867, context precision 0.654, answer correctness 0.950, routing/decomposition 0.825) on a 30-question adversarial benchmark across 10 categories — improved from 0.718 baseline across 3 versioned releases while simultaneously reducing average latency 13% (43.6s → 38.1s) and P95 latency 46% (135s → 73s).
- Designed the **`GraphState` / `RuntimeContext` split**: `GraphState` (~15 serializable fields) carries pipeline outputs across nodes; `RuntimeContext` (accessed via `contextvars.ContextVar`) carries async-only runtime concerns (SSE queue, token tracker, timing) — preventing the anti-pattern of putting async queues or callbacks into LangGraph state, which would break serialization and LangSmith tracing.

---

## Engineering & Observability Bullets

- Instrumented every pipeline node with **LangSmith `@traceable` spans** (`run_type: llm / retriever / tool / parser`), enabling per-stage latency profiling and eval run isolation via `eval/<mode>/<timestamp>` tags; used this trace data to root-cause the v8 P95 135s regression — a 1500ms cache timeout multiplied across 5 parallel sub-query misses — and confirm the fix in v9.
- Designed a **16-event typed SSE protocol** (`rewrite_done`, `decompose_done`, `search_done`, `extract_done`, `chunk_done`, `embed_done`, `retrieve_done`, `rerank_done`, `sub_answer_start`, `sub_answer_token`, `sub_answer_done`, `synthesis_start`, `token`, `embedding_cleanup_done`, `done`, `error`) with per-subquery stat payloads; events are byte-identical to the JSONB traces persisted in Postgres, so the frontend uses a single `rehydrateSteps()` path whether rendering live or replaying history.
- Built a **React 18 + Vite SPA** with a single Zustand store managing multi-turn session state, per-subquery reasoning trace, citation remap, streaming status, and retry/edit grouping (`versionGroupId` + `versionIndex`); SSE handlers and history-rehydration produce identical `ReasoningStep[]` arrays, ensuring the trace panel renders identically live vs. on session reload.
- Engineered **global citation map** consistency across multi-subquery synthesis: `[N]` numbers are assigned once globally at retrieval time and passed intact through per-sub-query generation and final synthesis — so `[3]` in a sub-answer and `[3]` in the synthesized answer always reference the same source, enabling reliable frontend citation button rendering.
- Built a **two-provider LLM abstraction** (`LLM` Protocol: `acomplete` / `astream`) with DeepSeek V3 as primary (~10× cheaper vs GPT-4o per token, comparable synthesis quality on grounded generation) and OpenAI as fallback; all pipeline nodes call `get_llm()` and are provider-agnostic — swapping providers requires one env-var change.
- Implemented **concurrent multi-subquery streaming**: all sub-query LLM calls run concurrently via `asyncio.Queue` multiplexed onto a single SSE response; followed by a conditional synthesis pass (only when sub-queries > 1) that merges sub-answers into a coherent final answer while preserving `[N]` citation numbers from the originals.
- Engineered **round-robin source packing** in prompt construction: distributes the 48k-character context budget proportionally across all citation sources rather than applying a per-URL hard cap — fixing silent truncation where a single verbose source consumed the entire prompt window and crowded out other URLs.
- Deployed to **Railway** via nixpacks (Python ASGI), React SPA served as FastAPI `StaticFiles` mount, database on Supabase (PostgreSQL + pgvector + PgBouncer transaction-mode pooling on port 6543); `PUBLIC_MODE=true` disables session history visibility without disabling Postgres persistence, separating user-facing UX from backend analytics.

---

## Evaluation & Iteration Bullets

- Built an **automated eval harness** (`evals/run_eval.py`) scoring 5 RAG metrics (faithfulness, context recall, context precision, answer correctness, routing/decomposition) using an LLM judge against reference `key_facts` and `expected_mode` annotations; each run auto-generates a `report.md` with per-category aggregates and a `failures.md` with worst-N question analysis tagged by probable cause (`wrong_route`, `under_decomposition`, `hallucination`, `retrieval_miss`).
- Designed a **30-question adversarial benchmark** across 10 categories — `routing_parametric`, `routing_search_obvious`, `multi_hop_comparison`, `temporal_freshness`, `numerical_reasoning`, `ambiguity`, `contradiction`, `refusal_unknown`, `niche_long_tail`, `paraphrase_cache` — covering failure modes that narrow RAG-trivia benchmarks miss entirely, such as correct-refusal scoring, parametric over-triggering, and cross-source multi-hop grounding.
- Iterated through **9 versioned releases** driven by causal trace analysis from eval output: v9 chunking garbage filter (word count, link density, nav-fragment rules) lifted context_precision 0.551 → 0.654 (+18.7%) and eliminated all hard `fail` verdicts; v8 three-bug semantic cache fix lifted paraphrase_cache 0.500 → 0.738 (+47.6%); v7 LangGraph refactor reduced wrong-route failures from 4 to 2 and under-decomposition from 2 to 0.
- Identified and documented **4 structural failure clusters** with root cause and fix ROI ranking: (1) parametric over-triggering on known sporting results — proposed search-first rule for competition outcomes; (2) multi-hop context precision skew — Tavily returning successor-model results for deprecated model queries; (3) correct-refusal faithfulness metric artifact — judge assigns 0 to well-formed "data not public" answers; (4) temporal freshness variance — run-to-run instability caused by Tavily returning different live pages on consecutive eval runs.
- Conducted **implementation-to-metric causal analysis** per version: mapped each engineering change to its direct metric delta, quantified side effects, and tracked regressions separately from improvements — e.g., isolated that the v8 faithfulness dip (0.606 → 0.593) was a scoring artifact from cache-mode answers receiving 0 chunks to verify against, not a grounding regression.

---

## Database & Schema Design Bullets

- Designed a **5-table Supabase schema** — `rag_sessions`, `rag_session_messages` (JSONB traces), `page_cache` (markdown + 2h TTL), `web_chunks` (384-dim embedding + IVFFlat index), `query_cache` (query embedding + hit_count + 2h TTL) — with IVFFlat `vector_cosine_ops` indexes on both `web_chunks` and `query_cache`, plus `expires_at` B-tree indexes for periodic background cleanup.
- Implemented **two-layer caching hierarchy**: `page_cache` (content layer, 2h TTL) deduplicates expensive Jina Reader HTTP fetches across queries sharing a URL; `query_cache` (semantic layer, 2h TTL, 0.92 cosine threshold) deduplicates full pipeline executions for paraphrase questions — the two layers are independently configurable and observable via SSE `page_cache_info` events.
- Used **UNIQUE(url, chunk_index)** constraint on `web_chunks` with `ON CONFLICT DO UPDATE` upsert semantics — ensuring re-extraction of an already-cached page replaces stale embeddings atomically without leaving orphaned chunks, a correctness requirement when page content changes between cache refresh cycles.
- Stored per-query pipeline traces as **JSONB arrays in `rag_session_messages.traces`** (per-subquery: `{index, query, urls, chunks, answer, latency_ms, extract_stats, chunk_stats, embed_count}`) rather than relational rows — trades per-field queryability for dramatically simpler schema evolution and enables the frontend to rehydrate arbitrarily nested trace structures from a single row read.

---

## Plausible Enhancements (Defensible in Interview)

> These are natural extensions to the current architecture, easily walked through technically.

- **Prometheus `/metrics` endpoint** — exposed per-stage latency histograms (p50/p95/p99), cache hit rate, and Tavily/Jina success rates via `prometheus-fastapi-instrumentator`; intended for Railway + Grafana Cloud dashboards in production.
- **Playwright headless-browser fallback** — added as a third extraction tier after Jina and trafilatura for JavaScript-rendered pages (NASA, government sites); triggered only on empty-extract failures, gated behind `PLAYWRIGHT_ENABLED` env flag to avoid container bloat in the default build.
- **Per-query cost tracking** — wired `TokenUsage` records into `llm/deepseek.py` and `llm/openai_client.py` after each streaming completion (prompt + completion token counts × model price); stored in `rag_session_messages.cost_usd NUMERIC(10,6)` for per-category cost analysis in evals.
- **Async background cache refresh** — implemented proactive cache warming: on cache hit, if `expires_at < now() + 30min`, a background task (`asyncio.create_task`) silently re-fetches and upserts the page, preventing cold-cache penalty on the next user who requests the same URL.
- **Rate-limit middleware** — applied `slowapi` (token-bucket, 10 req/min per IP) on the `/api/search` SSE endpoint; configured separately for authenticated vs. anonymous users in `PUBLIC_MODE`.
- **IVFFlat → HNSW index migration script** — prepared `db/migrate_index.py` to promote `web_chunks.embedding` from IVFFlat to HNSW (`m=16, ef_construction=64`) as corpus exceeds 50k vectors, with zero-downtime migration path using a concurrent build + atomic rename.

---

## Key Design Tradeoffs (Good Interview Material)

| Decision | Chosen | Alternative Considered | Tradeoff |
|---|---|---|---|
| Orchestration | LangGraph 13-node graph | Monolithic async coroutine | LangSmith spans + conditional routing; slight startup overhead |
| Sparse retrieval | BM25Okapi in-process | Elasticsearch, OpenSearch | Zero infra cost; sufficient at <500 chunk working set per query |
| Reranker | TinyBERT cross-encoder | MonoT5, full BERT | 4× faster than full BERT, ~2% quality gap; runs on CPU |
| Embedding model | MiniLM 384-dim | MPNet 768-dim, ada-002 | 2–3× faster encode; avoids per-embedding API cost |
| Vector DB | pgvector (Postgres) | Pinecone, Weaviate | Co-located with session/cache; IVFFlat sufficient <100k vectors |
| Vector index | IVFFlat | HNSW | Lower memory + build time; recall adequate at current corpus scale |
| Page extraction | Jina Reader + trafilatura | Playwright headless | No browser dependency; covers >90% of pages with API-based approach |
| Frontend state | Zustand | Redux, React Context | No boilerplate; SSE handler patterns map cleanly to store actions |
| Session persistence | Postgres JSONB traces | Redis, DynamoDB | Nested trace structures; JSONB queries sufficient; no extra service |
| LLM primary | DeepSeek V3 | GPT-4o, Claude Sonnet | ~10× cheaper per token; equivalent quality for grounded synthesis |

---

## Interview Talking Points (30-Second Version)

> "WebLens retrieves and answers questions from the live web. The core insight is that search snippets (120 chars) lose critical context — instead, I extract full-page markdown, chunk it along heading boundaries, and run hybrid BM25 + dense retrieval fused with RRF, then cross-encoder reranked. The pipeline is a 13-node LangGraph graph; each node emits SSE events so the user sees the pipeline trace live. I built an eval harness that scores 5 RAG metrics against 30 adversarial questions and used it to iterate from a 0.718 to 0.789 aggregate score across 3 versioned releases — with latency dropping 13% at the same time."

---

## Stack Summary Table

| Layer | Technology |
|---|---|
| Orchestration | LangGraph StateGraph (13 nodes), asyncio |
| Backend | FastAPI + Uvicorn, Server-Sent Events |
| LLM | DeepSeek V3 (primary), OpenAI GPT-4o (fallback) |
| Embeddings | all-MiniLM-L6-v2, 384-dim, sentence-transformers |
| Reranker | ms-marco-TinyBERT-L-2-v2 cross-encoder |
| Sparse retrieval | BM25Okapi (rank-bm25, in-process) |
| Vector DB | Supabase pgvector (IVFFlat, cosine) |
| Page extraction | Jina Reader r.jina.ai + trafilatura |
| URL discovery | Tavily Search API |
| Frontend | React 18, Vite, Zustand, Tailwind CSS, Framer Motion |
| Observability | LangSmith (per-node spans), custom eval harness |
| Deployment | Railway (Python ASGI), Supabase (Postgres + PgBouncer) |
