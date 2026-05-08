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
from dataclasses import dataclass
from typing import List

import numpy as np

from pipeline.chunk import Chunk
from pipeline.embed import (
    bm25_search,
    build_bm25,
    embed_texts,
    get_rerank_model,
    upsert_chunks,
)

logger = logging.getLogger(__name__)

RRF_K       = 60   # standard constant — larger = smoother fusion
EMBED_POOL  = 24   # BM25 candidates to embed (recall vs. latency tradeoff)
CE_POOL     = 16   # cross-encoder input pool
TOP_K       = 10   # final chunks returned to LLM


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


# ── Public API ──────────────────────────────────────────────────────────────────

async def retrieve(
    query: str,
    chunks: List[Chunk],
    top_k: int = TOP_K,
) -> List[RankedChunk]:
    """Full retrieval pipeline. Returns top_k RankedChunks."""
    if not chunks:
        return []

    loop = asyncio.get_event_loop()

    # ── Stage 1: BM25 pre-filter (no embedding, instant) ───────────────────────
    bm25_index, _ = await loop.run_in_executor(None, build_bm25, chunks)
    embed_pool = min(EMBED_POOL, len(chunks))
    bm25_ranked = bm25_search(bm25_index, query, chunks, top_k=embed_pool)
    # bm25_ranked: [(global_chunk_idx, score)] sorted desc

    # Map to local index space for the candidate list
    candidate_global_idx = [i for i, _ in bm25_ranked]
    candidates = [chunks[i] for i in candidate_global_idx]

    # ── Stage 2: Embed query + BM25 candidates only ─────────────────────────────
    texts = [query] + [c.chunk_text for c in candidates]
    embeddings = await loop.run_in_executor(None, embed_texts, texts)
    query_vec        = embeddings[0]           # (384,)
    candidate_matrix = embeddings[1:]          # (EMBED_POOL, 384)

    # ── Stage 3: Cosine similarity over candidates ──────────────────────────────
    cosine_sims = (candidate_matrix @ query_vec).tolist()   # dot = cosine (normalised)
    vec_local_ranks = sorted(
        range(len(candidates)), key=lambda i: cosine_sims[i], reverse=True
    )
    vec_ranks_list  = [(i, cosine_sims[i]) for i in vec_local_ranks]

    # BM25 local ranks (same local index space)
    bm25_local_ranks = [(i, s) for i, (_, s) in enumerate(bm25_ranked)]

    # ── Stage 4: RRF ────────────────────────────────────────────────────────────
    rrf_ranks = _rrf_merge(vec_ranks_list, bm25_local_ranks, n=len(candidates))

    # ── Stage 5: Cross-encoder rerank (sync, thread pool) ───────────────────────
    ce_pool   = min(CE_POOL, len(candidates))
    ce_chunks = [candidates[i] for i, _ in rrf_ranks[:ce_pool]]
    ce_scores = [s            for _, s in rrf_ranks[:ce_pool]]

    reranked = await loop.run_in_executor(
        None, _cross_encoder_rerank, query, ce_chunks, ce_scores, top_k
    )

    result = [
        RankedChunk(chunk=chunk, score=score, rank=i)
        for i, (chunk, score) in enumerate(reranked)
    ]

    # ── Stage 6: Upsert candidates to DB (non-blocking) ─────────────────────────
    asyncio.create_task(upsert_chunks(candidates, candidate_matrix))

    logger.info(
        "[retrieve] %d total → BM25 pool=%d → embed=%d → CE pool=%d → top=%d",
        len(chunks), embed_pool, len(candidates), ce_pool, len(result),
    )
    for r in result:
        logger.debug("  #%d score=%.4f  %s  [%s]", r.rank, r.score, r.chunk.url[:60], r.chunk.heading)

    return result
