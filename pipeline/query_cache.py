"""
Semantic query cache.

Reuses the project's existing all-MiniLM-L6-v2 embedding model to embed
incoming queries, looks them up via pgvector cosine ANN, and replays cached
answers when similarity ≥ threshold.

Gated on `settings.semantic_cache_enabled` — when False the whole module is a
no-op so devs iterating on prompts don't get poisoned by stale cached answers.

Hard 250 ms timeout on lookup so a missed cache never blocks the request path
(a 250 ms blocking lookup is acceptable in the worst case; the pipeline-saved
~25 s makes the trade-off heavily positive on a hit).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Optional

import db.client as db
from config import settings
from pipeline.embed import embed_texts_async
from pipeline.token_tracker import get_tracker  # noqa: F401 (consumers may use)

logger = logging.getLogger(__name__)


def _normalize(query: str) -> str:
    """Light normalization so trivial spacing/case differences hash to the same key."""
    return re.sub(r"\s+", " ", query.strip().lower())


def _hash(query_norm: str) -> str:
    return hashlib.sha256(query_norm.encode("utf-8")).hexdigest()[:32]


async def lookup(query: str) -> Optional[dict]:
    """Return a cache hit dict (answer, citations, urls, sub_queries, mode) or None.

    Order of attempts:
      1. Exact-hash match (fast, no embedding needed).
      2. ANN cosine similarity against query embeddings, accept if ≥ threshold.

    Both wrapped in a single hard timeout to bound worst-case latency. The
    caller decides whether to call this at all — there is NO settings gate
    here, because per-request overrides need to be able to enable lookups
    even when the global setting is off (eval `paraphrase_cache` category).
    """
    qn = _normalize(query)
    qh = _hash(qn)

    try:
        result = await asyncio.wait_for(
            _lookup_inner(qn, qh, query),
            timeout=settings.semantic_cache_lookup_timeout_ms / 1000.0,
        )
        logger.info("[cache] lookup result hash=%s hit=%s", qh[:8], result is not None)
        return result
    except asyncio.TimeoutError:
        logger.info("[cache] lookup TIMED OUT (>%dms) hash=%s",
                    settings.semantic_cache_lookup_timeout_ms, qh[:8])
        return None
    except Exception as exc:
        logger.info("[cache] lookup failed: %s", exc)
        return None


async def _lookup_inner(qn: str, qh: str, original_query: str) -> Optional[dict]:
    # Exact-hash hit
    row = await db.fetchrow(
        """
        SELECT query_text, answer, citations, urls, sub_queries, mode, latency_breakdown
        FROM query_cache
        WHERE query_hash = $1 AND expires_at > NOW()
        """,
        qh,
    )
    if row:
        await db.execute(
            "UPDATE query_cache SET hit_count = hit_count + 1, last_hit_at = NOW() WHERE query_hash = $1",
            qh,
        )
        return _row_to_hit(row, similarity=1.0, exact=True)

    # ANN cosine — pgvector `<=>` is distance, similarity = 1 - distance
    emb = await embed_texts_async([original_query])
    if emb is None or len(emb) == 0:
        return None
    vec = emb[0].tolist()
    threshold = settings.semantic_cache_sim_threshold

    row = await db.fetchrow(
        """
        SELECT query_text, query_hash, answer, citations, urls, sub_queries, mode, latency_breakdown,
               1 - (query_embedding <=> $1::vector) AS similarity
        FROM query_cache
        WHERE expires_at > NOW()
        ORDER BY query_embedding <=> $1::vector
        LIMIT 1
        """,
        json.dumps(vec),
    )
    if row and float(row["similarity"]) >= threshold:
        await db.execute(
            "UPDATE query_cache SET hit_count = hit_count + 1, last_hit_at = NOW() WHERE query_hash = $1",
            row["query_hash"],
        )
        return _row_to_hit(row, similarity=float(row["similarity"]), exact=False)
    return None


def _row_to_hit(row: Any, similarity: float, exact: bool) -> dict:
    return {
        "query_text":  row["query_text"],
        "answer":      row["answer"],
        "citations":   _json_loads(row["citations"]),
        "urls":        _json_loads(row["urls"]),
        "sub_queries": _json_loads(row["sub_queries"]),
        "mode":        row["mode"],
        "latency_breakdown": _json_loads(row["latency_breakdown"]),
        "similarity":  similarity,
        "exact":       exact,
    }


def _json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


async def insert(
    *,
    query: str,
    answer: str,
    citations: list,
    urls: list,
    sub_queries: list,
    mode: str,
    latency_breakdown: dict,
    ttl_hours: Optional[int] = None,
) -> None:
    """Fire-and-forget insert. Never raises. Caller gates whether to call this."""
    if not answer or not answer.strip():
        return

    ttl = ttl_hours if ttl_hours is not None else settings.semantic_cache_ttl_hours
    qn = _normalize(query)
    qh = _hash(qn)

    try:
        emb = await embed_texts_async([query])
        vec = emb[0].tolist() if emb is not None and len(emb) else None
        if vec is None:
            return
        await db.execute(
            """
            INSERT INTO query_cache
              (query_hash, query_text, query_embedding, answer, citations, urls, sub_queries,
               mode, latency_breakdown, expires_at)
            VALUES ($1, $2, $3::vector, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9::jsonb,
                    NOW() + ($10::int * INTERVAL '1 hour'))
            ON CONFLICT (query_hash) DO UPDATE SET
              answer = EXCLUDED.answer,
              citations = EXCLUDED.citations,
              urls = EXCLUDED.urls,
              sub_queries = EXCLUDED.sub_queries,
              mode = EXCLUDED.mode,
              latency_breakdown = EXCLUDED.latency_breakdown,
              expires_at = EXCLUDED.expires_at
            """,
            qh, query, json.dumps(vec), answer,
            json.dumps(citations or []), json.dumps(urls or []),
            json.dumps(sub_queries or []), mode,
            json.dumps(latency_breakdown or {}), ttl,
        )
        logger.info("[cache] inserted: %r (mode=%s, ttl=%dh)", query[:60], mode, ttl)
    except Exception as exc:
        logger.debug("[cache] insert failed: %s", exc)


async def delete_by_query_text(query: str) -> int:
    """Delete cache rows whose normalized query text matches `query` exactly.

    Used by the eval harness to clean up its own paraphrase_cache writes so
    successive eval runs don't see leaked state.
    """
    qn = _normalize(query)
    qh = _hash(qn)
    try:
        result = await db.execute(
            "DELETE FROM query_cache WHERE query_hash = $1", qh,
        )
        if isinstance(result, str) and result.startswith("DELETE "):
            return int(result.split()[-1])
    except Exception as exc:
        logger.debug("[cache] delete_by_query_text failed: %s", exc)
    return 0


async def delete_expired() -> int:
    """Drop expired rows. Cheap; safe to call periodically."""
    try:
        result = await db.execute("DELETE FROM query_cache WHERE expires_at < NOW()")
        if isinstance(result, str) and result.startswith("DELETE "):
            return int(result.split()[-1])
    except Exception as exc:
        logger.debug("[cache] delete_expired failed: %s", exc)
    return 0


async def clear_all() -> int:
    """Wipe the entire query_cache. Used by the eval harness to ensure clean state."""
    try:
        result = await db.execute("DELETE FROM query_cache")
        if isinstance(result, str) and result.startswith("DELETE "):
            return int(result.split()[-1])
    except Exception as exc:
        logger.debug("[cache] clear_all failed: %s", exc)
    return 0
