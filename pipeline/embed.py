"""
Embedding and BM25 utilities.

Embedding model: all-MiniLM-L6-v2 (384-dim, L2-normalised)
  - Loaded lazily, kept as module singleton across requests
  - Device auto-detect: CUDA if available, else CPU. Production CPU-only is safe.

BM25: rank_bm25 BM25Okapi — built in-memory per query
  - Fast for ≤500 chunks; no persistence needed

Async wrappers run encoder/cross-encoder calls on the default executor so the
event loop stays responsive while N concurrent retrieve() calls share the model.

DB persistence: upsert_chunks writes candidate embeddings to web_chunks
  for future pgvector queries and cross-session caching.
"""
import asyncio
import json
import logging
from typing import List, Sequence, Tuple

import numpy as np

import db.client as db
from pipeline.chunk import Chunk

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _pick_device() -> str:
    """CUDA when available; CPU fallback. Never raises — safe at import time."""
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


_DEVICE: str = _pick_device()
_embedding_model = None
_rerank_model    = None


# ── Lazy loaders ────────────────────────────────────────────────────────────────

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[embed] Loading %s on %s…", EMBEDDING_MODEL, _DEVICE)
        try:
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL, device=_DEVICE)
        except Exception as exc:
            logger.warning("[embed] Device %s failed (%s) — falling back to CPU", _DEVICE, exc)
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        logger.info("[embed] Model ready")
    return _embedding_model


def get_rerank_model():
    global _rerank_model
    if _rerank_model is None:
        try:
            from sentence_transformers import CrossEncoder
            logger.info("[embed] Loading cross-encoder on %s…", _DEVICE)
            _rerank_model = CrossEncoder("cross-encoder/ms-marco-TinyBERT-L-2-v2", device=_DEVICE)
            logger.info("[embed] Cross-encoder ready")
        except Exception as exc:
            logger.warning("[embed] Cross-encoder unavailable (%s)", exc)
    return _rerank_model


def preload_models() -> None:
    """Call at app startup to avoid cold-start on first query."""
    get_embedding_model()
    get_rerank_model()


# ── Core functions ───────────────────────────────────────────────────────────────

def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Batch embed. Returns (N, 384) float32 array, L2-normalised.
    Used for both query and candidate chunks.
    """
    model = get_embedding_model()
    return model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False,
    ).astype(np.float32)


async def embed_texts_async(texts: List[str]) -> np.ndarray:
    """Run embed_texts on the default executor so it doesn't block the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_texts, texts)


def cross_encoder_score(pairs: Sequence[Tuple[str, str]]) -> List[float]:
    """Synchronous cross-encoder score; returns float list of length len(pairs)."""
    model = get_rerank_model()
    if model is None or not pairs:
        return [0.0] * len(pairs)
    scores = model.predict(list(pairs))
    return [float(s) for s in scores]


async def cross_encoder_score_async(pairs: Sequence[Tuple[str, str]]) -> List[float]:
    """Async wrapper around cross_encoder_score."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, cross_encoder_score, list(pairs))


def _tokenize(text: str) -> List[str]:
    import re
    return [t for t in re.findall(r"\b[a-zA-Z0-9]+\b", text.lower()) if len(t) >= 2]


def build_bm25(chunks: List[Chunk]):
    """Build BM25Okapi index. Returns (index, tokenised_corpus)."""
    from rank_bm25 import BM25Okapi
    corpus = [_tokenize(c.chunk_text) for c in chunks]
    return BM25Okapi(corpus), corpus


def bm25_search(
    bm25_index,
    query: str,
    chunks: List[Chunk],
    top_k: int,
) -> List[tuple[int, float]]:
    """Return [(chunk_idx, score)] sorted by BM25 score descending."""
    tokens = _tokenize(query)
    scores = bm25_index.get_scores(tokens)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


# ── DB persistence ───────────────────────────────────────────────────────────────

async def upsert_chunks(chunks: List[Chunk], embeddings: np.ndarray) -> None:
    """Upsert candidate chunks + embeddings to web_chunks (fire-and-forget)."""
    rows = [
        (
            chunk.url,
            chunk.title,
            chunk.chunk_index,
            chunk.chunk_text,
            chunk.heading,
            f"[{','.join(f'{v:.6f}' for v in emb.tolist())}]",
            json.dumps(chunk.metadata),
        )
        for chunk, emb in zip(chunks, embeddings)
    ]
    try:
        await db.executemany(
            """
            INSERT INTO web_chunks
              (url, title, chunk_index, chunk_text, heading, embedding, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
            ON CONFLICT (url, chunk_index) DO UPDATE
              SET chunk_text = EXCLUDED.chunk_text,
                  heading    = EXCLUDED.heading,
                  embedding  = EXCLUDED.embedding,
                  metadata   = EXCLUDED.metadata
            """,
            rows,
        )
        logger.debug("[embed] Upserted %d chunks", len(rows))
    except Exception as exc:
        logger.warning("[embed] DB upsert failed: %s", exc)
