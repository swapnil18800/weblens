"""
web-search-rag — FastAPI application

Endpoints:
  POST /api/search              → SSE stream (pipeline events + answer tokens)
  GET  /api/sessions            → list all sessions
  GET  /api/sessions/{id}       → session history with full traces
  GET  /api/eval/questions      → serve question file (?set=smoke|full|v6_smoke|v6|v2_smoke|v2)
  GET  /api/eval/results        → list eval run directories
  GET  /api/eval/results/{id}   → summary for a specific eval run
  GET  /api/health              → health check (includes environment)
  GET  /                        → frontend/index.html

SSE event protocol:
  event: decompose_done   data: {sub_queries, original_query, mode, latency_ms}
  event: search_done      data: {urls, sub_queries, latency_ms, per_subquery}
  event: extract_done     data: {pages, latency_ms}
  event: chunk_done       data: {count, pages, latency_ms, per_page}
  event: embed_done       data: {candidate_count, dim, latency_ms, device}
  event: retrieve_done    data: {total_chunks, sub_queries, latency_ms}
  event: rerank_done      data: {per_subquery, latency_ms}
  event: sub_answer_start data: {index, query, chunks, citations, urls, bm25_top, dense_top}
  event: sub_answer_token data: {index, text}
  event: sub_answer_done  data: {index, latency_ms}
  event: synthesis_start  data: {}
  event: token            data: {text}
  event: done             data: {session_id, citations, total_latency_ms, latency_breakdown}
  event: error            data: {message}
"""
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from dotenv import load_dotenv

# Load .env into os.environ FIRST — before any module imports `config` or
# instantiates `Settings()`. `override=True` ensures the .env file wins over
# any stale shell-exported value (TAVILY_API_KEY etc.). On hosted deploys
# (Railway, Fly) there's no .env in the repo so this is a no-op and the
# platform-injected env vars are honored.
load_dotenv(Path(__file__).parent / ".env", override=True)  # noqa: E402

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langsmith import tracing_context
from pydantic import BaseModel

import db.client as db
import db.sessions as sessions
from config import settings
from pipeline.graph import run_pipeline
from pipeline.title import generate_title

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_EVALS_DIR = Path(__file__).parent / "evals"


# ── Lifespan ───────────────────────────────────────────────────────────────────

async def _cleanup_cache_periodic():
    """Drop expired cache rows every 30 min so the tables don't grow unbounded."""
    from pipeline import query_cache
    while True:
        try:
            n = await query_cache.delete_expired()
            if n:
                logger.info("[cleanup] dropped %s expired query_cache rows", n)
            # page_cache cleanup (mirror logic — bounded SQL, runs cheaply)
            result = await db.execute("DELETE FROM page_cache WHERE expires_at < NOW()")
            if isinstance(result, str) and result.startswith("DELETE "):
                k = int(result.split()[-1])
                if k:
                    logger.info("[cleanup] dropped %d expired page_cache rows", k)
        except Exception as exc:
            logger.debug("[cleanup] periodic cleanup failed: %s", exc)
        await asyncio.sleep(1800)  # 30 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up…")
    await db.create_pool()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _preload_models)
    cleanup_task = asyncio.create_task(_cleanup_cache_periodic())
    logger.info("Ready.")
    yield
    cleanup_task.cancel()
    await db.close_pool()
    logger.info("Shut down.")


def _preload_models() -> None:
    from pipeline.embed import preload_models
    preload_models()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="WebLens", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

_FRONTEND_DIR = Path(__file__).parent / "frontend"
_FRONTEND_DIST = _FRONTEND_DIR / "dist"

if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")


@app.get("/question_examples.json")
async def serve_examples_json():
    """Serve the question bank used by the homepage chips + Examples dropdown.
    Vite copies `frontend/public/question_examples.json` into `dist/` on build,
    but app.py only mounts `/assets`, so this targeted route is the bridge."""
    p = _FRONTEND_DIST / "question_examples.json"
    if p.exists():
        return FileResponse(p)
    src = _FRONTEND_DIR / "public" / "question_examples.json"
    if src.exists():
        return FileResponse(src)
    raise HTTPException(status_code=404, detail="question_examples.json not found")


@app.get("/")
async def serve_index():
    # If the frontend has been built (`npm run build`), serve dist/index.html.
    # Otherwise, point the user to the dev frontend.
    dist_index = _FRONTEND_DIST / "index.html"
    if dist_index.exists():
        return FileResponse(dist_index)
    return JSONResponse({
        "status": "ok",
        "message": "Backend is running. Start the frontend dev server: cd frontend && npm run dev (http://localhost:5174)",
        "docs": "/docs",
    })


# ── Request model ──────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    max_results: int = 6
    top_k: int = 8


# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _title_session(session_id: str, question: str) -> None:
    """Background task: ensure session row exists, then upgrade its title via cheap LLM.

    Only runs on the FIRST question of a session.
    """
    try:
        await sessions.ensure_session(session_id)
        if await sessions.session_message_count(session_id) > 0:
            return
        heuristic = question[:60]
        await sessions.update_session_title(session_id, heuristic)
        title = await generate_title(question)
        if title and title != heuristic:
            await sessions.update_session_title_if(session_id, title, heuristic)
    except Exception as exc:
        logger.debug("[title] background task failed: %s", exc)


async def _pipeline_stream(
    req: SearchRequest,
    trace: bool = False,
    cache_override: Optional[bool] = None,
) -> AsyncIterator[str]:
    """Drive the LangGraph pipeline and stream its events as SSE.

    `trace=True` enables LangSmith tracing for this request only (sent by the
    eval harness via X-Langsmith-Trace: true). Tracing is off by default.

    `cache_override=True/False` forces semantic cache on/off for this request
    only (sent by the eval harness via X-Semantic-Cache: on/off). When None,
    falls back to `settings.semantic_cache_enabled`.
    """
    query = req.query.strip()
    session_id = req.session_id or str(uuid.uuid4())

    if not query:
        yield _sse("error", {"message": "Empty query"})
        return

    # Background: title generation (touches DB, never raises).
    asyncio.create_task(_title_session(session_id, query))

    # Fetch recent conversation history for the rewriter + generate context.
    # Best-effort — empty history if anything fails.
    try:
        history = await sessions.recent_turns(session_id, limit=settings.history_max_turns)
    except Exception:
        history = []

    try:
        with tracing_context(enabled=trace, project_name=settings.langsmith_project):
            async for event_name, data in run_pipeline(
                query=query,
                session_id=session_id,
                history=history,
                max_results=req.max_results,
                top_k=req.top_k,
                cache_enabled=cache_override,
            ):
                yield _sse(event_name, data)
    except asyncio.CancelledError:
        # Client disconnected; the graph task will be cancelled as the generator unwinds.
        raise
    except Exception as exc:
        logger.exception("[pipeline] Unhandled error for query: %s", query)
        yield _sse("error", {"message": str(exc), "reason": "internal"})


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/api/search")
async def search_endpoint(req: SearchRequest, request: Request):
    trace = request.headers.get("X-Langsmith-Trace", "").lower() == "true"
    cache_hdr = request.headers.get("X-Semantic-Cache", "").lower().strip()
    cache_override: Optional[bool] = None
    if cache_hdr in ("on", "true", "1"):
        cache_override = True
    elif cache_hdr in ("off", "false", "0"):
        cache_override = False
    return StreamingResponse(
        _pipeline_stream(req, trace=trace, cache_override=cache_override),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions")
async def list_sessions_endpoint(limit: int = 50):
    # In public_mode (production), hide the full sessions list from the API —
    # the frontend is responsible for using sessionStorage for the active
    # session_id. Sessions still persist in DB for analytics/debugging.
    if settings.public_mode:
        return JSONResponse([])
    data = await sessions.list_sessions(limit=limit)
    return JSONResponse(data)


@app.get("/api/sessions/{session_id}")
async def get_session_endpoint(session_id: str):
    # In public_mode, only the session_id held in the active browser session is
    # accessible — but we DON'T block this endpoint, because the frontend
    # legitimately needs to fetch the active session's history on a fresh
    # mount (e.g., page reload while still on the same session_id in
    # sessionStorage). Listing all sessions is what we block, not detail
    # access to a specific one.
    data = await sessions.get_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(data)


@app.get("/api/eval/sessions")
async def list_eval_sessions_endpoint(limit: int = 200):
    data = await sessions.list_eval_sessions(limit=limit)
    return JSONResponse(data)


@app.delete("/api/eval/sessions")
async def delete_all_eval_sessions_endpoint():
    n = await sessions.delete_eval_sessions()
    return JSONResponse({"deleted": n})


@app.delete("/api/admin/query_cache")
async def clear_query_cache_endpoint():
    """Wipe all entries from query_cache. Used by the eval harness to start clean."""
    from pipeline import query_cache as _qc
    n = await _qc.clear_all()
    return JSONResponse({"deleted": n})


@app.post("/api/admin/query_cache/delete")
async def delete_query_cache_by_text(payload: dict):
    """Delete a single cache row by query text (after eval clean-up)."""
    from pipeline import query_cache as _qc
    q = (payload or {}).get("query", "")
    if not q:
        return JSONResponse({"deleted": 0})
    n = await _qc.delete_by_query_text(q)
    return JSONResponse({"deleted": n})


@app.get("/api/admin/query_cache/snapshot")
async def query_cache_snapshot():
    """Return current set of query_hash values. Used by eval harness to diff before/after."""
    try:
        rows = await db.fetch("SELECT query_hash, query_text FROM query_cache ORDER BY created_at")
        return JSONResponse({"hashes": [r["query_hash"] for r in rows],
                             "rows": [{"query_hash": r["query_hash"], "query_text": r["query_text"]} for r in rows]})
    except Exception as exc:
        return JSONResponse({"hashes": [], "rows": [], "error": str(exc)})


@app.post("/api/admin/query_cache/diff")
async def query_cache_diff(payload: dict):
    """Return new cache rows added since the baseline snapshot.
    Body: {"baseline_hashes": ["hash1", "hash2", ...]}
    Returns full row metadata for newly-inserted rows.
    """
    baseline = set((payload or {}).get("baseline_hashes", []))
    try:
        rows = await db.fetch(
            "SELECT query_hash, query_text, mode, created_at, expires_at, hit_count "
            "FROM query_cache ORDER BY created_at"
        )
        new_rows = [
            {
                "query_hash": r["query_hash"],
                "query_text": r["query_text"],
                "mode": r["mode"],
                "inserted_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                "hit_count": r.get("hit_count", 0),
            }
            for r in rows if r["query_hash"] not in baseline
        ]
        return JSONResponse({"new_rows": new_rows})
    except Exception as exc:
        return JSONResponse({"new_rows": [], "error": str(exc)})


@app.get("/api/eval/questions")
async def eval_questions(set: str = "smoke"):
    fname_map = {
        "smoke":    "question_v1_smoke.txt",
        "full":     "question_v1.txt",
        "v6_smoke": "question_v6_smoke.txt",
        "v6":       "question_v6.txt",
        "v2_smoke": "question_v2_smoke.txt",
        "v2":       "question_v2.txt",
    }
    fname = fname_map.get(set, "question_v1_smoke.txt")
    path = _EVALS_DIR / fname
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Question file not found: {fname}")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


def _read_eval_summary(run_dir) -> Optional[dict]:
    """Read summary.json (v8+) with fallback to legacy _summary.json (v7).
    Returns None if neither exists or fails to parse."""
    for name in ("summary.json", "_summary.json"):
        p = run_dir / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def _list_eval_question_files(run_dir):
    """Return sorted list of per-question JSON files. v8+ runs put them in
    `per_question/`, v7 and earlier put them at the run-dir root."""
    pq_dir = run_dir / "per_question"
    if pq_dir.exists() and pq_dir.is_dir():
        return sorted(pq_dir.glob("[0-9]*.json"))
    return sorted(run_dir.glob("[0-9]*.json"))


def _read_cached_rows(run_dir) -> list:
    """Read cached_rows.json (v9+) if present."""
    p = run_dir / "cached_rows.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


@app.get("/api/eval/results")
async def eval_results_list(include_smoke: bool = False):
    """List eval runs. By default excludes smoke runs (kept in `results/smoke/`)
    from the main listing — pass `?include_smoke=true` to include them.

    Smoke runs live under `evals/results/smoke/{ts}/`; full runs live at
    `evals/results/{ts}_full/`. The legacy `{ts}_smoke` flat dirs are
    treated as smoke and excluded too.
    """
    results_dir = _EVALS_DIR / "results"
    if not results_dir.exists():
        return JSONResponse([])

    # Build the candidate list — flatten one level for the `smoke/` subdir.
    candidates: list = []
    for d in results_dir.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if name == "smoke":
            # Smoke subdirectory — each child is a run
            if include_smoke:
                for sub in d.iterdir():
                    if sub.is_dir():
                        candidates.append((f"smoke/{sub.name}", sub, True))
            continue
        is_smoke = name.endswith("_smoke")
        if is_smoke and not include_smoke:
            continue
        candidates.append((name, d, is_smoke))

    # Sort by name desc (timestamp ordering)
    candidates.sort(key=lambda x: x[0], reverse=True)

    result = []
    for run_id, d, is_smoke in candidates:
        result.append({
            "run_id":  run_id,
            "summary": _read_eval_summary(d),
            "is_smoke": is_smoke,
        })
    return JSONResponse(result)


@app.get("/api/eval/results/{run_id:path}")
async def eval_results_detail(run_id: str):
    """Fetch one eval run. `run_id` accepts `smoke/<ts>` form too."""
    results_dir = _EVALS_DIR / "results" / run_id
    if not results_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    summary = _read_eval_summary(results_dir)

    questions = []
    for f in _list_eval_question_files(results_dir):
        try:
            questions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass

    cached_rows = _read_cached_rows(results_dir)

    return JSONResponse({
        "run_id":      run_id,
        "summary":     summary,
        "questions":   questions,
        "cached_rows": cached_rows,
    })


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "env": settings.environment,
        "dev_mode": settings.environment != "production",
        "version": "3.0.0",
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    deleted = await sessions.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"deleted": session_id})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=settings.port, reload=True)
