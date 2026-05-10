"""
Session persistence — rag_sessions + rag_session_messages.
All public functions are fire-and-forget safe (log on failure, never raise).
"""
import json
import logging
from typing import List, Optional

import db.client as db

logger = logging.getLogger(__name__)


def _j(val, default):
    """Decode a value that may be a raw JSON string (PgBouncer mode) or already parsed."""
    if val is None:
        return default
    if isinstance(val, (str, bytes)):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val


async def ensure_session(session_id: str) -> None:
    try:
        await db.execute(
            "INSERT INTO rag_sessions (session_id) VALUES ($1) ON CONFLICT DO NOTHING",
            session_id,
        )
    except Exception as exc:
        logger.warning("[session] ensure_session failed: %s", exc)


async def update_session_title(session_id: str, title: str) -> None:
    try:
        await db.execute(
            "UPDATE rag_sessions SET title = $1 WHERE session_id = $2 AND title IS NULL",
            title[:120],
            session_id,
        )
    except Exception as exc:
        logger.warning("[session] update_session_title failed: %s", exc)


async def update_session_title_force(session_id: str, title: str) -> None:
    """Always overwrite the title (used for LLM-upgraded titles)."""
    try:
        await db.execute(
            "UPDATE rag_sessions SET title = $1 WHERE session_id = $2",
            title[:120],
            session_id,
        )
    except Exception as exc:
        logger.warning("[session] update_session_title_force failed: %s", exc)


async def update_session_title_if(session_id: str, new_title: str, was_title: str) -> None:
    """Overwrite the title only if it currently equals `was_title`.

    Used to upgrade the heuristic title to the LLM-generated one without
    clobbering a title that has already been changed by another turn.
    """
    try:
        await db.execute(
            "UPDATE rag_sessions SET title = $1 WHERE session_id = $2 AND title = $3",
            new_title[:120],
            session_id,
            was_title[:120],
        )
    except Exception as exc:
        logger.warning("[session] update_session_title_if failed: %s", exc)


async def recent_turns(session_id: str, limit: int = 4) -> List[dict]:
    """Return the most recent N turns (oldest→newest) for follow-up resolution."""
    try:
        rows = await db.fetch(
            """
            SELECT question, answer, created_at
            FROM rag_session_messages
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
        # Reverse to chronological order
        return [
            {"question": r["question"], "answer": r["answer"]}
            for r in reversed(rows)
        ]
    except Exception as exc:
        logger.warning("[session] recent_turns failed: %s", exc)
        return []


async def session_message_count(session_id: str) -> int:
    """Return how many messages the session already has (0 if missing)."""
    try:
        row = await db.fetchrow(
            "SELECT COUNT(*) AS n FROM rag_session_messages WHERE session_id = $1",
            session_id,
        )
        return int(row["n"]) if row else 0
    except Exception as exc:
        logger.warning("[session] session_message_count failed: %s", exc)
        return 0


async def save_message(
    session_id: str,
    question: str,
    answer: str,
    citations: list,
    urls: list,
    chunks: list,
    latency_breakdown: dict,
    total_latency_ms: int,
    sub_queries: list | None = None,
    traces: list | None = None,
) -> None:
    """Insert a completed Q&A message with full pipeline trace."""
    try:
        await db.execute(
            """
            INSERT INTO rag_session_messages
              (session_id, question, answer, citations, urls, chunks,
               latency_breakdown, total_latency_ms, sub_queries, traces)
            VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7::jsonb,$8,$9::jsonb,$10::jsonb)
            """,
            session_id,
            question,
            answer,
            json.dumps(citations),
            json.dumps(urls),
            json.dumps(chunks),
            json.dumps(latency_breakdown),
            total_latency_ms,
            json.dumps(sub_queries or []),
            json.dumps(traces or []),
        )
        await update_session_title(session_id, question)
    except Exception as exc:
        logger.warning("[session] save_message failed: %s", exc)


async def get_session(session_id: str) -> Optional[dict]:
    """Load a session with all messages ordered by created_at."""
    try:
        rows = await db.fetch(
            """
            SELECT id, question, answer, citations, urls, chunks,
                   latency_breakdown, total_latency_ms, sub_queries, traces, created_at
            FROM rag_session_messages
            WHERE session_id = $1
            ORDER BY created_at ASC
            """,
            session_id,
        )
        messages = [
            {
                "id": r["id"],
                "question": r["question"],
                "answer": r["answer"],
                "citations": _j(r["citations"], []),
                "urls": _j(r["urls"], []),
                "chunks": _j(r["chunks"], []),
                "latency_breakdown": _j(r["latency_breakdown"], {}),
                "total_latency_ms": r["total_latency_ms"],
                "sub_queries": _j(r["sub_queries"], []),
                "traces": _j(r["traces"], []),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
        return {"session_id": session_id, "messages": messages}
    except Exception as exc:
        logger.warning("[session] get_session failed: %s", exc)
        return None


async def delete_session(session_id: str) -> bool:
    """Delete a session and all its messages (CASCADE). Returns True if a row was deleted."""
    try:
        result = await db.execute(
            "DELETE FROM rag_sessions WHERE session_id = $1",
            session_id,
        )
        # asyncpg returns a status string like "DELETE 1"
        if isinstance(result, str) and result.startswith("DELETE "):
            return int(result.split()[-1]) > 0
        return True
    except Exception as exc:
        logger.warning("[session] delete_session failed: %s", exc)
        return False


async def list_sessions(limit: int = 50) -> List[dict]:
    """List recent sessions with title, message count, and last_active."""
    try:
        rows = await db.fetch(
            """
            SELECT
                s.session_id,
                COALESCE(
                    s.title,
                    (SELECT question FROM rag_session_messages
                     WHERE session_id = s.session_id
                     ORDER BY created_at ASC LIMIT 1),
                    'Untitled'
                ) AS title,
                COUNT(m.id) AS message_count,
                MAX(m.created_at) AS last_active,
                s.created_at
            FROM rag_sessions s
            LEFT JOIN rag_session_messages m ON m.session_id = s.session_id
            GROUP BY s.session_id, s.title, s.created_at
            ORDER BY last_active DESC NULLS LAST, s.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "session_id": r["session_id"],
                "title": r["title"],
                "message_count": r["message_count"] or 0,
                "last_active": r["last_active"].isoformat() if r["last_active"] else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[session] list_sessions failed: %s", exc)
        return []
