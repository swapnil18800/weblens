# Web Search RAG — Implementation Summary

**Project:** `web-search-rag`  
**Version:** 2.0.0  
**Date:** 2026-05-07  
**Stack:** FastAPI · asyncpg · PostgreSQL (Supabase/PgBouncer) · sentence-transformers · DeepSeek LLM · Tavily Search

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Implementations](#2-implementations)
3. [What Works Well](#3-what-works-well)
4. [Evaluation Setup](#4-evaluation-setup)
5. [Eval Results](#5-eval-results)
6. [What Is Challenging](#6-what-is-challenging)
7. [Scope of Improvements](#7-scope-of-improvements)

---

## 1. Architecture Overview

```
User Query
    │
    ▼
[Query Decomposer]              pipeline/decompose.py
    │  LLM splits into ≤12 sub-queries (N entities × D dimensions)
    │  Fast path: <60 chars → skip LLM entirely
    │
    ▼  (parallel asyncio.gather per sub-query)
[URL Discovery]                 pipeline/search.py
    │  Tavily Search API — one search per sub-query, results deduplicated by URL
    │
    ▼
[Page Extraction]               pipeline/extract.py
    │  Jina Reader (primary) → trafilatura fallback → raw HTTP last resort
    │
    ▼
[Chunking]                      pipeline/chunk.py
    │  Markdown-aware, heading-anchored, overlap-aware chunks
    │
    ▼  (parallel asyncio.gather per sub-query)
[Hybrid Retrieval + Rerank]     pipeline/retrieve.py
    │  BM25 sparse + sentence-transformer dense → RRF fusion → cross-encoder rerank
    │  One retrieve() call per sub-query, all run concurrently
    │
    ▼  (sequential streaming, one sub-query at a time)
[Per-Sub-Query Generation]      pipeline/generate.py
    │  generate_stream() — streams tokens for each sub-query answer
    │  Emits sub_answer_start / sub_answer_token / sub_answer_done events
    │
    ▼  (only when len(sub_queries) > 1)
[Synthesis]                     pipeline/generate.py
    │  synthesize_stream() — merges N sub-answers into one cohesive response
    │  Markdown tables for comparisons, Key Takeaways section
    │
    ▼
[Session Persistence]           db/sessions.py
    │  Saves Q&A + URLs + chunks + citations + latency → PostgreSQL (fire-and-forget)
    │
    ▼
Frontend (index.html)
    History drawer + Tests panel (eval runs as buckets) + SSE consumer
```

**SSE event sequence emitted by `POST /api/search`:**

| Event | Payload | Notes |
|-------|---------|-------|
| `decompose_done` | `{sub_queries}` | Always first |
| `search_done` | `{urls, sub_queries, latency_ms}` | |
| `extract_done` | `{pages, latency_ms}` | |
| `chunk_done` | `{count, pages, latency_ms}` | |
| `retrieve_done` | `{total_chunks, sub_queries, latency_ms}` | |
| `sub_answer_start` | `{index, query, chunks, citations}` | Once per sub-query |
| `sub_answer_token` | `{index, text}` | Streamed tokens per sub-query |
| `sub_answer_done` | `{index, latency_ms}` | Once per sub-query |
| `synthesis_start` | `{}` | Only when >1 sub-query |
| `token` | `{text}` | Synthesis tokens (multi-sub-query only) |
| `done` | `{session_id, citations, total_latency_ms, latency_breakdown}` | |
| `error` | `{message}` | On any pipeline failure |

---

## 2. Implementations

### 2.1 Core Pipeline (pre-existing)

| Module | Role |
|--------|------|
| `pipeline/search.py` | Tavily-based URL discovery, returns ranked `SearchResult` objects |
| `pipeline/extract.py` | Async parallel page fetching via Jina Reader / trafilatura |
| `pipeline/chunk.py` | Markdown-aware chunking with heading context and overlap |
| `pipeline/embed.py` | Sentence-transformer embeddings (`all-MiniLM-L6-v2`), cached at startup |
| `pipeline/retrieve.py` | BM25 + dense cosine → RRF fusion → cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`) |
| `pipeline/generate.py` | `generate_stream()` for single sub-query answers; `synthesize_stream()` for multi-sub-answer synthesis |
| `llm/deepseek.py` | DeepSeek OpenAI-compatible client with async streaming |
| `db/client.py` | asyncpg connection pool, `statement_cache_size=0` for PgBouncer compatibility |

### 2.2 Query Decomposition — `pipeline/decompose.py`

Splits complex multi-entity questions into independent sub-queries before URL discovery using an **N entities × D dimensions** strategy.

- **Fast path:** queries < 60 characters skip the LLM call entirely (zero overhead)
- **LLM path:** DeepSeek returns a JSON array of up to **12 sub-queries** (`max_tokens=500`), each self-contained
- **N×D strategy:** for multi-entity comparisons, one sub-query is generated per entity × per dimension (e.g., revenue, margins, challenges), ensuring balanced coverage across both axes
- **Time range preservation:** multi-year ranges stay within each sub-query rather than fanning out per year
- **Technical detail injection:** algorithm-specific terms are included in sub-queries for technical topics

**Example decompositions:**
```
"Compare Apple and Microsoft operating margin in FY2024"
→ ["Apple operating margin FY2024 based on annual filing (10-K)",
   "Microsoft operating margin FY2024 based on annual filing (10-K)"]

"For NVIDIA: (a) FY2024 total revenue? (b) Primary risk factors?"
→ ["NVIDIA FY2024 total revenue",
   "NVIDIA primary risk factors disclosed in 10-K"]
```

### 2.3 Parallel URL Discovery and Retrieval

When `len(sub_queries) > 1`, both URL discovery and retrieval use `asyncio.gather()`:

- **Parallel search:** one Tavily call per sub-query, results deduplicated by URL
- **Parallel retrieval:** one `retrieve()` call per sub-query, all concurrent, then generation streams sequentially

This ensures balanced coverage — a "Compare A and B" question gets dedicated search budget for A and B rather than A-dominated results from a single search.

### 2.4 Per-Sub-Query Streaming + Synthesis — `pipeline/generate.py`

v2.0.0 introduced two-stage generation:

**Stage 1 — Per-sub-query answers (always):**
- `generate_stream(query, ranked_chunks)` streams tokens for each sub-query sequentially
- Each sub-query emits `sub_answer_start` → `sub_answer_token` × N → `sub_answer_done`
- Citations are built per sub-query; unique citations accumulate globally

**Stage 2 — Synthesis (only when >1 sub-query):**
- `synthesize_stream(original_query, sub_answers)` receives a list of `{query, answer, citations}` dicts
- Assembles a structured prompt with each sub-answer labelled, asks LLM to merge into one response
- Output includes markdown tables for side-by-side comparisons and a "## Key Takeaways" section
- `max_tokens=2000` (vs 1500 for single-query generation)
- Single sub-answer short-circuits: re-streams without an extra LLM call

### 2.5 Session Persistence — `db/sessions.py`

**Database schema** (`db/migrate_sessions.py`):

```sql
CREATE TABLE rag_sessions (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE rag_session_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES rag_sessions(session_id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT DEFAULT '',
    citations JSONB DEFAULT '[]',
    urls JSONB DEFAULT '[]',
    chunks JSONB DEFAULT '[]',
    latency_breakdown JSONB DEFAULT '{}',
    total_latency_ms INTEGER DEFAULT 0,
    sub_queries JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Tables are prefixed `rag_` to avoid collision with AlphaLens tables in the same Supabase instance.

**Key detail:** asyncpg with `statement_cache_size=0` (required for PgBouncer) returns JSONB columns as raw strings. The `_j()` helper in `db/sessions.py` handles explicit `json.loads()`.

### 2.6 Frontend Enhancements — `frontend/index.html`

**Session History Drawer (left slide-in):**
- Session ID stored in `localStorage`, sent in every search request
- Past Q&A items with question text, sub-queries, citations, and chunk restore

**Tests Panel (bottom slide-up) — v2 redesign:**

The v2 Tests panel was completely redesigned away from a static 4-bucket question runner. It is now a **live eval run browser**:

- **Level 1 — Run list:** fetches `GET /api/eval/results` and renders every `evals/results/<run_id>/` folder as a clickable row. Each row shows the run ID, M7 avg, and pass/partial/fail counts from `_summary.json`.
- **Level 2 — Question list:** clicking a run fetches `GET /api/eval/results/{runId}` and renders question rows in the left pane, identical in format to the Session History drawer: question text, category chip, M1, M7, verdict badge, latency, source count.
- **Right pane — Detail view:** clicking a question renders the full chat-UI-mirrored right pane: metrics bar (M1/M3/M7/verdict/latency/citations/chunks), sub-query chips, answer in markdown, URLs panel, citations with snippets, collapsible chunks, ground truth, key facts, and judge reasoning.
- Back button returns to the run list. No "run eval" buttons — eval runs are launched from the CLI only.

### 2.7 Evaluation Harness — `evals/run_eval.py`

Standalone CLI script (no internal imports — calls the running server via `httpx`).

**Question sets:**

| Flag | File | Questions | Focus |
|------|------|-----------|-------|
| `--smoke` | `question_v1_smoke.txt` | 2 | Fast sanity check (IR/RAG concepts) |
| `--full` | `question_v1.txt` | 10 | Full IR/RAG benchmark |
| `--v6-smoke` | `question_v6_smoke.txt` | 5 | Financial multi-entity smoke |
| `--v6` | `question_v6.txt` | 15 | Full financial/multi-entity benchmark |

**Metrics:**

| Metric | Name | Method |
|--------|------|--------|
| M1 | Factual Correctness | Fuzzy key-fact match against LLM answer (keyword overlap ≥60%, no LLM) |
| M3 | Retrieval Recall | Same fuzzy match against concatenated retrieved chunk text |
| M7 | LLM Judge Score | DeepSeek judge prompt: compare answer against ground truth, score 0.0–1.0 |

**Verdicts:** Pass ≥ 0.90 · Partial 0.50–0.89 · Fail < 0.50

**Output per run** (saved to `evals/results/<timestamp>_<mode>/`):
```
NN_<category>_<question>.json    per-question detail
_summary.json                    aggregate scores
_analysis.md                     human-readable table + decomposition log
```

---

## 3. What Works Well

### Retrieval Quality
- **Hybrid BM25 + dense retrieval with RRF** consistently outperforms either alone. BM25 handles exact terminology; dense handles paraphrase-heavy questions.
- **Cross-encoder reranking** reliably surfaces the most relevant chunks even when initial retrieval order is imperfect.
- **Parallel search per sub-query** materially improves URL coverage for comparison questions — each entity gets dedicated Tavily search budget. In v6, AMD + Intel + NVIDIA triple comparisons retrieved 24 chunks across 9 citations.

### Multi-Entity Decomposition
- Decomposition correctly identifies entities and dimensions for financial comparisons (e.g., splits Apple/Microsoft/Alphabet operating margins into 3 sub-queries automatically).
- Multi-year trend queries are decomposed per-year when needed (Meta Reality Labs FY2022/FY2023/FY2024 losses).
- Single-entity, short queries fast-path through without LLM overhead.

### Generation + Streaming
- Streamed token delivery gives responsive UX even for 30–75 second multi-entity queries.
- Synthesis correctly produces markdown tables for side-by-side comparisons and Key Takeaways sections.
- Inline `[N]` citations correctly attached to source-backed claims.

### Session Persistence
- Fire-and-forget `asyncio.create_task()` design never blocks the SSE stream.
- Session restore re-renders full answer, citations, and chunks without re-running the pipeline.

### Eval Harness
- Pure HTTP client design — no internal imports, robust to refactors.
- Three-metric design separates retrieval failures (M3) from generation failures (M7).
- v6 question set exercises decomposition, synthesis, strict grounding, and hallucination refusal in ways v1 never could.

---

## 4. Evaluation Setup

### v1 Question Sets (IR/RAG Concepts)

| File | Questions | Purpose |
|------|-----------|---------|
| `evals/question_v1_smoke.txt` | 2 | Sanity check |
| `evals/question_v1.txt` | 10 | Full IR/RAG benchmark |

Topics: RRF, BM25 vs TF-IDF, RAG architecture, dense vs sparse retrieval, cross-encoder reranking, pgvector, chunking strategies, sentence transformers, hybrid search, IVFFlat vs HNSW.

### v6 Question Sets (Financial / Multi-Entity)

| File | Questions | Categories |
|------|-----------|------------|
| `evals/question_v6_smoke.txt` | 5 | single_simple, cross_company_simple, strict_refusal, hybrid_web, multi_part |
| `evals/question_v6.txt` | 15 | year_scoped, cross_company_quant, multi_year_trend, transcript_grounding, strict_rag_hard, hybrid_dual, multi_hop_ratio, gap_fill_trigger, private_company_gap |

v6 categories are specifically designed to stress:
- **year_scoped:** must cite FY2024-only data, not forward guidance
- **cross_company_quant:** requires ranking multiple companies by financial metric from their 10-Ks
- **multi_year_trend:** must surface multi-year figures from separate filings
- **transcript_grounding:** requires earnings call transcript chunks, not just 10-K data
- **strict_rag_hard:** must answer only from a named document, refuse if not found
- **hybrid_dual:** blend of 10-K disclosures + recent news coverage
- **multi_hop_ratio:** compute derived metrics (R&D as % of revenue) from retrieved figures
- **gap_fill_trigger:** delivery guidance vs. disclosed FX headwinds — comparative reasoning
- **private_company_gap:** Stripe FY2024 revenue — no public filing, should identify data gap

---

## 5. Eval Results

### v1 Benchmark — IR/RAG Concepts

| Run | Timestamp | Avg M7 | Pass | Partial | Fail | Avg M1 | Avg M3 | Avg Latency |
|-----|-----------|--------|------|---------|------|--------|--------|-------------|
| Baseline | 20260507T162203Z | 0.735 | 3 | 7 | 0 | 0.810 | 0.803 | 25.6s |
| +Gen prompt v1 | 20260507T163245Z | 0.785 | 4 | 6 | 0 | 0.827 | 0.823 | 19.9s |
| +Gen prompt v2 | 20260507T163920Z | **0.825** | **5** | **5** | **0** | **0.903** | **0.843** | 20.4s |

**Final v1 scores by category (20260507T163920Z):**

| Category | Verdict | M7 | M1 | M3 |
|----------|---------|-----|-----|-----|
| simple_factual | **pass** | 1.00 | 1.00 | 0.80 |
| retrieval_comparison | **pass** | 0.95 | 1.00 | 1.00 |
| rag_architecture | partial | 0.65 | 0.80 | 0.60 |
| dense_vs_sparse | partial | 0.75 | 0.80 | 0.80 |
| cross_encoder | **pass** | 0.95 | 1.00 | 0.80 |
| pgvector | **pass** | 0.95 | 1.00 | 1.00 |
| chunking_strategies | partial | 0.65 | 0.80 | 0.80 |
| sentence_transformers | partial | 0.65 | 0.80 | 0.80 |
| hybrid_search | **pass** | 0.95 | 1.00 | 1.00 |
| ivfflat_hnsw | partial | 0.75 | 0.83 | 0.83 |

---

### v6 Smoke — Financial Multi-Entity (5 questions)

**Run:** `20260507T181518Z_v6_smoke`

```
Overall avg M7: 0.470  |  Pass: 1  Partial: 1  Fail: 3
Avg M1: 0.467  Avg M3: 0.583  Avg latency: 37.0s/Q
```

| # | Category | Question (truncated) | Verdict | M7 | M1 | M3 |
|---|----------|---------------------|---------|-----|-----|-----|
| 1 | single_simple | Apple total revenue FY2024 | **pass** | 0.90 | 0.33 | 0.67 |
| 2 | cross_company_simple | Apple vs Microsoft operating margin FY2024 | **fail** | 0.35 | 0.75 | 0.75 |
| 3 | strict_refusal | Apple FY2024 R&D by patent category | **fail** | 0.20 | 0.40 | 0.40 |
| 4 | hybrid_web | NVIDIA most recent quarterly revenue + data center strategy | **fail** | 0.25 | 0.25 | 0.50 |
| 5 | multi_part | NVIDIA: (a) FY2024 revenue (b) risk factors | partial | 0.65 | 0.60 | 0.60 |

**Key failure patterns:**
- **Q2 (cross_company):** Decomposition correctly split Apple/Microsoft, but synthesis failed to surface Microsoft's specific margin figure.
- **Q3 (strict_refusal):** Should have refused (R&D by patent category is not in SEC filings). Instead gave a partial answer about total R&D.
- **Q4 (hallucination):** Fabricated specific NVIDIA revenue figures ($68.1B, $215.938B) that don't match filings.

---

### v6 Full — Financial Multi-Entity (15 questions)

**Run:** `20260507T181845Z_v6`

```
Overall avg M7: 0.393  |  Pass: 1  Partial: 6  Fail: 8
Avg M1: 0.510  Avg M3: 0.687  Avg latency: 40.4s/Q
```

| # | Category | Question (truncated) | Verdict | M7 | M1 | M3 |
|---|----------|---------------------|---------|-----|-----|-----|
| 1 | year_scoped | Meta AI infrastructure CapEx FY2024 | **fail** | 0.20 | 0.75 | 0.75 |
| 2 | year_scoped | Tesla FSD progress FY2023 10-K only | partial | 0.50 | 0.50 | 0.75 |
| 3 | cross_company_quant | AMD / Intel / NVIDIA data center revenue FY2024 ranked | partial | 0.65 | 0.60 | 0.60 |
| 4 | cross_company_quant | Apple / Microsoft / Alphabet operating margins FY2024 table | **fail** | 0.20 | 0.80 | 0.80 |
| 5 | multi_year_trend | Meta Reality Labs operating loss FY2022–FY2024 | partial | 0.60 | 0.60 | 0.60 |
| 6 | multi_year_trend | Microsoft Intelligent Cloud revenue FY2022–FY2024 | partial | 0.65 | 0.60 | 0.80 |
| 7 | transcript_grounding | Microsoft Azure growth deceleration (earnings call) | **fail** | 0.00 | 0.00 | 0.80 |
| 8 | transcript_grounding | NVIDIA CEO on Blackwell production timeline | **fail** | 0.25 | 0.40 | 0.60 |
| 9 | strict_rag_hard | AWS operating income + margin per Amazon FY2024 10-K | **pass** | 0.85 | 0.80 | 0.80 |
| 10 | strict_rag_hard | Alphabet Other Bets revenue + loss per FY2024 10-K | **fail** | 0.20 | 0.40 | 1.00 |
| 11 | hybrid_dual | NVIDIA 10-K AI competition + 2025–2026 export control news | partial | 0.60 | 0.60 | 0.80 |
| 12 | hybrid_dual | Microsoft FY2024 10-K AI strategy + 2025 Copilot adoption | **fail** | 0.20 | 0.20 | 0.40 |
| 13 | multi_hop_ratio | Apple + Meta R&D as % of revenue FY2023–FY2024 | partial | 0.60 | 0.60 | 0.80 |
| 14 | gap_fill_trigger | Tesla delivery guidance vs. FX headwinds | **fail** | 0.20 | 0.40 | 0.40 |
| 15 | private_company_gap | Stripe FY2024 revenue | **fail** | 0.20 | 0.40 | 0.40 |

**Recurring failure modes in v6:**

1. **Year-scope leakage (Q1, Q2):** Responses mix FY2025 forward guidance with FY2024 actuals. The retrieval correctly surfaces the right documents (M3=0.75) but generation doesn't filter by year scope.

2. **Missing markdown tables (Q4):** The question explicitly asks for a comparison table. The synthesis prompt requests tables for comparisons, but the answer omitted the table format — likely because single-query generation was triggered instead of synthesis.

3. **Connection error → empty answer (Q7):** One question produced a connection error during search that yielded an empty answer, scoring M7=0.00. This is a reliability issue, not a quality issue.

4. **Transcript grounding not sourced (Q8):** The system retrieved web pages about Blackwell, not earnings call transcript chunks. The ground truth expected transcript-grounded citations (`TC-NVDA-*` markers). Tavily doesn't guarantee sourcing earnings call transcripts specifically.

5. **Hallucinated figures (Q10, Q15):** For Alphabet Other Bets (Q10), the answer fabricated a $4,444M operating loss. For Stripe (Q15), it fabricated $5.11B revenue from a non-credible source. These are the highest-risk failures.

6. **Citation marker format (Q12):** Ground truth expected specific citation marker formats (`[SEC-MSFT-*]`, `[NEWS:*]`); the response used different numbering, scoring M7=0.20 despite partially correct content.

---

## 6. What Is Challenging

### 6.1 Financial Year-Scope Discipline

The biggest v6 failure pattern: when FY2024 10-K data is retrieved alongside 2025/2026 news or guidance, the LLM conflates them. The system prompt does not currently instruct the model to filter by year scope when the question specifies a fiscal year. Retrieved chunks often contain forward guidance (in the 10-K outlook section) adjacent to the actuals being asked about.

### 6.2 Transcript Grounding

Earnings call transcript chunks are not consistently surfaced by Tavily search. The system has no transcript-specific search path — when a question requires transcript evidence, it may retrieve 10-K or news content instead. M3 can be high (relevant concepts found) while the evidence type is wrong.

### 6.3 Strict Refusal

Questions designed to test refusal (e.g., "R&D by patent category" which no 10-K reports) should produce clean refusals with source justification. The current generation prompt does not include explicit refusal instructions — it will attempt an answer even when the ground truth is "this data is not publicly disclosed."

### 6.4 Hallucination on Private/Niche Data

For private companies (Stripe) or sub-segment breakdowns not required by SEC disclosure, the LLM fabricates specific figures from low-credibility sources. The prompt currently doesn't instruct the model to express uncertainty proportional to source authority.

### 6.5 PgBouncer + asyncpg JSONB Handling

asyncpg with `statement_cache_size=0` (required for PgBouncer compatibility) returns JSONB columns as raw strings, not Python objects. Without explicit `json.loads()`, values were returned as their string-length integer. Fixed with the `_j()` helper in `db/sessions.py`.

### 6.6 Source Vocabulary vs. Ground Truth Vocabulary

Fuzzy key-fact matching (M1/M3) uses keyword overlap ≥60%. When ground truth uses "embedding and vector indexing" but sources consistently say "Indexing" and "encoding", the matcher misses despite factual correctness. This conflates vocabulary coverage with factual coverage, causing M1 to undercount in v1.

### 6.7 Generation Latency at Scale

End-to-end latency averages 37–40s for v6 questions (vs. ~20s for v1), driven by:
- More URLs extracted (multi-entity questions hit 4–9 pages)
- Page extraction time scales with page count (Jina Reader: up to 22s for 5-page batches)
- Sequential sub-query streaming means total time = Σ(sub-query generation times)

---

## 7. Scope of Improvements

### 7.1 Year-Scope and Refusal — Generation Prompt (High Priority)

| Improvement | Expected Impact | Effort |
|-------------|----------------|--------|
| **Year-scope instruction** — add explicit "if the question specifies a fiscal year, cite only figures from that year, not forward guidance" to the system prompt | Fix Q1/Q2 failures, +0.10–0.15 M7 on year_scoped | Low |
| **Refusal instruction** — add "if the requested breakdown is not present in retrieved sources, explicitly state this rather than approximating" | Fix strict_refusal category | Low |
| **Source authority signal** — include domain authority in the prompt ("prefer SEC EDGAR, official press releases; flag figures from non-primary sources") | Reduce hallucination on private data | Medium |

### 7.2 Transcript Sourcing

| Improvement | Expected Impact | Effort |
|-------------|----------------|--------|
| **Transcript-specific Tavily queries** — detect "earnings call", "CEO said", "management said" in sub-queries and route to transcript-specific search terms | Fix transcript_grounding category | Medium |
| **Pre-indexed transcript corpus** — crawl and chunk key earnings call transcripts into pgvector; route transcript questions to this corpus | Reliable transcript grounding | High |

### 7.3 Retrieval

| Improvement | Expected Impact | Effort |
|-------------|----------------|--------|
| **Larger top-K** — increase from top-8 to top-12 chunks for multi-year trend questions | More year-range coverage in context | Low |
| **Re-query on low M3** — if retrieval recall < threshold, auto-expand sub-queries | +0.05–0.10 M7 on weak categories | Medium |
| **Domain-filtered search** — for 10-K questions, bias Tavily toward `sec.gov`, `ir.<company>.com` | Better source quality, fewer hallucinations | Low |

### 7.4 Generation

| Improvement | Expected Impact | Effort |
|-------------|----------------|--------|
| **Structured output mode** — ask LLM to output JSON `{answer, key_points}` for cleaner M1 eval targeting | Cleaner eval, better UI | Medium |
| **Model upgrade** — switch from DeepSeek-chat to a longer-context model (DeepSeek-r1, GPT-4o) | +0.05–0.15 M7 across v6 | Low |
| **Iterative RAG** — parse answer for uncertain claims and trigger a second retrieval pass | Higher factual coverage | High |

### 7.5 Evaluation

| Improvement | Expected Impact | Effort |
|-------------|----------------|--------|
| **Semantic M1** — replace keyword-overlap with embedding cosine similarity for key-fact coverage | Fix vocabulary-mismatch false negatives in v1 | Medium |
| **Reliability retry** — catch connection errors and retry once before scoring M7=0.00 | Fix Q7 type failures | Low |
| **v6 ground truth calibration** — some v6 key facts may require updating as company data changes | Maintain eval validity | Ongoing |
| **Regression CI** — run smoke eval on every server restart | Catch regressions early | Low |

### 7.6 Infrastructure

| Improvement | Expected Impact | Effort |
|-------------|----------------|--------|
| **Extraction caching** — cache Jina Reader results keyed by URL + ETag to avoid re-fetching | Major latency reduction on repeated domains | Medium |
| **Async embedding** — move sentence-transformer inference off the event loop via `run_in_executor` | Eliminate event-loop blocking during batch embed | Low |
| **Connection pool to direct Postgres** — removing PgBouncer re-enables asyncpg prepared statement caching | ~20% DB query speedup | Low |

---

*Document generated: 2026-05-07 · web-search-rag v2.0.0*
