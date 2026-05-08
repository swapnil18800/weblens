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
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import db.client as db
import db.sessions as sessions
from config import settings
from pipeline.chunk import chunk_pages
from pipeline.decompose import decompose_query
from pipeline.extract import extract_pages
from pipeline.generate import build_citations, generate_stream, synthesize_stream
from pipeline.retrieve import retrieve
from pipeline.search import discover_urls
from pipeline.title import generate_title

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_EVALS_DIR = Path(__file__).parent / "evals"


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up…")
    await db.create_pool()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _preload_models)
    logger.info("Ready.")
    yield
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


# ── Pipeline SSE stream ────────────────────────────────────────────────────────

# Sentinel used inside the parallel sub-query generator queue
_SENTINEL_DONE = object()


async def _title_session(session_id: str, question: str) -> None:
    """Background task: ensure session row exists, then upgrade its title via cheap LLM.

    Only runs on the FIRST question of a session — subsequent questions
    don't change the session title (it stays as the title of the first one).
    """
    try:
        await sessions.ensure_session(session_id)
        # Skip title generation if the session already has prior messages
        if await sessions.session_message_count(session_id) > 0:
            return
        heuristic = question[:60]
        # Set heuristic only if the title is currently NULL
        await sessions.update_session_title(session_id, heuristic)
        # Upgrade with LLM, but only if no other turn / title-change has happened
        title = await generate_title(question)
        if title and title != heuristic:
            await sessions.update_session_title_if(session_id, title, heuristic)
    except Exception as exc:
        logger.debug("[title] background task failed: %s", exc)


async def _persist_stub(
    session_id: str,
    question: str,
    error_msg: str,
    urls: list,
    chunks: list,
    decompose_ms: int = 0,
    sub_queries: list | None = None,
) -> None:
    """Save a placeholder message so the session shows the question even on errors."""
    try:
        await sessions.save_message(
            session_id=session_id,
            question=question,
            answer=f"[error] {error_msg}",
            citations=[],
            urls=urls,
            chunks=chunks,
            latency_breakdown={"decompose_ms": decompose_ms, "error": True},
            total_latency_ms=0,
            sub_queries=sub_queries or [question],
            traces=[],
        )
    except Exception as exc:
        logger.debug("[persist] stub save failed: %s", exc)


async def _generate_subquery_task(
    index: int,
    sub_query: str,
    ranked,
    out_queue: "asyncio.Queue",
) -> None:
    """One sub-query's full streaming generation. Pushes events to a shared queue."""
    t_sq = time.perf_counter()
    try:
        async for token in generate_stream(sub_query, ranked):
            await out_queue.put(("sub_answer_token", {"index": index, "text": token}))
        latency_ms = int((time.perf_counter() - t_sq) * 1000)
        await out_queue.put(("sub_answer_done", {"index": index, "latency_ms": latency_ms}))
    except asyncio.CancelledError:
        await out_queue.put(("sub_answer_done", {"index": index, "latency_ms": 0, "cancelled": True}))
        raise
    except Exception as exc:
        await out_queue.put((
            "sub_answer_done",
            {"index": index, "latency_ms": int((time.perf_counter() - t_sq) * 1000), "error": str(exc)},
        ))


async def _pipeline_stream(req: SearchRequest) -> AsyncIterator[str]:
    t_total = time.perf_counter()
    query = req.query.strip()
    session_id = req.session_id or str(uuid.uuid4())

    if not query:
        yield _sse("error", {"message": "Empty query"})
        return

    # Kick off title generation in the background (touches DB, never raises).
    asyncio.create_task(_title_session(session_id, query))

    _urls: list = []
    _all_chunks: list = []
    _all_citations: list = []
    _answer_parts: list = []
    _sub_queries: list = [query]
    _traces: list = []
    gen_tasks: list = []

    try:
        # ── 0. Query decomposition ─────────────────────────────────────────────
        t0 = time.perf_counter()
        _sub_queries = await decompose_query(query)
        decompose_ms = int((time.perf_counter() - t0) * 1000)
        decompose_mode = "fast_path" if (len(query) < 60 and len(_sub_queries) == 1 and _sub_queries[0] == query) else "llm"
        yield _sse("decompose_done", {
            "sub_queries": _sub_queries,
            "original_query": query,
            "mode": decompose_mode,
            "latency_ms": decompose_ms,
        })

        # ── 1. Parallel URL discovery ──────────────────────────────────────────
        t0 = time.perf_counter()
        search_tasks = [discover_urls(sq, max_results=req.max_results) for sq in _sub_queries]
        all_results_lists = await asyncio.gather(*search_tasks)

        seen_urls: set = set()
        search_results = []
        for results in all_results_lists:
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    search_results.append(r)

        search_ms = int((time.perf_counter() - t0) * 1000)

        if not search_results:
            asyncio.create_task(_persist_stub(
                session_id, query, "No URLs found. Check TAVILY_API_KEY.",
                urls=[], chunks=[], decompose_ms=decompose_ms, sub_queries=_sub_queries,
            ))
            yield _sse("error", {"message": "No URLs found. Check TAVILY_API_KEY."})
            return

        _urls = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in search_results]
        per_subquery_urls = [
            [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
            for results in all_results_lists
        ]
        per_subquery_search = [
            {"index": i, "subquery": sq, "urls": per_subquery_urls[i], "count": len(per_subquery_urls[i])}
            for i, sq in enumerate(_sub_queries)
        ]

        yield _sse("search_done", {
            "urls": _urls,
            "sub_queries": _sub_queries,
            "latency_ms": search_ms,
            "per_subquery": per_subquery_search,
        })

        # ── 2. Full-page extraction ────────────────────────────────────────────
        t0 = time.perf_counter()
        pages = await extract_pages(search_results)
        extract_ms = int((time.perf_counter() - t0) * 1000)

        if not pages:
            asyncio.create_task(_persist_stub(
                session_id, query, "Could not extract content from any URL.",
                urls=_urls, chunks=[], decompose_ms=decompose_ms, sub_queries=_sub_queries,
            ))
            yield _sse("error", {"message": "Could not extract content from any URL."})
            return

        yield _sse("extract_done", {
            "pages": [p.summary() for p in pages],
            "latency_ms": extract_ms,
        })

        # ── 3. Chunking ────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        chunks = chunk_pages(pages)
        chunk_ms = int((time.perf_counter() - t0) * 1000)

        if not chunks:
            asyncio.create_task(_persist_stub(
                session_id, query, "No content chunks generated.",
                urls=_urls, chunks=[], decompose_ms=decompose_ms, sub_queries=_sub_queries,
            ))
            yield _sse("error", {"message": "No content chunks generated."})
            return

        per_page_chunks: dict = {}
        for c in chunks:
            per_page_chunks[c.url] = per_page_chunks.get(c.url, 0) + 1

        yield _sse("chunk_done", {
            "count": len(chunks),
            "pages": len(pages),
            "latency_ms": chunk_ms,
            "per_page": [{"url": u, "chunk_count": n} for u, n in per_page_chunks.items()],
        })

        # ── 4. Parallel retrieval (BM25 + dense + RRF + cross-encoder) ─────────
        t0 = time.perf_counter()
        retrieve_tasks = [retrieve(sq, chunks, top_k=req.top_k) for sq in _sub_queries]
        all_ranked_lists = await asyncio.gather(*retrieve_tasks)
        retrieve_ms = int((time.perf_counter() - t0) * 1000)

        # Surface embedding device info once (best effort — not fatal on import error)
        try:
            from pipeline.embed import _DEVICE  # type: ignore
            embed_device = _DEVICE
        except Exception:
            embed_device = "cpu"

        yield _sse("embed_done", {
            "candidate_count": len(chunks),
            "dim": 384,
            "device": embed_device,
            "latency_ms": retrieve_ms,
        })

        total_retrieved = sum(len(r) for r in all_ranked_lists)
        yield _sse("retrieve_done", {
            "total_chunks": total_retrieved,
            "sub_queries": len(_sub_queries),
            "latency_ms": retrieve_ms,
        })

        rerank_summary = []
        for i, ranked in enumerate(all_ranked_lists):
            scores = [r.score for r in ranked] or [0.0]
            rerank_summary.append({
                "index": i,
                "candidates": len(chunks),
                "top_k": len(ranked),
                "max_score": round(max(scores), 4),
                "min_score": round(min(scores), 4),
            })
        yield _sse("rerank_done", {
            "per_subquery": rerank_summary,
            "latency_ms": retrieve_ms,
        })

        # ── 5. Parallel sub-query generation (multiplexed via queue) ───────────
        sub_answers: list = [None] * len(_sub_queries)
        sq_tokens_acc: list = ["" for _ in _sub_queries]
        sq_latencies: list = [0] * len(_sub_queries)
        seen_citation_urls: set = set()
        per_subquery_citations: list = []

        # Pre-compute per-subquery static metadata + emit sub_answer_start up-front
        per_sq_chunks: list = []
        for i, ranked in enumerate(all_ranked_lists):
            sq_citations = build_citations(ranked)
            sq_chunks_dicts = [r.to_dict() for r in ranked]
            sq_urls = per_subquery_urls[i] if i < len(per_subquery_urls) else []
            per_sq_chunks.append(sq_chunks_dicts)
            per_subquery_citations.append(sq_citations)

            for c in sq_citations:
                if c["url"] not in seen_citation_urls:
                    seen_citation_urls.add(c["url"])
                    _all_citations.append({**c, "num": len(_all_citations) + 1})

            _all_chunks.extend(sq_chunks_dicts)

            # Top-3 chunks-by-url for BM25 / dense surfaces (approximation from final ranking;
            # real BM25/dense traces would require retrieve.py to surface intermediates)
            top3 = [{"url": rc.chunk.url, "score": round(rc.score, 4), "title": rc.chunk.title} for rc in ranked[:3]]

            yield _sse("sub_answer_start", {
                "index": i,
                "query": _sub_queries[i],
                "chunks": sq_chunks_dicts,
                "citations": sq_citations,
                "urls": sq_urls,
                "bm25_top": top3,
                "dense_top": top3,
            })

        # Spawn N concurrent generator tasks; multiplex tokens through one queue
        out_queue: "asyncio.Queue" = asyncio.Queue()
        for i, (sq, ranked) in enumerate(zip(_sub_queries, all_ranked_lists)):
            gen_tasks.append(asyncio.create_task(
                _generate_subquery_task(i, sq, ranked, out_queue)
            ))

        remaining = len(gen_tasks)
        while remaining > 0:
            event_name, payload = await out_queue.get()
            yield _sse(event_name, payload)
            if event_name == "sub_answer_token":
                sq_tokens_acc[payload["index"]] += payload["text"]
            elif event_name == "sub_answer_done":
                sq_latencies[payload["index"]] = payload.get("latency_ms", 0)
                remaining -= 1

        # Build sub-answers list in order
        for i in range(len(_sub_queries)):
            sub_answers[i] = {
                "query": _sub_queries[i],
                "answer": sq_tokens_acc[i],
                "citations": per_subquery_citations[i],
            }
            _traces.append({
                "index": i,
                "query": _sub_queries[i],
                "urls": per_subquery_urls[i] if i < len(per_subquery_urls) else [],
                "chunks": per_sq_chunks[i],
                "answer": sq_tokens_acc[i],
                "latency_ms": sq_latencies[i],
            })

        # ── 6. Synthesis (multi-subquery only) ────────────────────────────────
        synthesis_tokens = []

        if len(_sub_queries) > 1:
            yield _sse("synthesis_start", {})
            async for token in synthesize_stream(query, sub_answers):
                synthesis_tokens.append(token)
                yield _sse("token", {"text": token})

        if synthesis_tokens:
            _answer_parts = synthesis_tokens
        else:
            _answer_parts = [sub_answers[0]["answer"]] if sub_answers else []

        total_ms = int((time.perf_counter() - t_total) * 1000)
        latency_breakdown = {
            "decompose_ms": decompose_ms,
            "search_ms": search_ms,
            "extract_ms": extract_ms,
            "chunk_ms": chunk_ms,
            "retrieve_ms": retrieve_ms,
        }

        yield _sse("done", {
            "session_id": session_id,
            "citations": _all_citations,
            "total_latency_ms": total_ms,
            "latency_breakdown": latency_breakdown,
        })

        # ── 7. Persist (fire-and-forget) ───────────────────────────────────────
        asyncio.create_task(sessions.save_message(
            session_id=session_id,
            question=query,
            answer="".join(_answer_parts),
            citations=_all_citations,
            urls=_urls,
            chunks=_all_chunks,
            latency_breakdown=latency_breakdown,
            total_latency_ms=total_ms,
            sub_queries=_sub_queries,
            traces=_traces,
        ))

    except asyncio.CancelledError:
        # Client disconnected — propagate to in-flight generators and exit silently
        for t in gen_tasks:
            if not t.done():
                t.cancel()
        raise
    except Exception as exc:
        logger.exception("[pipeline] Unhandled error for query: %s", query)
        asyncio.create_task(_persist_stub(
            session_id, query, str(exc),
            urls=_urls, chunks=_all_chunks, sub_queries=_sub_queries,
        ))
        yield _sse("error", {"message": str(exc)})


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/api/search")
async def search_endpoint(req: SearchRequest):
    return StreamingResponse(
        _pipeline_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions")
async def list_sessions_endpoint(limit: int = 50):
    data = await sessions.list_sessions(limit=limit)
    return JSONResponse(data)


@app.get("/api/sessions/{session_id}")
async def get_session_endpoint(session_id: str):
    data = await sessions.get_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(data)


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


@app.get("/api/eval/results")
async def eval_results_list():
    results_dir = _EVALS_DIR / "results"
    if not results_dir.exists():
        return JSONResponse([])
    dirs = sorted(
        [d for d in results_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    result = []
    for d in dirs:
        summary_file = d / "_summary.json"
        summary = None
        if summary_file.exists():
            try:
                summary = json.loads(summary_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        result.append({"run_id": d.name, "summary": summary})
    return JSONResponse(result)


@app.get("/api/eval/results/{run_id}")
async def eval_results_detail(run_id: str):
    results_dir = _EVALS_DIR / "results" / run_id
    if not results_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    summary = None
    summary_file = results_dir / "_summary.json"
    if summary_file.exists():
        try:
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    questions = []
    for f in sorted(results_dir.glob("[0-9]*.json")):
        try:
            questions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass

    return JSONResponse({"run_id": run_id, "summary": summary, "questions": questions})


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
