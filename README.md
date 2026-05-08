# WebLens

> A portfolio-grade web-search RAG playground that retrieves full-page content and generates grounded answers with citations.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)
![License](https://img.shields.io/badge/License-MIT-orange)

## Overview

WebLens demonstrates a production-ready Retrieval-Augmented Generation (RAG) system focused on **answer accuracy through full-page extraction** rather than search snippets. It combines:

- **URL Discovery** via Tavily API
- **Full-Page Extraction** using Jina Reader with trafilatura fallback
- **Intelligent Chunking** with heading-aware splitting and overlap
- **Hybrid Search** combining BM25 (sparse) and dense embeddings via RRF
- **Cross-Encoder Reranking** for precision ranking
- **Streaming LLM Generation** with real-time citations
- **Session Management** with persistent chat history

## Architecture

```mermaid
graph TB
    A["📤 Query"] --> B["🔄 Query Decomposition<br/>LLM splits complex queries"]
    B --> C["🔍 URL Discovery<br/>Tavily API"]
    C --> D["📄 Full-Page Extraction<br/>Jina Reader + trafilatura"]
    D --> E["✂️ Intelligent Chunking<br/>Heading-aware + overlap"]
    E --> F["📊 Embedding Generation<br/>all-MiniLM-L6-v2"]
    F --> G["🔎 Hybrid Retrieval<br/>BM25 + Dense + RRF"]
    G --> H["🎯 Cross-Encoder Reranking<br/>ms-marco-TinyBERT-L-2-v2"]
    H --> I["💬 LLM Generation<br/>DeepSeek V3 Streaming"]
    I --> J["📌 Citation Synthesis<br/>Citation building"]
    J --> K["✅ Final Answer<br/>With citations"]
    
    D -.-> L["🗄️ Page Cache<br/>Supabase pgvector"]
    E -.-> L
    L -.-> G
```

## Tech Stack

| Component | Technology |
|-----------|-------------|
| **Backend** | FastAPI, Uvicorn |
| **Database** | Supabase (PostgreSQL + pgvector) |
| **Search** | Tavily API |
| **Extraction** | Jina Reader, trafilatura |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) |
| **Retrieval** | BM25, Reciprocal Rank Fusion (RRF) |
| **Reranking** | Cross-Encoder (ms-marco-TinyBERT-L-2-v2) |
| **LLM** | DeepSeek V3 (with OpenAI fallback) |
| **Frontend** | Vanilla HTML/CSS/JavaScript |
| **Streaming** | Server-Sent Events (SSE) |

## Features

- ✅ **Real-time Streaming** — SSE with granular pipeline events
- ✅ **Full-Page Context** — No reliance on search snippets
- ✅ **Intelligent Retrieval** — Hybrid search with RRF ranking
- ✅ **Citation Tracking** — Grounded answers with source attribution
- ✅ **Session Persistence** — Chat history with full traces
- ✅ **Multi-Query Support** — Automatic decomposition for complex questions
- ✅ **Evaluation Framework** — Built-in eval harness with smoke/full test sets
- ✅ **No Abstractions** — Direct, testable module architecture

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 16+ (for frontend)
- Supabase account (or PostgreSQL + pgvector)

### Environment Setup

1. Clone and navigate to the repo:
```bash
git clone https://github.com/swapnil18800/weblens.git
cd weblens
```

2. Create a `.env` file:
```env
# Database
DATABASE_URL=postgresql://user:password@host:6543/dbname

# LLM
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key

# Search
TAVILY_API_KEY=your_tavily_key

# Optional
LOG_LEVEL=INFO
ENVIRONMENT=development
PORT=8000
```

### Backend Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Initialize database (first time only)
python db/setup.py

# Start backend
uvicorn app:app --reload --port 8000
```

The backend will be available at `http://localhost:8000`.

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend runs on `http://localhost:5174`.

## API Endpoints

### Search
```
POST /api/search
```
Initiates RAG pipeline with streaming SSE response.

**Request:**
```json
{
  "query": "What is RAG and how does it work?",
  "session_id": "optional-session-uuid",
  "max_results": 6,
  "top_k": 8
}
```

**Response:** Server-Sent Events with pipeline events
- `decompose_done` — Query decomposition result
- `search_done` — URLs discovered
- `extract_done` — Pages extracted
- `chunk_done` — Content chunked
- `embed_done` — Embeddings generated
- `retrieve_done` — Candidates retrieved
- `rerank_done` — Reranking scores
- `sub_answer_*` — Per-query generation
- `token` — Answer tokens
- `done` — Final result with citations

### Sessions
```
GET  /api/sessions?limit=50          — List sessions
GET  /api/sessions/{session_id}      — Get session history
DELETE /api/sessions/{session_id}    — Delete session
```

### Health
```
GET /api/health                       — Health check with environment info
```

## Database Schema

### `page_cache`
Stores extracted web pages with 24h TTL:
```sql
CREATE TABLE page_cache (
  url TEXT PRIMARY KEY,
  title TEXT,
  markdown TEXT,
  fetched_at TIMESTAMP,
  expires_at TIMESTAMP
);
```

### `web_chunks`
Stores chunked content with embeddings:
```sql
CREATE TABLE web_chunks (
  id BIGSERIAL PRIMARY KEY,
  url TEXT NOT NULL,
  title TEXT,
  chunk_index INT,
  chunk_text TEXT,
  heading TEXT,
  embedding vector(384),
  metadata JSONB,
  created_at TIMESTAMP,
  UNIQUE(url, chunk_index)
);
```

### `chat_sessions`
Tracks conversation sessions:
```sql
CREATE TABLE chat_sessions (
  id UUID PRIMARY KEY,
  title TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

### `chat_messages`
Stores question-answer pairs with traces:
```sql
CREATE TABLE chat_messages (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID REFERENCES chat_sessions(id),
  question TEXT,
  answer TEXT,
  citations JSONB,
  urls JSONB,
  chunks JSONB,
  traces JSONB,
  latency_breakdown JSONB,
  total_latency_ms INT,
  created_at TIMESTAMP
);
```

## Deployment

### Railway

See [DEPLOYMENT.md](./docs/DEPLOYMENT.md) for Railway-specific setup.

Quick deploy:
```bash
railway link
railway up
```

### Environment Variables

Production requires:
- `DATABASE_URL` — Pooled connection string
- `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` — LLM provider
- `TAVILY_API_KEY` — URL discovery
- `ENVIRONMENT=production` — Production mode
- `PORT` — Server port (Railway sets this automatically)

## Evaluation

Run the evaluation suite:

```bash
# Smoke test (2 questions)
python evals/run_eval.py --set smoke

# Full eval (9 questions)
python evals/run_eval.py --set full
```

Results are saved to `evals/results/{timestamp}/`.

## Project Structure

```
weblens/
├── app.py                  # FastAPI entry point
├── config.py              # Pydantic settings
├── requirements.txt       # Python dependencies
│
├── db/                    # Database layer
│   ├── client.py         # Connection pool & queries
│   ├── sessions.py       # Chat session management
│   ├── setup.py          # Schema initialization
│   └── schema.sql        # Database schema
│
├── pipeline/             # RAG pipeline modules
│   ├── search.py         # Tavily URL discovery
│   ├── extract.py        # Jina Reader + trafilatura
│   ├── chunk.py          # Heading-aware chunking
│   ├── embed.py          # Embedding generation
│   ├── retrieve.py       # BM25 + dense + RRF + reranking
│   ├── generate.py       # LLM streaming
│   ├── decompose.py      # Query decomposition
│   └── title.py          # Session title generation
│
├── llm/                  # LLM integrations
│   ├── deepseek.py       # DeepSeek V3
│   ├── openai_client.py  # OpenAI (fallback)
│   └── base.py           # Abstract base
│
├── frontend/             # Frontend (vanilla JS)
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── evals/                # Evaluation suite
│   ├── run_eval.py
│   ├── question_v6.txt
│   └── results/
│
└── docs/                 # Documentation
    ├── DEPLOYMENT.md
    └── architecture.md
```

## Performance

Typical latency breakdown (8 sub-queries, 6 URLs, 50 chunks):

| Stage | Time |
|-------|------|
| Decompose | ~200ms |
| Search | ~800ms |
| Extract | ~1200ms |
| Chunk | ~100ms |
| Retrieve (RRF + rerank) | ~300ms |
| Generation | ~3000ms |
| **Total** | **~5.6s** |

## Known Limitations

- **Jina Reader blocking** — Falls back to trafilatura (less reliable)
- **LLM latency** — Streaming improves UX but generation is still slow
- **RRF tuning** — k=60 is heuristic; may need adjustment per domain
- **No conversation context** — Each query is independent

## Contributing

Contributions welcome! Areas for improvement:

- [ ] Real conversation context (multi-turn)
- [ ] Incremental indexing for URL updates
- [ ] Custom LLM fine-tuning on citations
- [ ] A/B testing framework for retrievers
- [ ] GraphQL API alternative
- [ ] Deploy to Vercel/AWS Lambda

## License

MIT

## Credits

Built with:
- [FastAPI](https://fastapi.tiangolo.com/)
- [sentence-transformers](https://www.sbert.net/)
- [rank-bm25](https://github.com/dorianbrown/rank_bm25)
- [DeepSeek](https://www.deepseek.com/)
- [Tavily](https://tavily.com/)
