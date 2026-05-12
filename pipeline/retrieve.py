"""
Hybrid retrieval: BM25 pre-filter → vector cosine → RRF → cross-encoder rerank.

KEY optimisation (vs naive approach):
  Naïve:     embed ALL chunks → cosine → rerank  [O(n) embeddings, slow on CPU]
  This file: BM25 first → embed only top-N candidates → cosine → RRF → rerank
             For n=85 chunks: embeds ~25 texts instead of 85. ~3-4x faster.

Pipeline:
  1. BM25 (tokenised keyword, O(n), instant) → top EMBED_POOL candidates
  2. Embed query + those candidates only (21-25 texts instead of 85+)
  3. Cosine similarity (O(EMBED_POOL), vectorised numpy)
  4. RRF: merge BM25 and cosine rank lists → top CE_POOL
  5. Cross-encoder (TinyBERT): score CE_POOL pairs → final top_k
  6. Fire-and-forget: upsert candidates to web_chunks (pgvector cache)
"""
import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from typing import List

import numpy as np
from langsmith import traceable

from pipeline.chunk import Chunk
from pipeline.embed import (
    bm25_search,
    build_bm25,
    embed_texts,
    get_rerank_model,
)

_WS_RE = re.compile(r"\s+")

logger = logging.getLogger(__name__)

RRF_K       = 60   # standard constant — larger = smoother fusion
EMBED_POOL  = 24   # BM25 candidates to embed (recall vs. latency tradeoff)
CE_POOL     = 16   # cross-encoder input pool
TOP_K       = 8    # final chunks returned to LLM (also surfaced in UI)

# Defensive dedup — see _dedupe_ranked() docstring.
# Use a generous fingerprint window so chunks that share a heading/intro paragraph
# but diverge later don't collapse to one entry.
_DEDUP_FP_HEAD = 400
_DEDUP_FP_TAIL = 100


@dataclass
class RankedChunk:
    chunk: Chunk
    score: float
    rank: int

    def to_dict(self) -> dict:
        return {
            "url":        self.chunk.url,
            "title":      self.chunk.title,
            "heading":    self.chunk.heading,
            "chunk_text": self.chunk.chunk_text,
            "score":      round(self.score, 4),
            "rank":       self.rank,
        }


@dataclass
class RetrievalResult:
    """Return value of retrieve() — ranked passages plus raw embedding data for deferred upsert."""
    ranked: List[RankedChunk]
    candidates: List[Chunk]
    candidate_matrix: "np.ndarray"
    explain: dict = field(default_factory=dict)
    # explain shape:
    #   total_chunks: int    (input pool)
    #   bm25_pool:    int    (post-BM25 candidates)
    #   ce_pool:      int    (cross-encoder input)
    #   dedup_dropped: int   (post-CE near-duplicates removed)
    #   url_cap_dropped: int (post-CE per-URL diversity cap)
    #   final_kept:   int
    #   score_min, score_max: float


# ── RRF ────────────────────────────────────────────────────────────────────────

def _rrf_merge(
    vec_ranks:  List[tuple[int, float]],   # (local_idx, cosine_score)
    bm25_ranks: List[tuple[int, float]],   # (local_idx, bm25_score)
    n: int,
    k: int = RRF_K,
) -> List[tuple[int, float]]:
    """Reciprocal Rank Fusion over a shared local index space of size n."""
    scores = [0.0] * n
    for pos, (idx, _) in enumerate(vec_ranks):
        scores[idx] += 1.0 / (k + pos + 1)
    for pos, (idx, _) in enumerate(bm25_ranks):
        scores[idx] += 1.0 / (k + pos + 1)
    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
    return [(i, scores[i]) for i in ranked]


# ── Cross-encoder ───────────────────────────────────────────────────────────────

def _cross_encoder_rerank(
    query: str,
    candidates: List[Chunk],
    fallback_scores: List[float],
    top_k: int,
) -> List[tuple[Chunk, float]]:
    ce = get_rerank_model()
    if ce is None or not candidates:
        ranked = sorted(zip(candidates, fallback_scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
    try:
        pairs  = [(query, c.chunk_text[:2_000]) for c in candidates]
        scores = ce.predict(pairs, show_progress_bar=False).tolist()
        ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
    except Exception as exc:
        logger.warning("[retrieve] Cross-encoder failed (%s) — using RRF scores", exc)
        ranked = sorted(zip(candidates, fallback_scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ── Defensive dedup ────────────────────────────────────────────────────────────

def _fingerprint(text: str) -> str:
    """Normalised head+tail fingerprint. Two chunks with identical head AND tail
    (after whitespace collapse) are treated as duplicates. The head-only window
    used to be the only key, which collapsed many distinct chunks that shared an
    intro paragraph — the tail check disambiguates them."""
    norm = _WS_RE.sub(" ", text.lower()).strip()
    head = norm[:_DEDUP_FP_HEAD]
    tail = norm[-_DEDUP_FP_TAIL:] if len(norm) > _DEDUP_FP_HEAD else ""
    return head + "||" + tail


def _dedupe_ranked(ranked: List[RankedChunk]) -> tuple[List[RankedChunk], int]:
    """Dedup by (url, chunk_index) exact key + text fingerprint (head+tail).
    Returns (kept, dropped_count). The previous (url, heading) tuple was removed
    — collapsing every chunk under the same H2 to one was the root cause of the
    'Selected top 1 passage' bug."""
    seen_fp: set[str] = set()
    seen_exact: set[tuple] = set()
    out: List[RankedChunk] = []
    for rc in ranked:
        exact = (rc.chunk.url, rc.chunk.chunk_index)
        if exact in seen_exact:
            continue
        fp = _fingerprint(rc.chunk.chunk_text)
        if fp in seen_fp:
            continue
        seen_exact.add(exact)
        seen_fp.add(fp)
        out.append(rc)
    return out, len(ranked) - len(out)


def _cap_per_url(ranked: List[RankedChunk], top_k: int) -> tuple[List[RankedChunk], int]:
    """Cap per-URL chunk count at ceil(top_k/2) to prevent same-source domination.
    Order-preserving — earlier (higher-scored) chunks stay; later ones from a
    saturated URL are dropped. Returns (kept, dropped_count)."""
    cap = max(1, math.ceil(top_k / 2))
    counts: dict[str, int] = {}
    out: List[RankedChunk] = []
    for rc in ranked:
        n = counts.get(rc.chunk.url, 0)
        if n >= cap:
            continue
        counts[rc.chunk.url] = n + 1
        out.append(rc)
    return out, len(ranked) - len(out)


# ── Traced retrieval sub-stages (visible as separate spans in LangSmith) ──────
# These wrap the inline pipeline stages so each shows up with its proper
# run_type icon. They're thin shims — no behavioral change.

@traceable(run_type="retriever", name="BM25 pre-filter")
def _traced_bm25(query: str, chunks: List[Chunk], top_k: int):
    bm25_index, _ = build_bm25(chunks)
    return bm25_search(bm25_index, query, chunks, top_k=top_k)


@traceable(run_type="retriever", name="Dense embed + cosine")
def _traced_dense_embed_and_score(query: str, candidate_texts: List[str]):
    """Returns (query_vec, candidate_matrix, cosine_sims)."""
    embeddings = embed_texts([query] + candidate_texts)
    query_vec = embeddings[0]
    candidate_matrix = embeddings[1:]
    cosine_sims = (candidate_matrix @ query_vec).tolist()
    return query_vec, candidate_matrix, cosine_sims


@traceable(run_type="chain", name="Reciprocal Rank Fusion")
def _traced_rrf(
    vec_ranks: List[tuple], bm25_ranks: List[tuple], n: int
) -> List[tuple]:
    return _rrf_merge(vec_ranks, bm25_ranks, n)


@traceable(run_type="retriever", name="Cross-encoder rerank")
def _traced_rerank(query: str, candidates: List[Chunk], fallback_scores: List[float], top_k: int):
    return _cross_encoder_rerank(query, candidates, fallback_scores, top_k)


# ── Public API ──────────────────────────────────────────────────────────────────

async def retrieve(
    query: str,
    chunks: List[Chunk],
    top_k: int = TOP_K,
) -> RetrievalResult:
    """Full retrieval pipeline. Returns RetrievalResult with top_k ranked chunks and embedding data."""
    if not chunks:
        return RetrievalResult(
            ranked=[], candidates=[], candidate_matrix=np.zeros((0, 0)),
            explain={"total_chunks": 0, "final_kept": 0},
        )

    loop = asyncio.get_event_loop()

    # ── Stage 1: BM25 pre-filter (no embedding, instant) ───────────────────────
    embed_pool = min(EMBED_POOL, len(chunks))
    bm25_ranked = await loop.run_in_executor(None, _traced_bm25, query, chunks, embed_pool)
    # bm25_ranked: [(global_chunk_idx, score)] sorted desc

    # Map to local index space for the candidate list
    candidate_global_idx = [i for i, _ in bm25_ranked]
    candidates = [chunks[i] for i in candidate_global_idx]

    # ── Stage 2: Embed query + BM25 candidates only + cosine score ───────────
    candidate_texts = [c.chunk_text for c in candidates]
    query_vec, candidate_matrix, cosine_sims = await loop.run_in_executor(
        None, _traced_dense_embed_and_score, query, candidate_texts
    )

    # ── Stage 3: Rank by cosine ─────────────────────────────────────────────
    vec_local_ranks = sorted(
        range(len(candidates)), key=lambda i: cosine_sims[i], reverse=True
    )
    vec_ranks_list  = [(i, cosine_sims[i]) for i in vec_local_ranks]

    # BM25 local ranks (same local index space)
    bm25_local_ranks = [(i, s) for i, (_, s) in enumerate(bm25_ranked)]

    # ── Stage 4: RRF ────────────────────────────────────────────────────────────
    rrf_ranks = _traced_rrf(vec_ranks_list, bm25_local_ranks, n=len(candidates))

    # ── Stage 5: Cross-encoder rerank (sync, thread pool) ───────────────────────
    # Run CE on the full pool, then apply dedup + per-URL cap, THEN trim to top_k.
    # This lets the diversity cap actually drop saturated-URL chunks before the
    # final cut, instead of after.
    ce_pool   = min(CE_POOL, len(candidates))
    ce_chunks = [candidates[i] for i, _ in rrf_ranks[:ce_pool]]
    ce_scores = [s            for _, s in rrf_ranks[:ce_pool]]

    reranked = await loop.run_in_executor(
        None, _traced_rerank, query, ce_chunks, ce_scores, ce_pool,
    )

    pre_filter = [
        RankedChunk(chunk=chunk, score=score, rank=i)
        for i, (chunk, score) in enumerate(reranked)
    ]

    # Defensive dedup — catches overlap-window near-duplicates that survived RRF.
    deduped, dedup_dropped = _dedupe_ranked(pre_filter)

    # Per-URL diversity cap.
    capped, url_cap_dropped = _cap_per_url(deduped, top_k)

    # Final trim + re-rank.
    result = [
        RankedChunk(chunk=rc.chunk, score=rc.score, rank=i)
        for i, rc in enumerate(capped[:top_k])
    ]

    scores = [r.score for r in result] or [0.0]
    explain = {
        "total_chunks":    len(chunks),
        "bm25_pool":       len(candidates),
        "ce_pool":         ce_pool,
        "dedup_dropped":   dedup_dropped,
        "url_cap_dropped": url_cap_dropped,
        "final_kept":      len(result),
        "score_min":       round(min(scores), 4),
        "score_max":       round(max(scores), 4),
    }

    logger.info(
        "[retrieve] %d total → BM25 pool=%d → embed=%d → CE pool=%d → dedup-drop=%d → url-cap-drop=%d → top=%d",
        len(chunks), embed_pool, len(candidates), ce_pool,
        dedup_dropped, url_cap_dropped, len(result),
    )
    for r in result:
        logger.debug("  #%d score=%.4f  %s  [%s]", r.rank, r.score, r.chunk.url[:60], r.chunk.heading)

    return RetrievalResult(
        ranked=result,
        candidates=candidates,
        candidate_matrix=candidate_matrix,
        explain=explain,
    )
