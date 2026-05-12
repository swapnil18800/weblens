"""
LangGraph orchestration for the WebLens RAG pipeline (v9).

Node graph:

    START
      └─ rewrite_query            (LLM call 1: conversation-aware rewrite)
          └─ analyze              (LLM call 2: route + decompose, single JSON output)
              ├─[parametric]─→ parametric_answer ──────────────────────────────────────────→ emit_done → END
              └─[search]    ─→ cache_lookup
                                 ├─[hit] ─→ cache_replay ────────────────────────────────→ emit_done → END
                                 └─[miss]─→ search_urls
                                              └─→ extract_pages         (emits page_cache_info)
                                                    └─→ chunk_pages
                                                           └─→ retrieve  (BM25/embed/RRF/rerank inner spans)
                                                                  └─→ generate_answers
                                                                         └─→ embedding_cleanup
                                                                                └─→ cache_insert → emit_done → END

Compared to v8, this graph:
  • Splits the old monolithic `node_analyze` into `rewrite_query` + `analyze`.
  • Splits the old monolithic `search_pipeline` into 5 nodes (search_urls,
    extract_pages, chunk_pages, retrieve, generate_answers) plus a
    `embedding_cleanup` housekeeping node.
  • Each retrieval sub-stage (BM25, dense embed, RRF, cross-encoder rerank) is
    a @traceable span inside `pipeline/retrieve.py` so it shows up with its
    proper run_type icon in LangSmith.
  • Intermediate pipeline state is held in `RuntimeContext.workspace` (NOT
    GraphState) — keeps the state TypedDict slim and serializable.

SSE events are pushed onto `RuntimeContext.event_queue`; the HTTP layer in
`app.py` drains the queue and forwards events to the client. Every existing
event type from v8 is preserved byte-identical so the frontend keeps working
without changes. NEW events: `rewrite_done`, `page_cache_info`,
`embedding_cleanup_done`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, AsyncIterator, List, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import traceable
from langsmith.run_helpers import trace as ls_trace

import db.sessions as sessions
from config import settings
from pipeline.analyze import AnalyzeResult, rewrite_query, route_and_decompose
from pipeline.chunk import chunk_pages as _chunk_pages
from pipeline.extract import extract_pages as _extract_pages
from pipeline.embed import upsert_chunks
from pipeline.followups import generate_followups
from pipeline.generate import build_citations, generate_stream, synthesize_stream
from pipeline.retrieve import retrieve
from pipeline.runtime import RuntimeContext, get_runtime, reset_runtime, set_runtime
from pipeline.search import discover_urls
from pipeline import query_cache


# ── Traced wrappers — give each pipeline stage its own LangSmith run_type ─────
# LangGraph's auto-instrumentation tags every node as `chain`. Wrapping the
# inner work in @traceable lets LangSmith display proper icons:
#   • llm        for LLM calls
#   • retriever  for retrieval
#   • tool       for external tools
#   • parser     for parsing

@traceable(run_type="llm", name="Rewrite query (conversational)")
async def _traced_rewrite(query: str, history: list):
    return await rewrite_query(query, history)


@traceable(run_type="llm", name="Analyze · route + decompose")
async def _traced_route_decompose(rewritten: str, rewrote: bool):
    return await route_and_decompose(rewritten, rewrote)


@traceable(run_type="retriever", name="Cache lookup (pgvector ANN)")
async def _traced_cache_lookup(query: str):
    return await query_cache.lookup(query)


@traceable(run_type="tool", name="Web search · Tavily")
async def _traced_discover_urls(sub_query: str, max_results: int):
    return await discover_urls(sub_query, max_results=max_results)


@traceable(run_type="tool", name="Page extraction · Jina + trafilatura")
async def _traced_extract_pages(search_results):
    return await _extract_pages(search_results)


@traceable(run_type="parser", name="Chunk pages · heading-aware")
def _traced_chunk_pages(pages):
    return _chunk_pages(pages)


@traceable(run_type="retriever", name="Hybrid retrieve · BM25 + dense + RRF + rerank")
async def _traced_retrieve(sub_query: str, chunks, top_k: int):
    return await retrieve(sub_query, chunks, top_k=top_k)


@traceable(run_type="tool", name="Embedding cleanup · drop in-memory matrices")
def _traced_embedding_cleanup(candidate_count: int) -> dict:
    """Pure observability span — the actual GC happens because we drop refs to
    `RuntimeContext.workspace` in node_embedding_cleanup. This shim exists so
    the cleanup step is a visible LangSmith node, not invisible Python GC."""
    return {"freed_candidate_count": candidate_count}


@traceable(run_type="tool", name="Cache insert")
async def _traced_cache_insert(**kwargs):
    return await query_cache.insert(**kwargs)


logger = logging.getLogger(__name__)

REPLAY_CHUNK_CHARS = 8  # tokens-per-yield when replaying parametric / cached answers


# ── State ─────────────────────────────────────────────────────────────────────
# Lean GraphState — intermediate pipeline data lives in RuntimeContext.workspace
# (a per-request dict), NOT here, so the TypedDict stays small and serializable.

class GraphState(TypedDict, total=False):
    # Inputs
    query: str
    session_id: str
    history: list
    max_results: int
    top_k: int
    cache_enabled: Optional[bool]   # None → fall back to settings.semantic_cache_enabled
    # Analyze outputs
    mode: Literal["parametric", "search", "cache"]
    rewritten_query: str
    sub_queries: list
    parametric_answer: Optional[str]
    rationale: str
    rewrote: bool
    # Cache
    cache_hit: Optional[dict]
    # Final outputs (for cache_insert + persist)
    final_answer: str
    citations: list
    urls: list
    all_chunks: list
    traces: list
    latency_breakdown: dict
    followups: list
    error: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _replay_string_as_tokens(rt: RuntimeContext, index: int, text: str, query: str) -> None:
    """Emit a string as a sequence of sub_answer_token events to mimic a live stream."""
    await rt.emit("sub_answer_start", {
        "index": index, "query": query, "chunks": [], "citations": [], "urls": [],
        "bm25_top": [], "dense_top": [],
    })
    t0 = time.perf_counter()
    for i in range(0, len(text), REPLAY_CHUNK_CHARS):
        chunk = text[i : i + REPLAY_CHUNK_CHARS]
        await rt.emit("sub_answer_token", {"index": index, "text": chunk})
        await asyncio.sleep(0)
    await rt.emit("sub_answer_done", {
        "index": index, "latency_ms": int((time.perf_counter() - t0) * 1000),
    })


# ── Node: rewrite_query ───────────────────────────────────────────────────────

async def node_rewrite_query(state: GraphState) -> dict:
    """LLM call 1: conversation-aware rewrite. No-op (just passes through) when
    history is empty. Emits `rewrite_done` if a rewrite actually occurred."""
    rt = get_runtime()
    t0 = time.perf_counter()
    rewritten, rewrote = await _traced_rewrite(state["query"], state.get("history") or [])
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("rewrite_ms", ms)
    await rt.emit("rewrite_done", {
        "original_query":  state["query"],
        "rewritten_query": rewritten,
        "rewrote":         rewrote,
        "latency_ms":      ms,
    })
    return {"rewritten_query": rewritten, "rewrote": rewrote}


# ── Node: analyze (route + decompose) ─────────────────────────────────────────

async def node_analyze(state: GraphState) -> dict:
    """LLM call 2: route (parametric vs search) + decompose into sub-queries."""
    rt = get_runtime()
    t0 = time.perf_counter()
    result: AnalyzeResult = await _traced_route_decompose(
        state["rewritten_query"], state.get("rewrote", False)
    )
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("decompose_ms", ms)
    await rt.emit("decompose_done", {
        "sub_queries":     result.sub_queries,
        "original_query":  state["query"],
        "rewritten_query": result.rewritten_query,
        "rewrote":         result.rewrote,
        "mode":            result.mode,
        "rationale":       result.rationale,
        "latency_ms":      ms,
    })
    return {
        "mode": result.mode,
        "rewritten_query": result.rewritten_query,
        "sub_queries": result.sub_queries,
        "parametric_answer": result.parametric_answer,
        "rationale": result.rationale,
        "rewrote": result.rewrote,
    }


# ── Node: parametric_answer ───────────────────────────────────────────────────

async def node_parametric_answer(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    answer = state.get("parametric_answer") or ""
    await _replay_string_as_tokens(rt, 0, answer, state["query"])
    return {
        "final_answer": answer,
        "citations": [],
        "urls": [],
        "all_chunks": [],
        "traces": [],
    }


# ── Node: cache_lookup ────────────────────────────────────────────────────────

async def node_cache_lookup(state: GraphState, config: Any = None) -> dict:
    # Per-request override (from X-Semantic-Cache header) takes precedence over settings.
    cache_enabled = state.get("cache_enabled")
    if cache_enabled is None:
        cache_enabled = settings.semantic_cache_enabled
    if not cache_enabled:
        return {"cache_hit": None}
    hit = await _traced_cache_lookup(state["rewritten_query"])
    return {"cache_hit": hit, "mode": "cache" if hit else state.get("mode", "search")}


# ── Node: cache_replay ────────────────────────────────────────────────────────

async def node_cache_replay(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    hit = state.get("cache_hit") or {}
    answer = hit.get("answer", "")
    citations = hit.get("citations") or []
    urls = hit.get("urls") or []
    sub_queries = hit.get("sub_queries") or [state["query"]]

    await _replay_string_as_tokens(rt, 0, answer, state["query"])
    return {
        "final_answer": answer,
        "citations": citations,
        "urls": urls,
        "sub_queries": sub_queries,
        "all_chunks": [],
        "traces": [],
        "mode": "cache",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Search pipeline — split into 5 LangGraph nodes plus embedding_cleanup.
# Intermediate state lives in `RuntimeContext.workspace` (dict). GraphState
# stays slim.
# ─────────────────────────────────────────────────────────────────────────────


# ── Node: search_urls ─────────────────────────────────────────────────────────

async def node_search_urls(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    sub_queries: List[str] = state["sub_queries"]
    max_results = state.get("max_results", 6)

    t0 = time.perf_counter()
    search_tasks = [_traced_discover_urls(sq, max_results) for sq in sub_queries]
    search_pairs = await asyncio.gather(*search_tasks)
    all_results_lists = [pair[0] for pair in search_pairs]
    per_sq_errors = [pair[1] for pair in search_pairs]

    seen_urls: set = set()
    search_results = []
    attempted = 0
    for results in all_results_lists:
        for r in results:
            attempted += 1
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                search_results.append(r)
    dropped_duplicates = attempted - len(search_results)
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("search_ms", ms)

    if not search_results:
        err_reason = next((r for r in per_sq_errors if r), "no_urls")
        err_msg = {
            "no_api_key":        "Tavily API key not configured.",
            "tavily_timeout":    "Search timed out.",
            "tavily_http_error": "Search provider returned an error.",
            "no_urls":           "No web sources found for this question.",
        }.get(err_reason, "No URLs found.")
        await rt.emit("error", {"message": err_msg, "reason": err_reason})
        return {"error": err_msg}

    _urls = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in search_results]
    per_subquery_urls = [
        [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
        for results in all_results_lists
    ]
    per_subquery_search = [
        {"index": i, "subquery": sq, "urls": per_subquery_urls[i],
         "count": len(per_subquery_urls[i]), "error_reason": per_sq_errors[i]}
        for i, sq in enumerate(sub_queries)
    ]
    await rt.emit("search_done", {
        "urls":               _urls,
        "sub_queries":        sub_queries,
        "latency_ms":         ms,
        "per_subquery":       per_subquery_search,
        "attempted":          attempted,
        "returned":           len(search_results),
        "dropped_duplicates": dropped_duplicates,
        "error_reason":       next((r for r in per_sq_errors if r), None),
    })

    # Stash intermediates for downstream pipeline nodes
    rt.workspace["all_results_lists"] = all_results_lists
    rt.workspace["search_results"]    = search_results
    rt.workspace["urls"]              = _urls
    rt.workspace["per_subquery_urls"] = per_subquery_urls
    return {}


# ── Node: extract_pages ───────────────────────────────────────────────────────

async def node_extract_pages(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    search_results = rt.workspace.get("search_results") or []
    all_results_lists = rt.workspace.get("all_results_lists") or []
    sub_queries = state["sub_queries"]

    t0 = time.perf_counter()
    extraction = await _traced_extract_pages(search_results)
    pages = extraction.pages
    extract_failures = extraction.failures
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("extract_ms", ms)

    if not pages:
        await rt.emit("error", {
            "message": "Found sources but couldn't read any of them.",
            "reason":  "extract_failed",
            "failures": extract_failures,
        })
        return {"error": "extract_failed", "urls": rt.workspace.get("urls") or []}

    # Page cache hit/miss surfacing — was invisible in v8
    cache_hits   = [p for p in pages if p.from_cache]
    cache_misses = [p for p in pages if not p.from_cache]
    await rt.emit("page_cache_info", {
        "hits":            len(cache_hits),
        "misses":          len(cache_misses),
        "from_cache_urls": [p.url for p in cache_hits],
        "fetched_urls":    [p.url for p in cache_misses],
    })

    page_by_url = {p.url: p for p in pages}
    failure_by_url = {f["url"]: f for f in extract_failures}
    _REASON_TO_STATUS = {
        "http_error":   "http_error",
        "timeout":      "http_error",
        "too_short":    "too_short",
        "parse_failed": "parse_error",
    }

    def _per_sq_extract(sq_idx: int) -> dict:
        sq_results = all_results_lists[sq_idx]
        sq_pages = [page_by_url[r.url] for r in sq_results if r.url in page_by_url]
        sq_failures = [failure_by_url[r.url] for r in sq_results if r.url in failure_by_url]
        entries = []
        for r in sq_results:
            u = r.url
            title = r.title or u
            if u in page_by_url:
                p = page_by_url[u]
                entries.append({"url": u, "title": title,
                                "status": "cached" if p.from_cache else "extracted",
                                "char_count": p.char_count})
            elif u in failure_by_url:
                reason = failure_by_url[u].get("reason", "")
                entries.append({"url": u, "title": title,
                                "status": _REASON_TO_STATUS.get(reason, "http_error"),
                                "char_count": 0})
        entries.sort(key=lambda x: (0 if x["status"] in ("extracted", "cached") else 1,
                                    -x["char_count"]))
        return {"index": sq_idx, "pages": entries, "succeeded": len(sq_pages),
                "attempted": len(sq_results), "failures": sq_failures}

    per_sq_extract = [_per_sq_extract(i) for i in range(len(sub_queries))]
    await rt.emit("extract_done", {
        "pages":        [p.summary() for p in pages],
        "latency_ms":   ms,
        "attempted":    len(search_results),
        "succeeded":    len(pages),
        "failures":     extract_failures,
        "per_subquery": per_sq_extract,
    })

    rt.workspace["pages"] = pages
    rt.workspace["per_sq_extract"] = per_sq_extract
    return {}


# ── Node: chunk_pages ─────────────────────────────────────────────────────────

async def node_chunk_pages(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    pages = rt.workspace.get("pages") or []
    all_results_lists = rt.workspace.get("all_results_lists") or []
    sub_queries = state["sub_queries"]

    t0 = time.perf_counter()
    chunks, chunk_stats, per_url_chunk_stats = _traced_chunk_pages(pages)
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("chunk_ms", ms)

    if not chunks:
        await rt.emit("error", {"message": "No content chunks generated.", "reason": "no_chunks"})
        return {"error": "no_chunks", "urls": rt.workspace.get("urls") or []}

    per_page_chunks: dict = {}
    for c in chunks:
        per_page_chunks[c.url] = per_page_chunks.get(c.url, 0) + 1

    def _per_sq_chunk(sq_idx: int) -> dict:
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
        return {"index": sq_idx, "count": agg["kept"], "pages": sq_pages_count, "stats": agg}

    per_sq_chunk = [_per_sq_chunk(i) for i in range(len(sub_queries))]
    await rt.emit("chunk_done", {
        "count":        len(chunks),
        "pages":        len(pages),
        "latency_ms":   ms,
        "per_page":     [{"url": u, "chunk_count": n} for u, n in per_page_chunks.items()],
        "stats":        chunk_stats,
        "per_subquery": per_sq_chunk,
    })

    rt.workspace["chunks"] = chunks
    rt.workspace["per_page_chunks"] = per_page_chunks
    rt.workspace["per_sq_chunk"] = per_sq_chunk
    return {}


# ── Node: retrieve ────────────────────────────────────────────────────────────

async def node_retrieve(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    chunks = rt.workspace.get("chunks") or []
    all_results_lists = rt.workspace.get("all_results_lists") or []
    per_page_chunks = rt.workspace.get("per_page_chunks") or {}
    sub_queries = state["sub_queries"]
    top_k = state.get("top_k", 8)

    t0 = time.perf_counter()
    retrieve_tasks = [_traced_retrieve(sq, chunks, top_k) for sq in sub_queries]
    all_results = await asyncio.gather(*retrieve_tasks)
    all_ranked_lists = [r.ranked for r in all_results]
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("retrieve_ms", ms)

    try:
        from pipeline.embed import _DEVICE  # type: ignore
        embed_device = _DEVICE
    except Exception:
        embed_device = "cpu"

    per_sq_embed = []
    for sq_idx in range(len(sub_queries)):
        sq_urls = {r.url for r in all_results_lists[sq_idx]}
        sq_count = sum(n for u, n in per_page_chunks.items() if u in sq_urls)
        per_sq_embed.append({"index": sq_idx, "candidate_count": sq_count})

    await rt.emit("embed_done", {
        "candidate_count": len(chunks), "dim": 384, "device": embed_device,
        "latency_ms": ms, "per_subquery": per_sq_embed,
    })
    total_retrieved = sum(len(r) for r in all_ranked_lists)
    await rt.emit("retrieve_done", {
        "total_chunks": total_retrieved, "sub_queries": len(sub_queries), "latency_ms": ms,
    })
    rerank_summary = []
    for i, (ranked, retrieval) in enumerate(zip(all_ranked_lists, all_results)):
        scores = [r.score for r in ranked] or [0.0]
        rerank_summary.append({
            "index": i, "candidates": len(chunks), "top_k": len(ranked),
            "max_score": round(max(scores), 4), "min_score": round(min(scores), 4),
            "explain": retrieval.explain,
        })
    await rt.emit("rerank_done", {"per_subquery": rerank_summary, "latency_ms": ms})

    # Stash for generate_answers + embedding_cleanup
    rt.workspace["all_ranked_lists"] = all_ranked_lists
    rt.workspace["all_retrieval_results"] = all_results
    rt.workspace["per_sq_embed"] = per_sq_embed
    return {}


# ── Node: generate_answers ────────────────────────────────────────────────────

async def node_generate_answers(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    sub_queries: List[str] = state["sub_queries"]
    rewritten = state["rewritten_query"]
    history = state.get("history") or []

    all_ranked_lists = rt.workspace.get("all_ranked_lists") or []
    all_retrieval_results = rt.workspace.get("all_retrieval_results") or []
    per_subquery_urls = rt.workspace.get("per_subquery_urls") or []
    per_sq_extract = rt.workspace.get("per_sq_extract") or []
    per_sq_chunk = rt.workspace.get("per_sq_chunk") or []
    per_sq_embed = rt.workspace.get("per_sq_embed") or []
    chunks = rt.workspace.get("chunks") or []

    # ── Build global citation map ────────────────────────────────────────────
    global_citation_map: dict[str, int] = {}
    best_chunk_by_url: dict[str, Any] = {}
    for ranked in all_ranked_lists:
        for rc in ranked:
            if rc.chunk.url not in global_citation_map:
                global_citation_map[rc.chunk.url] = len(global_citation_map) + 1
            existing = best_chunk_by_url.get(rc.chunk.url)
            if existing is None or rc.score > existing.score:
                best_chunk_by_url[rc.chunk.url] = rc

    _all_citations = []
    for url, num in sorted(global_citation_map.items(), key=lambda x: x[1]):
        rc = best_chunk_by_url[url]
        _all_citations.append({
            "num": num, "url": url, "title": rc.chunk.title,
            "snippet": rc.chunk.chunk_text[:300],
        })

    sq_tokens_acc: list = ["" for _ in sub_queries]
    sq_latencies: list = [0] * len(sub_queries)
    per_subquery_citations: list = []
    per_sq_chunks_dicts: list = []
    _all_chunks_flat: list = []

    for i, ranked in enumerate(all_ranked_lists):
        sq_citations = build_citations(ranked, global_citation_map)
        sq_chunks_dicts = [r.to_dict() for r in ranked]
        sq_urls = per_subquery_urls[i] if i < len(per_subquery_urls) else []
        per_sq_chunks_dicts.append(sq_chunks_dicts)
        per_subquery_citations.append(sq_citations)
        _all_chunks_flat.extend(sq_chunks_dicts)
        top3 = [{"url": rc.chunk.url, "score": round(rc.score, 4), "title": rc.chunk.title}
                for rc in ranked[:3]]
        await rt.emit("sub_answer_start", {
            "index": i, "query": sub_queries[i], "chunks": sq_chunks_dicts,
            "citations": sq_citations, "urls": sq_urls,
            "bm25_top": top3, "dense_top": top3,
        })

    # Fire-and-forget upsert of candidates to web_chunks (pgvector cache)
    for result in all_retrieval_results:
        asyncio.create_task(upsert_chunks(result.candidates, result.candidate_matrix))

    # ── Parallel sub-query generation via multiplexed queue ──────────────────
    async def _gen_one(index: int, sub_query: str, ranked, out_q: asyncio.Queue) -> None:
        t_sq = time.perf_counter()
        with ls_trace(
            name=f"Generate sub-answer · {index+1}",
            run_type="llm",
            inputs={"sub_query": sub_query, "chunks_in": len(ranked)},
        ) as run:
            collected: list[str] = []
            try:
                async for token in generate_stream(sub_query, ranked, global_citation_map, history=history):
                    collected.append(token)
                    await out_q.put(("sub_answer_token", {"index": index, "text": token}))
                run.add_outputs({"answer": "".join(collected)})
                await out_q.put(("sub_answer_done", {
                    "index": index, "latency_ms": int((time.perf_counter() - t_sq) * 1000),
                }))
            except asyncio.CancelledError:
                await out_q.put(("sub_answer_done", {"index": index, "latency_ms": 0, "cancelled": True}))
                raise
            except Exception as exc:
                run.end(error=str(exc))
                await out_q.put(("sub_answer_done", {
                    "index": index, "latency_ms": int((time.perf_counter() - t_sq) * 1000),
                    "error": str(exc),
                }))

    out_queue: asyncio.Queue = asyncio.Queue()
    gen_tasks = [
        asyncio.create_task(_gen_one(i, sq, ranked, out_queue))
        for i, (sq, ranked) in enumerate(zip(sub_queries, all_ranked_lists))
    ]

    remaining = len(gen_tasks)
    while remaining > 0:
        event_name, payload = await out_queue.get()
        await rt.emit(event_name, payload)
        if event_name == "sub_answer_token":
            sq_tokens_acc[payload["index"]] += payload["text"]
        elif event_name == "sub_answer_done":
            sq_latencies[payload["index"]] = payload.get("latency_ms", 0)
            remaining -= 1

    sub_answers = [
        {"query": sub_queries[i], "answer": sq_tokens_acc[i], "citations": per_subquery_citations[i]}
        for i in range(len(sub_queries))
    ]

    traces = [
        {"index": i, "query": sub_queries[i],
         "urls": per_subquery_urls[i] if i < len(per_subquery_urls) else [],
         "chunks": per_sq_chunks_dicts[i], "answer": sq_tokens_acc[i],
         "latency_ms": sq_latencies[i],
         "extract_stats": per_sq_extract[i] if i < len(per_sq_extract) else None,
         "chunk_stats":   per_sq_chunk[i]   if i < len(per_sq_chunk)   else None,
         "embed_count":   per_sq_embed[i]["candidate_count"] if i < len(per_sq_embed) else None}
        for i in range(len(sub_queries))
    ]

    # ── Synthesis (only if multi-subquery) ──────────────────────────────────
    t_synth = time.perf_counter()
    synthesis_tokens: list = []
    if len(sub_queries) > 1:
        await rt.emit("synthesis_start", {})
        with ls_trace(
            name="Synthesize final answer",
            run_type="llm",
            inputs={"sub_answer_count": len(sub_answers), "rewritten_query": rewritten[:200]},
        ) as run:
            async for token in synthesize_stream(rewritten, sub_answers, history=history):
                synthesis_tokens.append(token)
                await rt.emit("token", {"text": token})
            run.add_outputs({"answer": "".join(synthesis_tokens)})
    synthesis_ms = int((time.perf_counter() - t_synth) * 1000) if len(sub_queries) > 1 else 0
    rt.record_stage("synthesis_ms", synthesis_ms)

    final_text = "".join(synthesis_tokens) if synthesis_tokens else (sub_answers[0]["answer"] if sub_answers else "")

    # Post-hoc citation reconciliation — drop unreferenced citations
    referenced_nums: set = set()
    for text in sq_tokens_acc + [final_text]:
        for m in re.findall(r"\[(\d+)\]", text):
            referenced_nums.add(int(m))
    if referenced_nums:
        _all_citations = [c for c in _all_citations if c["num"] in referenced_nums]

    return {
        "final_answer": final_text,
        "citations": _all_citations,
        "urls": rt.workspace.get("urls") or [],
        "all_chunks": _all_chunks_flat,
        "traces": traces,
        "mode": "search",
    }


# ── Node: embedding_cleanup ───────────────────────────────────────────────────
# Pure housekeeping/observability. The candidate matrices held in workspace are
# now garbage-collectable; this node makes that step VISIBLE in the trace.

async def node_embedding_cleanup(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    t0 = time.perf_counter()
    # Count what we're about to drop (for the trace), then clear the workspace.
    chunks = rt.workspace.get("chunks") or []
    candidate_count = 0
    for r in (rt.workspace.get("all_retrieval_results") or []):
        try:
            candidate_count += len(r.candidates)
        except Exception:
            pass
    info = _traced_embedding_cleanup(candidate_count)
    rt.workspace.pop("chunks", None)
    rt.workspace.pop("all_retrieval_results", None)
    rt.workspace.pop("all_ranked_lists", None)
    rt.workspace.pop("pages", None)
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("embedding_cleanup_ms", ms)
    await rt.emit("embedding_cleanup_done", {
        "freed_candidate_count": info["freed_candidate_count"],
        "freed_chunks_count":    len(chunks),
        "latency_ms":            ms,
    })
    return {}


# ── Node: cache_insert (fire-and-forget) ──────────────────────────────────────

async def node_cache_insert(state: GraphState, config: Any = None) -> dict:
    cache_enabled = state.get("cache_enabled")
    if cache_enabled is None:
        cache_enabled = settings.semantic_cache_enabled
    if not cache_enabled:
        return {}
    if not state.get("final_answer") or state.get("error"):
        return {}
    if state.get("mode") == "cache":
        return {}
    rt = get_runtime()
    asyncio.create_task(_traced_cache_insert(
        query=state["rewritten_query"],
        answer=state["final_answer"],
        citations=state.get("citations") or [],
        urls=state.get("urls") or [],
        sub_queries=state.get("sub_queries") or [state["query"]],
        mode=state.get("mode") or "search",
        latency_breakdown=dict(rt.latency_breakdown),
    ))
    return {}


# ── Node: emit_done ───────────────────────────────────────────────────────────

async def node_emit_done(state: GraphState, config: Any = None) -> dict:
    rt = get_runtime()
    total_ms = int((time.perf_counter() - rt.t_start) * 1000)

    # Best-effort followups (never blocks)
    followups: list = []
    if state.get("mode") != "cache":
        try:
            followups = await generate_followups(
                question=state.get("rewritten_query") or state["query"],
                answer=state.get("final_answer") or "",
            )
        except Exception as exc:
            logger.debug("[followups] failed: %s", exc)

    latency_breakdown = {
        **rt.latency_breakdown,
        "sub_queries_count": len(state.get("sub_queries") or []),
        "mode": state.get("mode") or "search",
        "token_cost": rt.token_tracker.snapshot(),
    }

    await rt.emit("done", {
        "session_id":        rt.session_id,
        "citations":         state.get("citations") or [],
        "total_latency_ms":  total_ms,
        "latency_breakdown": latency_breakdown,
        "followups":         followups,
        "mode":              state.get("mode") or "search",
    })

    # Persist (fire-and-forget) — preserves existing session history behavior.
    if rt.session_id and not state.get("error"):
        latency_with_extras = {
            **latency_breakdown,
            "followups": followups,
            "rewritten_query": state.get("rewritten_query") if state.get("rewrote") else None,
        }
        asyncio.create_task(sessions.save_message(
            session_id=rt.session_id,
            question=state["query"],
            answer=state.get("final_answer") or "",
            citations=state.get("citations") or [],
            urls=state.get("urls") or [],
            chunks=state.get("all_chunks") or [],
            latency_breakdown=latency_with_extras,
            total_latency_ms=total_ms,
            sub_queries=state.get("sub_queries") or [state["query"]],
            traces=state.get("traces") or [],
        ))

    await rt.signal_done()
    return {"followups": followups, "latency_breakdown": latency_breakdown}


# ── Routing edges ─────────────────────────────────────────────────────────────

def _route_after_analyze(state: GraphState) -> str:
    return "parametric_answer" if state.get("mode") == "parametric" else "cache_lookup"


def _route_after_cache_lookup(state: GraphState) -> str:
    return "cache_replay" if state.get("cache_hit") else "search_urls"


def _route_after_search_urls(state: GraphState) -> str:
    return "emit_done" if state.get("error") else "extract_pages"


def _route_after_extract(state: GraphState) -> str:
    return "emit_done" if state.get("error") else "chunk_pages"


def _route_after_chunk(state: GraphState) -> str:
    return "emit_done" if state.get("error") else "retrieve"


# ── Build & compile ───────────────────────────────────────────────────────────

_GRAPH = None


def build_pipeline_graph():
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH

    g = StateGraph(GraphState)
    g.add_node("rewrite_query", node_rewrite_query)
    g.add_node("analyze", node_analyze)
    g.add_node("parametric_answer", node_parametric_answer)
    g.add_node("cache_lookup", node_cache_lookup)
    g.add_node("cache_replay", node_cache_replay)
    g.add_node("search_urls", node_search_urls)
    g.add_node("extract_pages", node_extract_pages)
    g.add_node("chunk_pages", node_chunk_pages)
    g.add_node("retrieve", node_retrieve)
    g.add_node("generate_answers", node_generate_answers)
    g.add_node("embedding_cleanup", node_embedding_cleanup)
    g.add_node("cache_insert", node_cache_insert)
    g.add_node("emit_done", node_emit_done)

    g.add_edge(START, "rewrite_query")
    g.add_edge("rewrite_query", "analyze")
    g.add_conditional_edges("analyze", _route_after_analyze,
                            {"parametric_answer": "parametric_answer",
                             "cache_lookup": "cache_lookup"})
    g.add_conditional_edges("cache_lookup", _route_after_cache_lookup,
                            {"cache_replay": "cache_replay",
                             "search_urls": "search_urls"})

    # Search pipeline — each stage has an error short-circuit to emit_done
    g.add_conditional_edges("search_urls", _route_after_search_urls,
                            {"emit_done": "emit_done", "extract_pages": "extract_pages"})
    g.add_conditional_edges("extract_pages", _route_after_extract,
                            {"emit_done": "emit_done", "chunk_pages": "chunk_pages"})
    g.add_conditional_edges("chunk_pages", _route_after_chunk,
                            {"emit_done": "emit_done", "retrieve": "retrieve"})
    g.add_edge("retrieve", "generate_answers")
    g.add_edge("generate_answers", "embedding_cleanup")
    g.add_edge("embedding_cleanup", "cache_insert")

    g.add_edge("parametric_answer", "emit_done")
    g.add_edge("cache_replay", "emit_done")
    g.add_edge("cache_insert", "emit_done")
    g.add_edge("emit_done", END)

    _GRAPH = g.compile()
    return _GRAPH


# ── Driver: run pipeline as an async event generator ──────────────────────────

async def run_pipeline(
    *,
    query: str,
    session_id: str,
    history: Optional[list] = None,
    max_results: int = 6,
    top_k: int = 8,
    cache_enabled: Optional[bool] = None,
) -> AsyncIterator[tuple[str, dict]]:
    """Run the graph and yield SSE-shaped (event_name, data) tuples as they're produced."""
    graph = build_pipeline_graph()
    rt = RuntimeContext(session_id=session_id)

    run_config: dict = {
        "configurable": {"runtime": rt},
        "run_name": query[:100],
        "metadata": {"question": query, "session_id": session_id,
                     "eval_run_id": os.environ.get("EVAL_RUN_ID"),
                     "eval_mode": os.environ.get("EVAL_MODE")},
        "tags": [t for t in [
            f"eval/{os.environ.get('EVAL_MODE')}/{os.environ.get('EVAL_RUN_ID')}"
            if os.environ.get("EVAL_RUN_ID") else None
        ] if t],
    }

    initial: GraphState = {
        "query": query,
        "session_id": session_id,
        "history": history or [],
        "max_results": max_results,
        "top_k": top_k,
        "cache_enabled": cache_enabled,
    }

    async def _runner() -> None:
        token = set_runtime(rt)
        try:
            await graph.ainvoke(initial, config=run_config)
        except Exception as exc:
            logger.exception("[graph] unhandled error for %r", query[:80])
            await rt.emit("error", {"message": str(exc), "reason": "internal"})
            await rt.signal_done()
        finally:
            reset_runtime(token)

    runner_task = asyncio.create_task(_runner())

    try:
        while True:
            item = await rt.event_queue.get()
            if RuntimeContext.is_done_sentinel(item):
                break
            event_name, data = item
            yield (event_name, data)
    finally:
        if not runner_task.done():
            await runner_task
