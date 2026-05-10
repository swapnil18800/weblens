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
import re
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum, auto
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db.client as db
import db.sessions as sessions
from config import settings
from pipeline.chunk import chunk_pages
from pipeline.decompose import decompose_with_rewrite
from pipeline.extract import extract_pages
from pipeline.embed import upsert_chunks
from pipeline.followups import generate_followups
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

if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")


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

class _PipelineState(Enum):
    STARTED             = auto()
    RETRIEVAL_COMPLETED = auto()
    SUBQUERY_STARTED    = auto()
    DONE                = auto()


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
    global_citation_map: "dict | None" = None,
) -> None:
    """One sub-query's full streaming generation. Pushes events to a shared queue."""
    t_sq = time.perf_counter()
    try:
        async for token in generate_stream(sub_query, ranked, global_citation_map):
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
    pipeline_state = _PipelineState.STARTED

    try:
        # ── 0. Query decomposition ─────────────────────────────────────────────
        # Pull recent turns for follow-up resolution ("and microsoft" → "What's
        # Microsoft's revenue?" given prior NVIDIA context). The fetch is best-
        # effort: any failure leaves history=[] and we proceed with raw query.
        t0 = time.perf_counter()
        history = await sessions.recent_turns(session_id, limit=4)
        decomp = await decompose_with_rewrite(query, history)
        # IMPORTANT: downstream search/retrieval/generation use the rewritten
        # query — that's the whole point of the rewrite. The original is shown
        # in the UI as the user's question; the rewrite surfaces in the trace.
        effective_query = decomp.rewritten_query
        _sub_queries = decomp.sub_queries
        decompose_ms = int((time.perf_counter() - t0) * 1000)
        decompose_mode = "llm"
        yield _sse("decompose_done", {
            "sub_queries":     _sub_queries,
            "original_query":  query,
            "rewritten_query": effective_query,
            "rewrote":         decomp.rewrote,
            "mode":            decompose_mode,
            "latency_ms":      decompose_ms,
        })

        # ── 1. Parallel URL discovery ──────────────────────────────────────────
        t0 = time.perf_counter()
        search_tasks = [discover_urls(sq, max_results=req.max_results) for sq in _sub_queries]
        search_pairs = await asyncio.gather(*search_tasks)
        # search_pairs: list[(results, error_reason)]
        all_results_lists = [pair[0] for pair in search_pairs]
        per_sq_errors = [pair[1] for pair in search_pairs]

        seen_urls: set = set()
        search_results = []
        attempted = 0
        # Track URL → set of sub-query indices that surfaced it. We need this to
        # partition global extract/chunk stats back into per-sub-query slices
        # below (a URL surfaced by 2 sub-queries shows up in BOTH slices).
        url_to_sq: dict[str, set[int]] = {}
        for sq_idx, results in enumerate(all_results_lists):
            for r in results:
                attempted += 1
                url_to_sq.setdefault(r.url, set()).add(sq_idx)
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    search_results.append(r)
        dropped_duplicates = attempted - len(search_results)

        logger.info(
            "[search] sub_queries=%d max_results=%d total_pre_dedup=%d after_dedup=%d",
            len(_sub_queries), req.max_results, attempted, len(search_results),
        )

        search_ms = int((time.perf_counter() - t0) * 1000)

        if not search_results:
            # Pick the most informative error reason — first non-None across sub-queries.
            err_reason = next((r for r in per_sq_errors if r), "no_urls")
            err_msg = {
                "no_api_key":         "Tavily API key not configured.",
                "tavily_timeout":     "Search timed out.",
                "tavily_http_error":  "Search provider returned an error.",
                "no_urls":            "No web sources found for this question.",
            }.get(err_reason, "No URLs found.")
            asyncio.create_task(_persist_stub(
                session_id, query, err_msg,
                urls=[], chunks=[], decompose_ms=decompose_ms, sub_queries=_sub_queries,
            ))
            yield _sse("error", {"message": err_msg, "reason": err_reason})
            return

        _urls = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in search_results]
        per_subquery_urls = [
            [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
            for results in all_results_lists
        ]
        per_subquery_search = [
            {
                "index":    i,
                "subquery": sq,
                "urls":     per_subquery_urls[i],
                "count":    len(per_subquery_urls[i]),
                "error_reason": per_sq_errors[i],
            }
            for i, sq in enumerate(_sub_queries)
        ]

        yield _sse("search_done", {
            "urls":               _urls,
            "sub_queries":        _sub_queries,
            "latency_ms":         search_ms,
            "per_subquery":       per_subquery_search,
            "attempted":          attempted,
            "returned":           len(search_results),
            "dropped_duplicates": dropped_duplicates,
            "error_reason":       next((r for r in per_sq_errors if r), None),
        })

        # ── 2. Full-page extraction ────────────────────────────────────────────
        t0 = time.perf_counter()
        extraction = await extract_pages(search_results)
        pages = extraction.pages
        extract_failures = extraction.failures
        extract_ms = int((time.perf_counter() - t0) * 1000)

        if not pages:
            asyncio.create_task(_persist_stub(
                session_id, query, "Could not extract content from any URL.",
                urls=_urls, chunks=[], decompose_ms=decompose_ms, sub_queries=_sub_queries,
            ))
            yield _sse("error", {
                "message": "Found sources but couldn't read any of them.",
                "reason": "extract_failed",
                "failures": extract_failures,
            })
            return

        # Build per-URL lookups for partitioning extract stats per sub-query.
        page_by_url = {p.url: p for p in pages}
        failure_by_url = {f["url"]: f for f in extract_failures}

        # `_REASON_TO_STATUS` maps internal reason codes → user-facing chip labels.
        # Anything unknown falls through to a generic http error chip.
        _REASON_TO_STATUS = {
            "http_error":   "http_error",
            "timeout":      "http_error",
            "too_short":    "too_short",
            "parse_failed": "parse_error",
        }

        def _per_sq_extract_entries(sq_idx: int) -> dict:
            """Build the per-sub-query extract slice: source-list rows with chip
            status data plus succeeded/attempted/failure counts."""
            sq_results = all_results_lists[sq_idx]
            sq_pages = [page_by_url[r.url] for r in sq_results if r.url in page_by_url]
            sq_failures = [failure_by_url[r.url] for r in sq_results if r.url in failure_by_url]

            entries = []
            for r in sq_results:
                u = r.url
                title = r.title or u
                if u in page_by_url:
                    p = page_by_url[u]
                    status = "cached" if p.from_cache else "extracted"
                    char_count = p.char_count
                elif u in failure_by_url:
                    reason = failure_by_url[u].get("reason", "")
                    status = _REASON_TO_STATUS.get(reason, "http_error")
                    char_count = 0
                else:
                    # Search result that never made it to extract (race / async edge case).
                    continue
                entries.append({
                    "url": u, "title": title, "status": status, "char_count": char_count,
                })
            # Successful pages first (by chars desc), failures at the bottom.
            entries.sort(key=lambda x: (
                0 if x["status"] in ("extracted", "cached") else 1,
                -x["char_count"],
            ))
            return {
                "index":     sq_idx,
                "pages":     entries,
                "succeeded": len(sq_pages),
                "attempted": len(sq_results),
                "failures":  sq_failures,
            }

        per_sq_extract = [_per_sq_extract_entries(i) for i in range(len(_sub_queries))]

        yield _sse("extract_done", {
            "pages":        [p.summary() for p in pages],
            "latency_ms":   extract_ms,
            "attempted":    len(search_results),
            "succeeded":    len(pages),
            "failures":     extract_failures,
            "per_subquery": per_sq_extract,
        })

        # ── 3. Chunking ────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        chunks, chunk_stats, per_url_chunk_stats = chunk_pages(pages)
        chunk_ms = int((time.perf_counter() - t0) * 1000)

        if not chunks:
            asyncio.create_task(_persist_stub(
                session_id, query, "No content chunks generated.",
                urls=_urls, chunks=[], decompose_ms=decompose_ms, sub_queries=_sub_queries,
            ))
            yield _sse("error", {
                "message": "No content chunks generated.",
                "reason":  "no_chunks",
            })
            return

        per_page_chunks: dict = {}
        for c in chunks:
            per_page_chunks[c.url] = per_page_chunks.get(c.url, 0) + 1

        # Per-sub-query chunk slice: aggregate per-URL stats across the
        # sub-query's URL set so the descriptive "Built N (dropped M: ...)"
        # text reflects only that sub-query's pages.
        def _per_sq_chunk_entries(sq_idx: int) -> dict:
            sq_urls = {r.url for r in all_results_lists[sq_idx]}
            agg = {"garbage_dropped": 0, "min_body_dropped": 0, "dedup_dropped": 0, "kept": 0}
            sq_pages_count = 0
            for u in sq_urls:
                s = per_url_chunk_stats.get(u)
                if not s:
                    continue
                sq_pages_count += 1
                for k in agg:
                    agg[k] += s.get(k, 0)
            return {
                "index":      sq_idx,
                "count":      agg["kept"],
                "pages":      sq_pages_count,
                "stats":      agg,
            }

        per_sq_chunk = [_per_sq_chunk_entries(i) for i in range(len(_sub_queries))]

        yield _sse("chunk_done", {
            "count":        len(chunks),
            "pages":        len(pages),
            "latency_ms":   chunk_ms,
            "per_page":     [{"url": u, "chunk_count": n} for u, n in per_page_chunks.items()],
            "stats":        chunk_stats,
            "per_subquery": per_sq_chunk,
        })

        # ── 4. Parallel retrieval (BM25 + dense + RRF + cross-encoder) ─────────
        t0 = time.perf_counter()
        retrieve_tasks = [retrieve(sq, chunks, top_k=req.top_k) for sq in _sub_queries]
        all_results = await asyncio.gather(*retrieve_tasks)
        all_ranked_lists = [r.ranked for r in all_results]
        retrieve_ms = int((time.perf_counter() - t0) * 1000)
        pipeline_state = _PipelineState.RETRIEVAL_COMPLETED

        # Surface embedding device info once (best effort — not fatal on import error)
        try:
            from pipeline.embed import _DEVICE  # type: ignore
            embed_device = _DEVICE
        except Exception:
            embed_device = "cpu"

        # Per-sub-query candidate count = chunks owned by this sub-query's URLs.
        per_sq_embed = []
        for sq_idx in range(len(_sub_queries)):
            sq_urls = {r.url for r in all_results_lists[sq_idx]}
            sq_count = sum(n for u, n in per_page_chunks.items() if u in sq_urls)
            per_sq_embed.append({"index": sq_idx, "candidate_count": sq_count})

        yield _sse("embed_done", {
            "candidate_count": len(chunks),
            "dim": 384,
            "device": embed_device,
            "latency_ms": retrieve_ms,
            "per_subquery": per_sq_embed,
        })

        total_retrieved = sum(len(r) for r in all_ranked_lists)
        yield _sse("retrieve_done", {
            "total_chunks": total_retrieved,
            "sub_queries": len(_sub_queries),
            "latency_ms": retrieve_ms,
        })

        rerank_summary = []
        for i, (ranked, retrieval) in enumerate(zip(all_ranked_lists, all_results)):
            scores = [r.score for r in ranked] or [0.0]
            rerank_summary.append({
                "index":      i,
                "candidates": len(chunks),
                "top_k":      len(ranked),
                "max_score":  round(max(scores), 4),
                "min_score":  round(min(scores), 4),
                "explain":    retrieval.explain,
            })
        yield _sse("rerank_done", {
            "per_subquery": rerank_summary,
            "latency_ms":   retrieve_ms,
        })

        # ── 5. Parallel sub-query generation (multiplexed via queue) ───────────

        # Pre-compute ONE global citation map covering ALL sub-queries' chunks.
        # Every sub-query's LLM prompt will use these same [N] numbers, so sub-answer
        # text and final synthesis text share one numbering scheme.
        global_citation_map: dict[str, int] = {}
        best_chunk_by_url: dict[str, object] = {}  # url → highest-score RankedChunk
        for ranked in all_ranked_lists:
            for rc in ranked:
                if rc.chunk.url not in global_citation_map:
                    global_citation_map[rc.chunk.url] = len(global_citation_map) + 1
                existing = best_chunk_by_url.get(rc.chunk.url)
                if existing is None or rc.score > existing.score:  # type: ignore[union-attr]
                    best_chunk_by_url[rc.chunk.url] = rc

        # Build _all_citations from global map (best snippet per URL)
        _all_citations = []
        for url, num in sorted(global_citation_map.items(), key=lambda x: x[1]):
            rc = best_chunk_by_url[url]
            _all_citations.append({
                "num": num,
                "url": url,
                "title": rc.chunk.title,  # type: ignore[union-attr]
                "snippet": rc.chunk.chunk_text[:300],  # type: ignore[union-attr]
            })

        sub_answers: list = [None] * len(_sub_queries)
        sq_tokens_acc: list = ["" for _ in _sub_queries]
        sq_latencies: list = [0] * len(_sub_queries)
        per_subquery_citations: list = []

        # Pre-compute per-subquery static metadata + emit sub_answer_start up-front
        per_sq_chunks: list = []
        for i, ranked in enumerate(all_ranked_lists):
            sq_citations = build_citations(ranked, global_citation_map)
            sq_chunks_dicts = [r.to_dict() for r in ranked]
            sq_urls = per_subquery_urls[i] if i < len(per_subquery_urls) else []
            per_sq_chunks.append(sq_chunks_dicts)
            per_subquery_citations.append(sq_citations)
            _all_chunks.extend(sq_chunks_dicts)

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

        # Now we're committed to generation — persist embeddings and advance state
        pipeline_state = _PipelineState.SUBQUERY_STARTED
        for result in all_results:
            asyncio.create_task(upsert_chunks(result.candidates, result.candidate_matrix))

        # Spawn N concurrent generator tasks; multiplex tokens through one queue
        out_queue: "asyncio.Queue" = asyncio.Queue()
        for i, (sq, ranked) in enumerate(zip(_sub_queries, all_ranked_lists)):
            gen_tasks.append(asyncio.create_task(
                _generate_subquery_task(i, sq, ranked, out_queue, global_citation_map)
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
            # Persist the per-sub-query slices alongside the trace so
            # rehydration on reload renders chips / chunk-drop breakdowns
            # identical to the live stream.
            _traces.append({
                "index": i,
                "query": _sub_queries[i],
                "urls": per_subquery_urls[i] if i < len(per_subquery_urls) else [],
                "chunks": per_sq_chunks[i],
                "answer": sq_tokens_acc[i],
                "latency_ms": sq_latencies[i],
                "extract_stats": per_sq_extract[i] if i < len(per_sq_extract) else None,
                "chunk_stats":   per_sq_chunk[i]   if i < len(per_sq_chunk)   else None,
                "embed_count":   per_sq_embed[i]["candidate_count"] if i < len(per_sq_embed) else None,
            })

        # ── 6. Synthesis (multi-subquery only) ────────────────────────────────
        synthesis_tokens = []
        t_synth_start = time.perf_counter()

        if len(_sub_queries) > 1:
            yield _sse("synthesis_start", {})
            async for token in synthesize_stream(effective_query, sub_answers):
                synthesis_tokens.append(token)
                yield _sse("token", {"text": token})

        synthesis_ms = int((time.perf_counter() - t_synth_start) * 1000) if len(_sub_queries) > 1 else 0
        pipeline_state = _PipelineState.DONE

        if synthesis_tokens:
            _answer_parts = synthesis_tokens
        else:
            _answer_parts = [sub_answers[0]["answer"]] if sub_answers else []

        # Post-hoc citation reconciliation — keep only [N]s actually referenced in text.
        # Don't renumber: the already-rendered tokens still contain the original [N] labels.
        final_text = "".join(_answer_parts)
        referenced_nums: set[int] = set()
        for text in sq_tokens_acc + [final_text]:
            for m in re.findall(r"\[(\d+)\]", text):
                referenced_nums.add(int(m))
        if referenced_nums:
            _all_citations = [c for c in _all_citations if c["num"] in referenced_nums]

        total_ms = int((time.perf_counter() - t_total) * 1000)
        # Enriched breakdown — frontend rehydrates the FULL trace (live, history, eval)
        # using these fields, so they MUST stay in lock-step with the SSE pipeline.
        latency_breakdown = {
            "decompose_ms": decompose_ms,
            "decompose_mode": decompose_mode,
            "search_ms": search_ms,
            "extract_ms": extract_ms,
            "chunk_ms": chunk_ms,
            "embed_ms": retrieve_ms,
            "retrieve_ms": retrieve_ms,
            "rerank_ms": retrieve_ms,
            "synthesis_ms": synthesis_ms,
            "pages_count": len(pages),
            "chunks_count": len(chunks),
            "embed_device": embed_device,
            "sub_queries_count": len(_sub_queries),
        }

        # Suggested follow-up questions — best-effort, never blocks the answer.
        try:
            followups = await generate_followups(
                question=effective_query,
                answer="".join(_answer_parts),
            )
        except Exception as exc:
            logger.debug("[followups] failed: %s", exc)
            followups = []

        yield _sse("done", {
            "session_id":       session_id,
            "citations":        _all_citations,
            "total_latency_ms": total_ms,
            "latency_breakdown": latency_breakdown,
            "followups":        followups,
        })

        # ── 7. Persist (fire-and-forget) ───────────────────────────────────────
        # Stash followups inside latency_breakdown so we don't need a schema
        # change. The frontend re-reads them on history load.
        latency_breakdown_with_extras = {
            **latency_breakdown,
            "followups": followups,
            "rewritten_query": effective_query if decomp.rewrote else None,
        }
        asyncio.create_task(sessions.save_message(
            session_id=session_id,
            question=query,
            answer="".join(_answer_parts),
            citations=_all_citations,
            urls=_urls,
            chunks=_all_chunks,
            latency_breakdown=latency_breakdown_with_extras,
            total_latency_ms=total_ms,
            sub_queries=_sub_queries,
            traces=_traces,
        ))

    except asyncio.CancelledError:
        for t in gen_tasks:
            if not t.done():
                t.cancel()
        # If generation already started, save a stub so the session sidebar shows the turn.
        # If we're still in retrieval, nothing was persisted yet — nothing to clean up.
        if pipeline_state in (_PipelineState.SUBQUERY_STARTED, _PipelineState.DONE):
            asyncio.create_task(_persist_stub(
                session_id, query, "[cancelled]",
                urls=_urls, chunks=_all_chunks, sub_queries=_sub_queries,
            ))
        raise
    except Exception as exc:
        logger.exception("[pipeline] Unhandled error for query: %s", query)
        asyncio.create_task(_persist_stub(
            session_id, query, str(exc),
            urls=_urls, chunks=_all_chunks, sub_queries=_sub_queries,
        ))
        yield _sse("error", {"message": str(exc), "reason": "internal"})


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
