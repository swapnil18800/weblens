# WebLens

> A production-grade Web Search RAG playground — retrieves full-page content, runs hybrid semantic search, and streams grounded answers with citations in real time.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)
![React](https://img.shields.io/badge/React-18-61dafb)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## Overview

WebLens answers natural-language questions by orchestrating real-time web retrieval, full-page extraction, hybrid semantic search, cross-encoder reranking, and LLM synthesis — all streamed to the user via SSE before the pipeline completes.

**Three non-negotiable design constraints drive the architecture:**

1. **Every query passes through an LLM.** No heuristic routing. The `analyze` node makes a reasoned routing decision — parametric vs. search — using few-shot classification with a strong search bias.
2. **Streaming must start in under 3 seconds.** (Either in reasoning trace or main answer) LangGraph + asyncio concurrency ensures `decompose_done` fires ~500ms in; first tokens within ~3s regardless of pipeline depth.
3. **Retrieval is global, not per-sub-query.** Extraction runs once on the deduplicated URL union — eliminating redundant fetches and ensuring citation number consistency.

---

## High-Level Architecture

![System Architecture](assets/architecture.png)

See the full detailed architecture with all layers and interactions in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI, Uvicorn, asyncio |
| **Orchestration** | LangGraph StateGraph (13 nodes, conditional routing) |
| **Database** | Supabase — PostgreSQL + pgvector |
| **Search** | Tavily API (URL discovery, parallel per sub-query) |
| **Extraction** | Jina Reader (primary), trafilatura (fallback) |
| **Embeddings** | sentence-transformers — all-MiniLM-L6-v2 (384-dim) |
| **Sparse Retrieval** | BM25Okapi (rank-bm25, in-process) |
| **Fusion** | Reciprocal Rank Fusion (RRF, k=60) |
| **Reranking** | Cross-Encoder — ms-marco-TinyBERT-L-2-v2 |
| **LLM** | DeepSeek V3 (primary) · OpenAI GPT (fallback) |
| **Observability** | LangSmith (per-node typed spans) |
| **Frontend** | React 18, Vite, TypeScript, Zustand, Tailwind CSS |
| **Streaming** | Server-Sent Events (SSE) |

---

## Observability & UI

### LangSmith Tracing

![LangSmith Single Query Trace](assets/langsmith/single_query.png)

<details>
<summary><b>View all LangSmith traces</b></summary>

**Single Query Traces:**
- ![](assets/langsmith/single_query_1st_half.png)
- ![](assets/langsmith/single_query_2nd_half.png)

**Multi-Hop Query Traces:**
- ![](assets/langsmith/multi_hop.png)
- ![](assets/langsmith/multi_hop_1st.png)
- ![](assets/langsmith/multi_hop_2nd.png)

**Parametric Answer Traces:**
- ![](assets/langsmith/parametric_answer.png)

</details>

### Frontend UI

![WebLens Home Page](assets/website-ss/home-page-fresh.png)

<details>
<summary><b>View all UI screenshots</b></summary>

**Core Features:**
- ![Reasoning Trace - Decomposed](assets/website-ss/reasoning-trace-decomposed.png)
- ![Reasoning Trace - Expanded View](assets/website-ss/reasoning-trace-expanded-view-per-question.png)
- ![Reasoning Trace - Subquery Steps](assets/website-ss/reasoning-trace-expanded-subquery-steps.png)

**Retrieved Content & Citations:**
- ![Retrieved Passages Preview](assets/website-ss/retrieved-passages-preview.png)
- ![Citations, Tags & Follow-ups](assets/website-ss/citations-tags-and-preview-and-followups.png)

**Evaluation Tab:**
- ![Evaluation Tab](assets/website-ss/eval_tab.png)

</details>

---

## Features

- **Parametric routing** — arithmetic, geography, and textbook-stable facts bypass search entirely (~2–5s vs 25–60s)
- **Semantic query cache** — pgvector ANN lookup at cosine ≥ 0.92 replays cached answers in 1–3s
- **Full-page extraction** — no reliance on search snippets; Jina Reader → trafilatura fallback
- **Heading-aware chunking** — markdown heading boundaries as semantic split points, 200-char overlap
- **Hybrid retrieval** — BM25 + dense cosine → RRF → TinyBERT cross-encoder (top-8)
- **Concurrent streaming** — all sub-query LLM calls stream simultaneously via `asyncio.Queue`
- **Global citation map** — `[N]` numbers assigned once, preserved through synthesis
- **Session persistence** — JSONB traces enable byte-identical reasoning trace replay on session reload
- **LangSmith observability** — per-node spans with typed `run_type` (`llm` / `retriever` / `tool`)
- **Evaluation harness** — 30-question benchmark, 5 core metrics, LLM-as-judge, auto `failures.md`

---

## RAG Pipeline

![RAG Pipeline Overview](assets/langgraph_rag_pipeline.png)

See the stage-by-stage breakdown with detailed explanations in [RAG-MODEL-PIPELINE.md](docs/RAG-MODEL-PIPELINE.md).

---

## Retrieval Architecture

**Why three signals?**

| Signal | Strength | Weakness |
|---|---|---|
| BM25 (sparse) | Entity names, ticker symbols, exact technical terms | Fails on paraphrases and semantic equivalents |
| Dense (MiniLM) | Semantic similarity, paraphrased questions | Underperforms on entity-dense queries |
| Cross-encoder (TinyBERT) | Token-level joint attention, high precision | Too slow as a primary retriever (O(corpus) passes) |

---

## Latency Breakdown

```mermaid
gantt
    title Typical Request Timeline (single sub-query, warm page cache)
    dateFormat X
    axisFormat %ss

    section Pre-Pipeline
    Rewrite + Analyze      :0, 900
    Cache Lookup           :900, 1100

    section Search Pipeline
    Tavily Search          :1100, 2300
    Page Extraction        :2300, 2400
    Chunk + Embed          :2400, 2900
    BM25 + RRF + Rerank    :2900, 3200

    section Generation
    LLM Streaming (perceived) :3200, 7200
```

| Stage | Warm (cache hit) | Cold (full path) | Notes |
|---|---|---|---|
| Rewrite + Analyze | 300–600ms | 400–900ms | 1–2 LLM calls |
| Cache lookup | 50–200ms | 50–200ms | 1500ms hard timeout |
| Tavily search | — | 400–1200ms | Parallel per sub-query |
| Page extraction | ~50ms | 500–2500ms | Cache hit vs Jina cold fetch |
| Chunk + Embed | 200–400ms | 200–500ms | MiniLM batch, executor-backed |
| BM25 + RRF + Rerank | 100–200ms | 100–300ms | In-process, TinyBERT over 16 candidates |
| Generate (streaming) | 1500–3500ms | 1500–4000ms | Perceived latency hidden by SSE |
| Synthesize | — | 1000–3000ms | Multi-sub-query only |
| **End-to-end** | **3–5s** | **5–60s** | Single SQ warm vs multi-hop cold |

> First tokens reach the user within ~3s on the search path. `decompose_done` fires within ~500ms.

---

## Evaluation Results

### Version-over-Version Progress

```mermaid
xychart-beta
    title "Aggregate Score by Version"
    x-axis [v1, v6, v7, v8, v9]
    y-axis "Score" 0 --> 1
    bar [0.735, 0.393, 0.718, 0.732, 0.789]
    line [0.735, 0.393, 0.718, 0.732, 0.789]
```

| Version | Questions | Aggregate | Pass | Partial | Fail | Key Change |
|---|---|---|---|---|---|---|
| v1 | 10 | 0.735 | 3 (30%) | 7 | 0 | RAG-trivia domain only |
| v6 | 15 | 0.393 | 1 (6%) | 6 | 8 | SEC/earnings domain, harder |
| v7 | 30 | 0.718 | 9 (30%) | 20 | 1 | New 5-metric harness, 10-domain mix |
| v8 | 30 | 0.732 | 12 (40%) | 18 | 0 | LangSmith spans, cache fixes |
| **v9** | **30** | **0.789** | **15 (50%)** | **15** | **0** | Node restructure, chunking quality |

### v9 Core Metrics

| Metric | Score | Verdict |
|---|---|---|
| Answer Correctness | 0.911 | Strong |
| Context Recall | 0.806 | Strong |
| Routing & Decomposition | 0.725 | Good |
| Faithfulness | 0.606 | Open issue |
| Context Precision | 0.542 | Open issue |
| **Aggregate** | **0.789** | |

### Per-Category Breakdown (v9)

| Category | Avg Score | Pass | Partial | Fail | Notes |
|---|---|---|---|---|---|
| `routing_parametric` | 1.000 | 4 | 0 | 0 | Perfect; arithmetic/geography bypasses search |
| `contradiction` | 0.871 | 1 | 1 | 0 | Handles conflicting evidence well |
| `temporal_freshness` | 0.765 | 2 | 2 | 0 | Struggles with phased regulatory events |
| `numerical_reasoning` | 0.764 | 1 | 2 | 0 | Good recall; precision gaps on financial data |
| `routing_search_obvious` | 0.744 | 1 | 2 | 0 | Correct routes; citation grounding gaps |
| `ambiguity` | 0.713 | 0 | 3 | 0 | Context precision weak on ambiguous queries |
| `refusal_unknown` | 0.562 | 0 | 2 | 0 | Correctly refuses; lacks explicit signaling |
| `niche_long_tail` | 0.500 | 0 | 2 | 0 | Correct answers; citation recall = 0 |
| `paraphrase_cache` | 0.500 | 0 | 2 | 0 | Cache disabled in standard eval runs |
| `multi_hop_comparison` | 0.590 | 0 | 4 | 1 | Weakest; under-decomposition + cross-model gaps |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Supabase account (PostgreSQL + pgvector)

### Environment Setup

```bash
git clone https://github.com/swapnil18800/weblens.git
cd weblens
```

Create a `.env` file:

```env
# Database
DATABASE_URL=postgresql://user:password@host:6543/dbname

# LLM (DeepSeek required; OpenAI optional fallback)
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key

# Search
TAVILY_API_KEY=your_tavily_key

# Optional
LOG_LEVEL=INFO
ENVIRONMENT=development
PORT=8000
SEMANTIC_CACHE_ENABLED=false
PUBLIC_MODE=false
```

### Backend

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt

# Initialize database (first time only)
python db/setup.py

# Start backend
uvicorn app:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

| Service | URL |
|---|---|
| Backend API | `http://localhost:8000` |
| Frontend SPA | `http://localhost:5174` |

---

## API Endpoints

### Search — `POST /api/search`

Initiates the RAG pipeline with a streaming SSE response.

```json
{
  "query": "What is RAG and how does it work?",
  "session_id": "optional-session-uuid",
  "max_results": 6,
  "top_k": 8
}
```

**SSE event sequence:**

| Event | Payload |
|---|---|
| `rewrite_done` | `original_query`, `rewritten_query`, `rewrote`, `latency_ms` |
| `decompose_done` | `sub_queries`, `rewritten_query`, `mode` |
| `page_cache_info` | `hits`, `misses`, `urls_from_cache` |
| `search_done` | `urls`, `per_subquery[]` |
| `extract_done` | `pages`, `failures`, `per_subquery[]` |
| `chunk_done` | `count`, `stats`, `per_subquery[]` |
| `embed_done` | `candidate_count`, `device`, `per_subquery[]` |
| `retrieve_done` | `total_chunks`, `sub_queries` |
| `rerank_done` | `per_subquery[].{top_k, max_score, min_score, explain}` |
| `sub_answer_start/token/done` | Per sub-query streaming tokens |
| `synthesis_start`, `token` | Final synthesis tokens (multi-SQ only) |
| `embedding_cleanup_done` | `freed_chunks`, `latency_ms` |
| `done` | `session_id`, `citations`, `latency_breakdown`, `followups` |
| `error` | `message`, `reason`, `failures[]` |

### Sessions

```
GET    /api/sessions?limit=50         List sessions
GET    /api/sessions/{session_id}     Get session with full trace
DELETE /api/sessions/{session_id}     Delete session
```

### Health

```
GET /api/health                       Environment info + version
```

---

## Database Schema

```mermaid
erDiagram
    rag_sessions ||--o{ rag_session_messages : "has"
    page_cache ||--o{ web_chunks : "url FK (logical)"
    query_cache }o--|| web_chunks : "embedding space"

    rag_sessions {
        TEXT session_id PK
        TEXT title
        TIMESTAMPTZ created_at
    }

    rag_session_messages {
        BIGSERIAL id PK
        TEXT session_id FK
        TEXT question
        TEXT answer
        JSONB citations
        JSONB urls
        JSONB chunks
        JSONB traces
        JSONB latency_breakdown
        INTEGER total_latency_ms
        TIMESTAMPTZ created_at
    }

    page_cache {
        TEXT url PK
        TEXT title
        TEXT markdown
        TIMESTAMPTZ fetched_at
        TIMESTAMPTZ expires_at
    }

    web_chunks {
        BIGSERIAL id PK
        TEXT url
        TEXT title
        INT chunk_index
        TEXT chunk_text
        TEXT heading
        VECTOR_384 embedding
        JSONB metadata
        TIMESTAMPTZ created_at
    }

    query_cache {
        TEXT query_hash PK
        TEXT query_text
        VECTOR_384 embedding
        TEXT answer_text
        JSONB citations
        INTEGER hit_count
        TIMESTAMPTZ expires_at
    }
```

> Authoritative DDL: [db/schema.sql](./db/schema.sql). Both `web_chunks` and `query_cache` carry IVFFlat indexes on `vector_cosine_ops`.

---

## Project Structure

```
web-search-rag/
│
├── app.py                    FastAPI entrypoint + SSE orchestrator
├── config.py                 Env-driven configuration (all settings)
├── requirements.txt
│
├── pipeline/                 RAG pipeline — one file per stage
│   ├── graph.py              LangGraph StateGraph: 13 nodes, conditional routing
│   ├── runtime.py            RuntimeContext (SSE queue, timing) via contextvars
│   ├── analyze.py            Rewrite + route classify + decompose (LLM)
│   ├── query_cache.py        Semantic cache: pgvector ANN over MiniLM embeddings
│   ├── search.py             Stage 1: Tavily URL discovery (parallel per sub-query)
│   ├── extract.py            Stage 2: Jina Reader + trafilatura + page_cache + normalize
│   ├── chunk.py              Stage 3: Heading-aware chunker + garbage filter
│   ├── embed.py              Stage 4: MiniLM batch encode (asyncio executor)
│   ├── retrieve.py           Stages 5–6: BM25 + dense → RRF → TinyBERT cross-encoder
│   ├── generate.py           Stages 7–8: Streaming generation + synthesis
│   ├── followups.py          Post-answer follow-up suggestions
│   └── title.py              Background session title upgrade
│
├── llm/                      Vendor-agnostic LLM protocol + implementations
│   ├── base.py               LLM protocol: acomplete() + astream()
│   ├── deepseek.py           DeepSeek V3 client (default)
│   └── openai_client.py      OpenAI client (fallback)
│
├── db/                       PostgreSQL access layer (asyncpg + Supabase)
│   ├── client.py             Async connection pool
│   ├── schema.sql            Authoritative DDL (all tables + indexes)
│   ├── setup.py              One-shot schema apply
│   └── sessions.py           save_message / get_session / list_sessions / delete_session
│
├── frontend/                 React 18 + Vite + TypeScript SPA
│   └── src/
│       ├── components/       All UI components
│       ├── state/
│       │   └── chatStore.ts  Single Zustand store: SSE handlers + rehydrateSteps
│       └── lib/
│           ├── sse.ts        SSE consumer (streamSearch)
│           └── types.ts      Shared TypeScript types
│
├── evals/                    Evaluation harness
│   ├── run_eval.py           CLI runner: 5 metrics, async concurrent, --smoke/--full
│   ├── question_dataset/
│   │   ├── benchmark.json    30-question canonical benchmark (10 categories)
│   │   └── multiturn.json    5 multi-turn scenarios
│   └── results/              Timestamped run artifacts
│
└── docs/                     Full documentation
    ├── ARCHITECTURE.md       System architecture (v9)
    ├── RAG-MODEL-PIPELINE.md Deep-dive retrieval pipeline
    ├── DEPLOYMENT.md         Railway, env vars, public mode
    └── DIRECTORY-STRUCTURE.md File-by-file responsibility map
```

---

## Deployment — Railway

```bash
# Install CLI
npm install -g @railway/cli

# Link repo and deploy
railway link
railway up

# Initialize database (one-time)
railway run python db/setup.py

# Monitor
railway logs --follow
```

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase pooled connection — port 6543, PgBouncer transaction mode |
| `DEEPSEEK_API_KEY` | Primary LLM |
| `TAVILY_API_KEY` | URL discovery |

### Optional Variables

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | LLM fallback |
| `ENVIRONMENT` | `development` | Set to `production` to disable debug mode |
| `PUBLIC_MODE` | `false` | `true` hides session list from users; DB writes still happen |
| `SEMANTIC_CACHE_ENABLED` | `false` | Enable pgvector semantic query cache |
| `LOG_LEVEL` | `INFO` | `DEBUG` for detailed traces |
| `PORT` | `8000` | Set automatically by Railway |

### Public Mode

| Mode | Sidebar shows sessions | session_id persistence | DB persistence |
|---|---|---|---|
| dev (`PUBLIC_MODE=false`) | Yes | `localStorage` | Always |
| prod (`PUBLIC_MODE=true`) | No — returns `[]` | In-memory only | Always |

### Cost Estimate

| Service | Monthly Cost | Notes |
|---|---|---|
| Railway (Python app) | $5–20 | Auto-scales |
| Supabase (pgvector) | $10–50 | Depends on data volume |
| DeepSeek API | $0.01–1 | ~0.01¢ per query |
| Tavily API | $0.20–5 | Free tier included |
| **Total** | **~$15–75** | Hobby to production |

---

## Design Decisions

| Decision | Chosen | Alternative | Tradeoff |
|---|---|---|---|
| Orchestration | LangGraph | Custom coroutine | LangSmith observability; conditional routing as graph edges |
| Search API | Tavily | Bing, SerpAPI | Structured results; simple auth; generous free tier |
| Page extraction | Jina Reader + trafilatura | Playwright headless | No browser dependency; ~800ms cold vs ~3s headless |
| Embedding | MiniLM 384-dim | MPNet 768-dim, OpenAI ada-002 | 2–3× faster; ~5% quality gap; no per-embedding API cost |
| Vector DB | pgvector (Postgres) | Pinecone, Qdrant | Co-located with session/cache; no extra service |
| Fusion | RRF k=60 | Score normalization | Robust to score distribution differences; no calibration |
| Reranker | TinyBERT cross-encoder | MonoT5, full BERT | 4× faster than full BERT; ~2% quality gap; runs on CPU |
| LLM primary | DeepSeek V3 | GPT-4o, Claude Sonnet | ~10× cheaper per token; equivalent synthesis quality |
| Frontend state | Zustand | Redux, React Context | No boilerplate; works naturally with SSE handler patterns |

---

## Known Limitations & Roadmap

| Area | Issue | Status |
|---|---|---|
| Context precision | 0.542 — off-topic chunks pass the reranker | Cross-encoder threshold tuning needed |
| Faithfulness | 0.606 — synthesis LLM occasionally adds uncited claims | Stricter "cite or omit" prompt instruction |
| Multi-hop comparison | Weakest category; under-decomposition on multi-entity queries | Reflection node planned (post-retrieve coverage check) |
| LLM cost tracking | `TokenTracker` wired but not called from LLM clients | Deferred |
| Jina Reader blocking | IP-based blocks fall back to trafilatura | By design |

**Planned improvements:**

- [ ] Reflection node: post-retrieve coverage check → re-decompose if gaps found
- [ ] BGE-reranker-v2-m3 upgrade (~5–8% precision improvement)
- [ ] Post-hoc hallucination verification pass (claim → citation validation)
- [ ] Streaming synthesis while sub-answers are still generating
- [ ] LLM cost attribution via `TokenTracker`

---

## Running Evaluations

```bash
# Smoke test (2 questions)
python evals/run_eval.py --set smoke

# Full benchmark (30 questions)
python evals/run_eval.py --set full

# Multi-turn scenarios
python evals/run_eval.py --multiturn
```

Results are saved to `evals/results/{timestamp}/` with:
- `summary.json` — aggregate metrics + category breakdown
- `report.md` — human-readable score table
- `failures.md` — worst-N questions with auto-classified probable cause
- `eval.log` — raw pipeline + judge output

---

## Credits

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) — ASGI backend
- [LangGraph](https://github.com/langchain-ai/langgraph) — pipeline orchestration
- [sentence-transformers](https://www.sbert.net/) — MiniLM embeddings
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — sparse retrieval
- [DeepSeek](https://www.deepseek.com/) — primary LLM
- [Tavily](https://tavily.com/) — URL discovery
- [Supabase](https://supabase.com/) — PostgreSQL + pgvector
- [LangSmith](https://smith.langchain.com/) — observability

---

## License

MIT
