# Web Search RAG — How to Run

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.10+ |
| PostgreSQL | Supabase (cloud) or local via Docker |
| API Keys | Tavily, DeepSeek (or OpenAI), Jina (optional) |

---

## 1. Environment Setup

Copy `.env.example` to `.env` (or create `.env`) in the project root:

```env
DATABASE_URL=postgresql://postgres:<password>@<host>:5432/<db>?sslmode=require
TAVILY_API_KEY=tvly-...
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...         # optional fallback
JINA_API_KEY=jina_...         # optional (used for page extraction)
LLM_PROVIDER=deepseek         # or "openai"
LOG_LEVEL=INFO
PORT=8000
```

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## 2. Database Setup

Run once to create the `rag_sessions` and `rag_session_messages` tables:

```bash
python db/migrate_sessions.py
```

Verify tables exist:
```bash
python db/check_tables.py
```

---

## 3. Start the Server

```bash
python app.py
```

Or with uvicorn directly:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at `http://localhost:8000`.

On first startup, sentence-transformer models (`all-MiniLM-L6-v2`, `ms-marco-MiniLM-L-2-v2`) are downloaded and cached (~100 MB total). Subsequent starts are fast.

---

## 4. Using the UI

**Search:** Type any question in the search bar. Multi-entity questions are automatically decomposed into sub-queries (e.g. "Apple vs Microsoft revenue 2024" → 2 sub-queries run in parallel).

**Pipeline Trace (left panel):** Shows each stage with latency — URL Discovery → Extraction → Chunking → Retrieval → Generation.

**Citations:** Click any `[N]` citation in the answer to jump to and expand the source snippet. Click the source URL to open the original page.

**History (top bar):** Opens the session drawer showing all past queries. Click any past query to restore the full answer, citations, and retrieved chunks without re-running.

**Tests (top bar):** Opens the Eval Results panel showing all past eval runs. Each run is a folder in `evals/results/`. Click a run to browse questions with scores, then click a question to see the full answer, citations, chunks, and judge reasoning.

---

## 5. Running Evaluations

The eval harness is a standalone script — the server must be running before you start it.

### v1 question sets (RAG/IR technical questions)

```bash
# Smoke — 2 questions, fast sanity check
python evals/run_eval.py --smoke

# Full — 10 questions, full benchmark
python evals/run_eval.py --full
```

### v6 question sets (financial/multi-company synthesis)

```bash
# v6 smoke — 5 categories, ~1 question each
python evals/run_eval.py --v6-smoke

# v6 full — all categories, multiple questions each
python evals/run_eval.py --v6
```

### Custom server URL

```bash
python evals/run_eval.py --smoke --url http://localhost:8001
```

### Output

Each run creates a folder under `evals/results/<timestamp>_<mode>/`:

| File | Contents |
|------|----------|
| `NN_<category>_<question>.json` | Per-question: answer, citations, chunks, URLs, sub-queries, M1/M3/M7 metrics, judge reasoning |
| `_summary.json` | Aggregate: avg M7, pass/partial/fail counts, avg M1/M3, avg latency |
| `_analysis.md` | Human-readable table of results |
| `eval.log` | Full stdout/stderr |

Results are immediately viewable in the **Tests** panel of the UI — no server restart needed.

---

## 6. Metrics Explained

| Metric | Method | What it measures |
|--------|--------|-----------------|
| **M1** | Keyword overlap ≥ 60% against key facts | Factual correctness of LLM answer |
| **M3** | Same keyword match against retrieved chunks | Retrieval recall (did we get the facts?) |
| **M7** | DeepSeek LLM judge, score 0–1 | Overall answer quality (accuracy, completeness, citations) |

Verdict thresholds: **Pass** ≥ 0.80 · **Partial** 0.40–0.79 · **Fail** < 0.40

---

## 7. Project Structure

```
app.py                  FastAPI server + SSE pipeline
config.py               Pydantic settings (reads .env)
requirements.txt

pipeline/
  decompose.py          LLM query decomposition (≤12 sub-queries)
  search.py             Tavily URL discovery (parallel per sub-query)
  extract.py            Jina Reader / trafilatura page extraction
  chunk.py              Markdown-aware semantic chunking
  embed.py              Sentence-transformer embeddings + BM25
  retrieve.py           BM25 + dense RRF + cross-encoder rerank
  generate.py           Streamed LLM generation + synthesis

llm/
  deepseek.py           DeepSeek client (OpenAI-compatible)
  openai_client.py      OpenAI fallback

db/
  client.py             asyncpg pool (PgBouncer-safe)
  sessions.py           Session CRUD helpers
  migrate_sessions.py   Run once to create tables

evals/
  run_eval.py           Standalone eval harness (HTTP-based)
  question_v1_smoke.txt 2-question smoke set (RAG/IR)
  question_v1.txt       10-question full set (RAG/IR)
  question_v6_smoke.txt 5-question smoke set (financial)
  question_v6.txt       Full financial question set
  results/              Timestamped eval run outputs

frontend/
  index.html            Single-page app (vanilla JS)

docs/
  how-to-run.md         This file
  implementation-summary.md  Architecture + eval results
```

---

## 8. Common Issues

| Issue | Fix |
|-------|-----|
| `No URLs found. Check TAVILY_API_KEY` | Set `TAVILY_API_KEY` in `.env` |
| `asyncpg.exceptions.UndefinedTableError` | Run `python db/migrate_sessions.py` |
| Slow first search (~30s) | Models loading on first request; normal after warmup |
| `JSONB columns return integers` | PgBouncer mode requires `statement_cache_size=0` — already set |
| Jina extraction fails | Set `JINA_API_KEY` or leave blank (trafilatura fallback is automatic) |
| Server port conflict | Change `PORT=8001` in `.env` |
