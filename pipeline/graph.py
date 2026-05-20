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
from pipeline.analyze import AnalyzeResult, RewriteResult, rewrite_query_full, route_and_decompose
from pipeline.summarize import incremental_summary
from pipeline.chunk import chunk_pages as _chunk_pages
from pipeline.extract import extract_pages as _extract_pages
from pipeline.embed import upsert_chunks
from pipeline.followups import generate_followups
from pipeline.generate import build_citations, generate_stream, strip_unknown_links, synthesize_stream
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

@traceable(run_type="llm", name="Rewrite query (conversational + topic-state)")
async def _traced_rewrite_full(
    query: str,
    history: list,
    history_summary: str,
    active_topic: str,
    active_constraints: list,
):
    return await rewrite_query_full(
        query, history,
        history_summary=history_summary,
        active_topic=active_topic,
        active_constraints=active_constraints,
    )


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
    history: list                   # last-N verbatim turns
    history_summary: str            # Phase 7 — rolling summary of older turns
    active_topic: str               # Phase 7 — prior topic anchor (in)
    active_constraints: list        # Phase 7 — prior constraints (in)
    max_results: int
    top_k: int
    cache_enabled: Optional[bool]   # None → fall back to settings.semantic_cache_enabled
    # Analyze outputs
    mode: Literal["parametric", "search", "cache", "unsupported"]
    rewritten_query: str
    sub_queries: list
    parametric_answer: Optional[str]
    rationale: str
    route_reason: str
    confidence: Optional[float]
    rewrote: bool
    # Phase 7 — rewriter classification (out)
    is_topic_switch: bool
    new_active_topic: str
    new_active_constraints: list
    rewrite_confidence: Optional[float]
    clarification: Optional[str]
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
    """LLM call 1: conversation-aware rewrite + topic-state classification.
    Returns the rewritten query plus an explicit `is_topic_switch` flag that
    downstream nodes use to isolate retrieval context."""
    rt = get_runtime()
    t0 = time.perf_counter()
    result: RewriteResult = await _traced_rewrite_full(
        state["query"],
        state.get("history") or [],
        state.get("history_summary") or "",
        state.get("active_topic") or "",
        state.get("active_constraints") or [],
    )
    ms = int((time.perf_counter() - t0) * 1000)
    rt.record_stage("rewrite_ms", ms)
    # Phase 7 — when the rewriter detects a topic switch, isolate retrieval
    # context: downstream nodes (decompose, generate, synthesize) will see an
    # empty history and a blank summary so old context can't contaminate the
    # new topic. The new topic_state is still propagated so it gets persisted.
    history_out = state.get("history") or []
    history_summary_out = state.get("history_summary") or ""
    if result.is_topic_switch:
        history_out = []
        history_summary_out = ""

    await rt.emit("rewrite_done", {
        "original_query":     state["query"],
        "rewritten_query":    result.rewritten,
        "rewrote":            result.changed,
        "is_topic_switch":    result.is_topic_switch,
        "active_topic":       result.active_topic,
        "active_constraints": result.active_constraints,
        "confidence":         result.confidence,
        "clarification":      result.clarification,
        "latency_ms":         ms,
    })
    return {
        "rewritten_query":        result.rewritten,
        "rewrote":                result.changed,
        "history":                history_out,
        "history_summary":        history_summary_out,
        "is_topic_switch":        result.is_topic_switch,
        "new_active_topic":       result.active_topic,
        "new_active_constraints": result.active_constraints,
        "rewrite_confidence":     result.confidence,
        "clarification":          result.clarification,
    }


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
    # Phase 1/2: surface routing decision and its reason as a dedicated event so
    # the frontend trace panel can show WHY the pipeline took the path it did.
    await rt.emit("route_done", {
        "mode":         result.mode,
        "route_reason": result.route_reason,
        "confidence":   result.confidence,
        "rationale":    result.rationale,
        "latency_ms":   ms,
    })
    await rt.emit("decompose_done", {
        "sub_queries":     result.sub_queries,
        "original_query":  state["query"],
        "rewritten_query": result.rewritten_query,
        "rewrote":         result.rewrote,
        "mode":            result.mode,
        "rationale":       result.rationale,
        "route_reason":    result.route_reason,
        "confidence":      result.confidence,
        "latency_ms":      ms,
    })
    return {
        "mode": result.mode,
        "rewritten_query": result.rewritten_query,
        "sub_queries": result.sub_queries,
        "parametric_answer": result.parametric_answer,
        "rationale": result.rationale,
        "route_reason": result.route_reason,
        "confidence": result.confidence,
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


# ── Phase 3: fused per-subquery retrieve+generate ─────────────────────────────
#
# The previous topology serialized at the stage barrier between retrieve and
# generate_answers: ALL N sub-queries had to finish their retrieve before ANY
# generation could start. That meant the slowest retrieval gated the entire
# generation phase — and generation is the dominant latency cost (LLM tokens).
#
# `node_retrieve_and_generate` removes that barrier. Per sub-query:
#     retrieve  →  emit per-sq retrieval events  →  start generation
# All N sub-queries run independently inside an asyncio.Semaphore; the global
# citation map is built INCREMENTALLY as each retrieve completes, so the
# numbering remains consistent across sub-answers and the final synthesis.
#
# Stage barriers preserved (still cheap because each stage already parallelizes
# internally across URLs / sub-queries):
#   - search_urls (Tavily searches in parallel)
#   - extract_pages (URL fetches in parallel)
#   - chunk_pages (in-process, ms latency)
#
# Stage barrier removed:
#   - retrieve  →  generate
#
# This is the "incremental concurrency refactor" the plan called for — minimal
# orchestration churn, biggest single-stage latency win.


async def node_retrieve(state: GraphState, config: Any = None) -> dict:
    """[deprecated] Kept for backwards-compat with eval harness imports. The
    live pipeline uses `node_retrieve_and_generate` which fuses retrieve+generate.
    """
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
    history_summary = state.get("history_summary") or ""

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
        chunks_available = len(ranked)
        # Allowed-URL set for hyperlink post-filter (Phase 6)
        allowed_urls = {rc.chunk.url for rc in ranked}
        with ls_trace(
            name=f"Generate sub-answer · {index+1}",
            run_type="llm",
            inputs={"sub_query": sub_query, "chunks_in": chunks_available},
        ) as run:
            collected: list[str] = []
            try:
                async for token in generate_stream(
                    sub_query, ranked, global_citation_map,
                    history=history, history_summary=history_summary,
                ):
                    collected.append(token)
                    await out_q.put(("sub_answer_token", {"index": index, "text": token}))
                final_sub_text = "".join(collected)
                # Phase 6 — strip any markdown links the model produced that point at
                # URLs outside the citation pool (anti-hallucination safety net).
                cleaned_sub_text, stripped_links = strip_unknown_links(final_sub_text, allowed_urls)
                # Phase 4 — utilization metric: distinct [N] markers actually used / chunks available.
                used_nums = set(int(m) for m in re.findall(r"\[(\d+)\]", cleaned_sub_text))
                citations_used = len(used_nums)
                utilization_ratio = (
                    round(citations_used / chunks_available, 3) if chunks_available else 0.0
                )
                run.add_outputs({
                    "answer": cleaned_sub_text,
                    "chunks_available": chunks_available,
                    "citations_used": citations_used,
                    "utilization_ratio": utilization_ratio,
                    "hyperlinks_stripped": stripped_links,
                })
                await out_q.put(("sub_answer_done", {
                    "index": index,
                    "latency_ms": int((time.perf_counter() - t_sq) * 1000),
                    "chunks_available": chunks_available,
                    "citations_used": citations_used,
                    "utilization_ratio": utilization_ratio,
                    "hyperlinks_stripped": stripped_links,
                    # Internal-only: cleaned sub-answer text. The consumer loop
                    # uses this to overwrite sq_tokens_acc so synthesis sees the
                    # safety-net-cleaned version. NOT forwarded to the SSE client
                    # (see the consumer-side filter below).
                    "_clean_text": cleaned_sub_text,
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
    # Phase 4 — aggregate utilization across sub-answers for trace/metrics.
    util_ratios: list[float] = []
    citations_used_total: list[int] = []
    chunks_available_total: list[int] = []
    while remaining > 0:
        event_name, payload = await out_queue.get()
        if event_name == "sub_answer_token":
            await rt.emit(event_name, payload)
            sq_tokens_acc[payload["index"]] += payload["text"]
        elif event_name == "sub_answer_done":
            # Pull internal-only fields before forwarding to SSE.
            clean_text = payload.pop("_clean_text", None)
            await rt.emit(event_name, payload)
            sq_latencies[payload["index"]] = payload.get("latency_ms", 0)
            if clean_text is not None:
                # Overwrite with the safety-net-cleaned text so synthesis input
                # and persistence never carry hallucinated URLs.
                sq_tokens_acc[payload["index"]] = clean_text
            if "utilization_ratio" in payload:
                util_ratios.append(float(payload["utilization_ratio"]))
                citations_used_total.append(int(payload.get("citations_used", 0)))
                chunks_available_total.append(int(payload.get("chunks_available", 0)))
            remaining -= 1
        else:
            await rt.emit(event_name, payload)

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
            async for token in synthesize_stream(
                rewritten, sub_answers, history=history, history_summary=history_summary,
            ):
                synthesis_tokens.append(token)
                await rt.emit("token", {"text": token})
            run.add_outputs({"answer": "".join(synthesis_tokens)})
    synthesis_ms = int((time.perf_counter() - t_synth) * 1000) if len(sub_queries) > 1 else 0
    rt.record_stage("synthesis_ms", synthesis_ms)

    final_text = "".join(synthesis_tokens) if synthesis_tokens else (sub_answers[0]["answer"] if sub_answers else "")

    # Phase 6 — strip hallucinated URLs from the synthesized final answer too.
    all_allowed_urls = {c["url"] for c in _all_citations}
    final_text, _final_stripped = strip_unknown_links(final_text, all_allowed_urls)

    # Post-hoc citation reconciliation — drop unreferenced citations
    referenced_nums: set = set()
    for text in sq_tokens_acc + [final_text]:
        for m in re.findall(r"\[(\d+)\]", text):
            referenced_nums.add(int(m))
    if referenced_nums:
        _all_citations = [c for c in _all_citations if c["num"] in referenced_nums]

    # Phase 4 — aggregate utilization across the whole answer.
    total_chunks_available = sum(chunks_available_total) if chunks_available_total else 0
    total_citations_used = sum(citations_used_total) if citations_used_total else 0
    median_util = (
        sorted(util_ratios)[len(util_ratios) // 2] if util_ratios else 0.0
    )
    overall_util = (
        round(total_citations_used / total_chunks_available, 3)
        if total_chunks_available else 0.0
    )
    rt.latency_breakdown["chunks_available"] = total_chunks_available
    rt.latency_breakdown["citations_used"] = total_citations_used
    rt.latency_breakdown["utilization_ratio_overall"] = overall_util
    rt.latency_breakdown["utilization_ratio_median"] = round(median_util, 3)

    return {
        "final_answer": final_text,
        "citations": _all_citations,
        "urls": rt.workspace.get("urls") or [],
        "all_chunks": _all_chunks_flat,
        "traces": traces,
        "mode": "search",
    }


# ── Phase 3: fused retrieve+generate node ─────────────────────────────────────

async def node_retrieve_and_generate(state: GraphState, config: Any = None) -> dict:
    """Per-subquery `retrieve → generate` pipeline. Each sub-query starts its
    LLM generation the moment its OWN retrieval finishes — no global retrieve
    barrier. The global citation map is built incrementally so [N] numbering
    stays consistent across sub-answers as they complete in arbitrary order.
    """
    rt = get_runtime()
    chunks = rt.workspace.get("chunks") or []
    all_results_lists = rt.workspace.get("all_results_lists") or []
    per_page_chunks = rt.workspace.get("per_page_chunks") or {}
    per_subquery_urls = rt.workspace.get("per_subquery_urls") or []
    per_sq_extract = rt.workspace.get("per_sq_extract") or []
    per_sq_chunk = rt.workspace.get("per_sq_chunk") or []
    sub_queries: List[str] = state["sub_queries"]
    rewritten = state["rewritten_query"]
    history = state.get("history") or []
    history_summary = state.get("history_summary") or ""
    top_k = state.get("top_k", 8)

    try:
        from pipeline.embed import _DEVICE  # type: ignore
        embed_device = _DEVICE
    except Exception:
        embed_device = "cpu"

    # Bounded concurrency — keeps Jina/LLM connection pressure sane.
    sub_conc = getattr(settings, "subquery_concurrency", max(2, min(8, len(sub_queries))))
    sem = asyncio.Semaphore(sub_conc)

    # Shared, incrementally built citation map (URL → [N]). Guarded so multiple
    # sub-queries finishing retrieve concurrently can't race the assignment.
    citation_lock = asyncio.Lock()
    global_citation_map: dict[str, int] = {}
    best_chunk_by_url: dict[str, Any] = {}

    # Per-subquery accumulators (indexed by subquery index).
    sq_tokens_acc: list = ["" for _ in sub_queries]
    sq_latencies: list = [0] * len(sub_queries)
    sq_clean_text: list = ["" for _ in sub_queries]
    all_ranked_lists: list = [None] * len(sub_queries)
    all_retrieval_results: list = [None] * len(sub_queries)
    per_subquery_citations: list = [[] for _ in sub_queries]
    per_sq_chunks_dicts: list = [[] for _ in sub_queries]
    per_sq_embed_local: list = [None] * len(sub_queries)
    rerank_summary_local: list = [None] * len(sub_queries)
    util_ratios: list[float] = []
    citations_used_total: list[int] = []
    chunks_available_total: list[int] = []

    out_queue: asyncio.Queue = asyncio.Queue()
    t_phase_start = time.perf_counter()

    async def _pipeline_one(index: int, sub_query: str) -> None:
        async with sem:
            # ── retrieve ────────────────────────────────────────────────────
            t_ret = time.perf_counter()
            retrieval = await _traced_retrieve(sub_query, chunks, top_k)
            ranked = retrieval.ranked
            ret_ms = int((time.perf_counter() - t_ret) * 1000)
            all_ranked_lists[index] = ranked
            all_retrieval_results[index] = retrieval

            # candidate count under this sub-query's URLs (for per_subquery_embed)
            sq_results = all_results_lists[index] if index < len(all_results_lists) else []
            sq_urls = {r.url for r in sq_results}
            sq_candidate_count = sum(n for u, n in per_page_chunks.items() if u in sq_urls)
            per_sq_embed_local[index] = {"index": index, "candidate_count": sq_candidate_count}

            # rerank summary entry
            scores = [r.score for r in ranked] or [0.0]
            rerank_summary_local[index] = {
                "index": index, "candidates": len(chunks), "top_k": len(ranked),
                "max_score": round(max(scores), 4), "min_score": round(min(scores), 4),
                "explain": retrieval.explain,
            }

            # ── incrementally assign [N]s for this sub-query's ranked URLs ──
            async with citation_lock:
                for rc in ranked:
                    if rc.chunk.url not in global_citation_map:
                        global_citation_map[rc.chunk.url] = len(global_citation_map) + 1
                    existing = best_chunk_by_url.get(rc.chunk.url)
                    if existing is None or rc.score > existing.score:
                        best_chunk_by_url[rc.chunk.url] = rc
                # Snapshot the map for THIS sub-query's prompt — once a number
                # is assigned it never changes, so passing a snapshot is safe.
                citation_map_snapshot = dict(global_citation_map)

            sq_citations = build_citations(ranked, citation_map_snapshot)
            sq_chunks_dicts = [r.to_dict() for r in ranked]
            per_subquery_citations[index] = sq_citations
            per_sq_chunks_dicts[index] = sq_chunks_dicts
            sq_urls_payload = per_subquery_urls[index] if index < len(per_subquery_urls) else []
            top3 = [{"url": rc.chunk.url, "score": round(rc.score, 4), "title": rc.chunk.title}
                    for rc in ranked[:3]]

            # Emit sub_answer_start (carries per-subquery retrieval signal)
            await rt.emit("sub_answer_start", {
                "index": index, "query": sub_query, "chunks": sq_chunks_dicts,
                "citations": sq_citations, "urls": sq_urls_payload,
                "bm25_top": top3, "dense_top": top3,
                "retrieve_latency_ms": ret_ms,
            })

            # Fire-and-forget upsert of this sub-query's candidates to pgvector.
            asyncio.create_task(upsert_chunks(retrieval.candidates, retrieval.candidate_matrix))

            # ── generate (per-subquery, streaming) ──────────────────────────
            t_sq = time.perf_counter()
            chunks_available = len(ranked)
            allowed_urls = {rc.chunk.url for rc in ranked}
            with ls_trace(
                name=f"Generate sub-answer · {index+1}",
                run_type="llm",
                inputs={"sub_query": sub_query, "chunks_in": chunks_available},
            ) as run:
                collected: list[str] = []
                try:
                    async for token in generate_stream(
                        sub_query, ranked, citation_map_snapshot,
                        history=history, history_summary=history_summary,
                    ):
                        collected.append(token)
                        await out_queue.put(("sub_answer_token", {"index": index, "text": token}))
                    final_sub_text = "".join(collected)
                    cleaned_sub_text, stripped_links = strip_unknown_links(final_sub_text, allowed_urls)
                    used_nums = set(int(m) for m in re.findall(r"\[(\d+)\]", cleaned_sub_text))
                    citations_used = len(used_nums)
                    utilization_ratio = (
                        round(citations_used / chunks_available, 3) if chunks_available else 0.0
                    )
                    run.add_outputs({
                        "answer": cleaned_sub_text,
                        "chunks_available": chunks_available,
                        "citations_used": citations_used,
                        "utilization_ratio": utilization_ratio,
                        "hyperlinks_stripped": stripped_links,
                    })
                    await out_queue.put(("sub_answer_done", {
                        "index": index,
                        "latency_ms": int((time.perf_counter() - t_sq) * 1000),
                        "retrieve_latency_ms": ret_ms,
                        "chunks_available": chunks_available,
                        "citations_used": citations_used,
                        "utilization_ratio": utilization_ratio,
                        "hyperlinks_stripped": stripped_links,
                        "_clean_text": cleaned_sub_text,
                    }))
                except asyncio.CancelledError:
                    await out_queue.put(("sub_answer_done", {
                        "index": index, "latency_ms": 0, "cancelled": True,
                    }))
                    raise
                except Exception as exc:
                    run.end(error=str(exc))
                    await out_queue.put(("sub_answer_done", {
                        "index": index, "latency_ms": int((time.perf_counter() - t_sq) * 1000),
                        "error": str(exc),
                    }))

    # Launch per-subquery pipelines.
    tasks = [asyncio.create_task(_pipeline_one(i, sq)) for i, sq in enumerate(sub_queries)]

    # Drain the multiplexed output queue until every sub-query finishes.
    remaining = len(tasks)
    while remaining > 0:
        event_name, payload = await out_queue.get()
        if event_name == "sub_answer_token":
            await rt.emit(event_name, payload)
            sq_tokens_acc[payload["index"]] += payload["text"]
        elif event_name == "sub_answer_done":
            clean_text = payload.pop("_clean_text", None)
            await rt.emit(event_name, payload)
            sq_latencies[payload["index"]] = payload.get("latency_ms", 0)
            if clean_text is not None:
                sq_clean_text[payload["index"]] = clean_text
                sq_tokens_acc[payload["index"]] = clean_text
            if "utilization_ratio" in payload:
                util_ratios.append(float(payload["utilization_ratio"]))
                citations_used_total.append(int(payload.get("citations_used", 0)))
                chunks_available_total.append(int(payload.get("chunks_available", 0)))
            remaining -= 1
        else:
            await rt.emit(event_name, payload)

    # Ensure all coroutines have returned (no orphans on the event loop).
    await asyncio.gather(*tasks, return_exceptions=True)

    # ── Aggregate retrieve/embed/rerank events for backwards-compat ──────────
    # These are reporting events. The frontend reads them for trace panels but
    # generation has already started/finished, so emitting now is fine.
    total_retrieve_ms = int((time.perf_counter() - t_phase_start) * 1000)
    rt.record_stage("retrieve_ms", total_retrieve_ms)
    per_sq_embed = [e for e in per_sq_embed_local if e is not None]
    await rt.emit("embed_done", {
        "candidate_count": len(chunks), "dim": 384, "device": embed_device,
        "latency_ms": total_retrieve_ms, "per_subquery": per_sq_embed,
    })
    total_retrieved = sum(len(r or []) for r in all_ranked_lists)
    await rt.emit("retrieve_done", {
        "total_chunks": total_retrieved,
        "sub_queries":  len(sub_queries),
        "latency_ms":   total_retrieve_ms,
    })
    await rt.emit("rerank_done", {
        "per_subquery": [s for s in rerank_summary_local if s is not None],
        "latency_ms":   total_retrieve_ms,
    })

    # ── Build full citation list from the (final) global map ────────────────
    _all_citations: list = []
    for url, num in sorted(global_citation_map.items(), key=lambda x: x[1]):
        rc = best_chunk_by_url[url]
        _all_citations.append({
            "num": num, "url": url, "title": rc.chunk.title,
            "snippet": rc.chunk.chunk_text[:300],
        })

    sub_answers = [
        {"query": sub_queries[i], "answer": sq_tokens_acc[i], "citations": per_subquery_citations[i]}
        for i in range(len(sub_queries))
    ]

    _all_chunks_flat: list = []
    for d in per_sq_chunks_dicts:
        _all_chunks_flat.extend(d)

    traces = [
        {"index": i, "query": sub_queries[i],
         "urls": per_subquery_urls[i] if i < len(per_subquery_urls) else [],
         "chunks": per_sq_chunks_dicts[i], "answer": sq_tokens_acc[i],
         "latency_ms": sq_latencies[i],
         "extract_stats": per_sq_extract[i] if i < len(per_sq_extract) else None,
         "chunk_stats":   per_sq_chunk[i]   if i < len(per_sq_chunk)   else None,
         "embed_count":   per_sq_embed_local[i]["candidate_count"] if per_sq_embed_local[i] else None}
        for i in range(len(sub_queries))
    ]

    # Stash for embedding_cleanup
    rt.workspace["all_ranked_lists"] = all_ranked_lists
    rt.workspace["all_retrieval_results"] = all_retrieval_results
    rt.workspace["per_sq_embed"] = per_sq_embed

    # ── Synthesis (only if multi-subquery) ──────────────────────────────────
    # We wait here for all sub-queries — by design, the plan requires synthesis
    # to wait for every sub-answer. Emit `synthesis_waiting` so the UI can show
    # "Waiting for all subquery answers to complete…" before tokens start.
    await rt.emit("synthesis_waiting", {"sub_queries_count": len(sub_queries)})

    t_synth = time.perf_counter()
    synthesis_tokens: list = []
    if len(sub_queries) > 1:
        await rt.emit("synthesis_start", {})
        with ls_trace(
            name="Synthesize final answer",
            run_type="llm",
            inputs={"sub_answer_count": len(sub_answers), "rewritten_query": rewritten[:200]},
        ) as run:
            async for token in synthesize_stream(
                rewritten, sub_answers, history=history, history_summary=history_summary,
            ):
                synthesis_tokens.append(token)
                await rt.emit("token", {"text": token})
            run.add_outputs({"answer": "".join(synthesis_tokens)})
    synthesis_ms = int((time.perf_counter() - t_synth) * 1000) if len(sub_queries) > 1 else 0
    rt.record_stage("synthesis_ms", synthesis_ms)

    final_text = "".join(synthesis_tokens) if synthesis_tokens else (sub_answers[0]["answer"] if sub_answers else "")

    all_allowed_urls = {c["url"] for c in _all_citations}
    final_text, _final_stripped = strip_unknown_links(final_text, all_allowed_urls)

    # Citation reconciliation — drop unreferenced
    referenced_nums: set = set()
    for text in sq_tokens_acc + [final_text]:
        for m in re.findall(r"\[(\d+)\]", text):
            referenced_nums.add(int(m))
    if referenced_nums:
        _all_citations = [c for c in _all_citations if c["num"] in referenced_nums]

    # Phase 4 — aggregate utilization
    total_chunks_available = sum(chunks_available_total) if chunks_available_total else 0
    total_citations_used = sum(citations_used_total) if citations_used_total else 0
    median_util = sorted(util_ratios)[len(util_ratios) // 2] if util_ratios else 0.0
    overall_util = (
        round(total_citations_used / total_chunks_available, 3)
        if total_chunks_available else 0.0
    )
    rt.latency_breakdown["chunks_available"] = total_chunks_available
    rt.latency_breakdown["citations_used"] = total_citations_used
    rt.latency_breakdown["utilization_ratio_overall"] = overall_util
    rt.latency_breakdown["utilization_ratio_median"] = round(median_util, 3)

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
    if state.get("mode") in ("cache", "parametric", "unsupported"):
        # Parametric / unsupported answers have no sources to cache; cache mode
        # was already a hit.
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


# ── Phase 7: rolling memory-state updater (fire-and-forget) ───────────────────
#
# Industry-standard `ConversationSummaryBufferMemory` pattern: keep the last 4
# turns verbatim + a single rolling summary string. When a new turn pushes an
# older turn out of the 4-turn window, fold ONLY that evicted turn into the
# existing summary (O(1) per update — not O(n)).
#
# This runs AFTER answer streaming completes, so user-visible latency is zero.

_RECENT_BUFFER_SIZE = 4


async def _update_memory_state_async(
    session_id: str,
    new_topic: str,
    new_constraints: list,
    current_question: str,
    current_answer: str,
) -> None:
    try:
        # Load prior memory state.
        memory = await sessions.get_memory_state(session_id)
        prev_summary = memory.get("history_summary", "") or ""
        summarized_up_to = int(memory.get("summarized_up_to") or 0)

        # The just-saved turn brings total messages to (count after save).
        # `session_message_count` reflects what's now persisted.
        total_msgs = await sessions.session_message_count(session_id)

        # Eviction window: any message older than the last _RECENT_BUFFER_SIZE
        # is now "evicted" and should be in the summary.
        new_summarized_up_to = max(0, total_msgs - _RECENT_BUFFER_SIZE)
        evict_count = new_summarized_up_to - summarized_up_to

        next_summary = prev_summary
        if evict_count > 0:
            # Fetch the evicted turns. recent_turns returns the LAST N — we
            # need a different slice. Pull all messages and slice; cheap because
            # sessions are bounded in size and this runs after the user reply.
            full = await sessions.get_session(session_id)
            messages = (full or {}).get("messages", []) if full else []
            evicted_slice = messages[summarized_up_to:new_summarized_up_to]
            evicted_turns = [
                {"question": m.get("question", ""), "answer": m.get("answer", "")}
                for m in evicted_slice
                if m.get("question")
            ]
            if evicted_turns:
                next_summary = await incremental_summary(prev_summary, evicted_turns)

        # Topic anchor: if the LLM provided one, persist it; otherwise keep prior.
        active_topic = new_topic.strip() or memory.get("active_topic", "") or ""
        # Constraints: replace with the rewriter's view (it already merged
        # prior + new on a continuation, and reset on a topic switch).
        active_constraints = list(new_constraints) if isinstance(new_constraints, list) else []
        if not active_constraints:
            active_constraints = list(memory.get("active_constraints") or [])

        updated = {
            "history_summary":    next_summary,
            "summarized_up_to":   new_summarized_up_to,
            "active_topic":       active_topic[:120],
            "active_constraints": [str(c)[:60] for c in active_constraints][:6],
        }
        await sessions.update_memory_state(session_id, updated)
    except Exception as exc:
        logger.debug("[memory] update_memory_state_async failed: %s", exc)


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
            # Phase 7 — capture topic/route metadata in the trace blob.
            "is_topic_switch":    state.get("is_topic_switch", False),
            "active_topic":       state.get("new_active_topic", ""),
            "active_constraints": state.get("new_active_constraints", []),
            "route_reason":       state.get("route_reason", ""),
            "route_confidence":   state.get("confidence"),
            "rewrite_confidence": state.get("rewrite_confidence"),
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
        # Phase 7 — fire-and-forget memory-state update: persist the topic
        # anchor AND roll the eviction window through the incremental summary.
        # This runs AFTER answer streaming completes, so it adds zero latency
        # to the user-visible critical path.
        asyncio.create_task(_update_memory_state_async(
            session_id=rt.session_id,
            new_topic=state.get("new_active_topic", "") or "",
            new_constraints=state.get("new_active_constraints", []) or [],
            current_question=state["query"],
            current_answer=state.get("final_answer") or "",
        ))

    await rt.signal_done()
    return {"followups": followups, "latency_breakdown": latency_breakdown}


# ── Routing edges ─────────────────────────────────────────────────────────────

def _route_after_analyze(state: GraphState) -> str:
    # `unsupported` reuses the parametric replay path — the polite-decline message
    # was already produced by the router LLM and lives in state["parametric_answer"].
    if state.get("mode") in ("parametric", "unsupported"):
        return "parametric_answer"
    return "cache_lookup"


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
    # Phase 3 — `retrieve_and_generate` fuses the old retrieve + generate_answers
    # nodes so each sub-query's LLM generation starts the moment its OWN retrieve
    # completes, instead of waiting for all sub-queries' retrievals to finish.
    g.add_node("retrieve_and_generate", node_retrieve_and_generate)
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
                            {"emit_done": "emit_done", "retrieve": "retrieve_and_generate"})
    g.add_edge("retrieve_and_generate", "embedding_cleanup")
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
    history_summary: str = "",
    active_topic: str = "",
    active_constraints: Optional[list] = None,
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
        "history_summary": history_summary or "",
        "active_topic": active_topic or "",
        "active_constraints": list(active_constraints or []),
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
