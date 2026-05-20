"""
Idempotent migration for rag_sessions + rag_session_messages.
  python db/migrate_sessions.py

Safe to run multiple times — all statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
"""
import asyncio
import asyncpg
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

STMTS = [
    """
    CREATE TABLE IF NOT EXISTS rag_sessions (
        session_id  TEXT PRIMARY KEY,
        title       TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_session_messages (
        id                BIGSERIAL PRIMARY KEY,
        session_id        TEXT NOT NULL REFERENCES rag_sessions(session_id) ON DELETE CASCADE,
        question          TEXT NOT NULL,
        answer            TEXT DEFAULT '',
        citations         JSONB DEFAULT '[]',
        urls              JSONB DEFAULT '[]',
        chunks            JSONB DEFAULT '[]',
        latency_breakdown JSONB DEFAULT '{}',
        total_latency_ms  INTEGER DEFAULT 0,
        sub_queries       JSONB DEFAULT '[]',
        traces            JSONB DEFAULT '[]',
        created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS rag_session_messages_sid_idx
        ON rag_session_messages (session_id, created_at)
    """,
    # Idempotent column additions for existing tables
    "ALTER TABLE rag_sessions ADD COLUMN IF NOT EXISTS title TEXT",
    "ALTER TABLE rag_session_messages ADD COLUMN IF NOT EXISTS traces JSONB DEFAULT '[]'",
    # Phase 7: per-session conversational memory state — holds the rolling
    # history summary, the active topic anchor, active constraints, and the
    # count of messages already incorporated into the summary. JSON shape:
    #   {"history_summary": str, "summarized_up_to": int,
    #    "active_topic": str, "active_constraints": [str]}
    "ALTER TABLE rag_sessions ADD COLUMN IF NOT EXISTS memory_state JSONB DEFAULT '{}'",
]


async def main() -> None:
    conn = await asyncpg.connect(dsn=os.getenv("DATABASE_URL"), statement_cache_size=0)
    try:
        for stmt in STMTS:
            await conn.execute(stmt)
            print(f"OK: {stmt.strip()[:70]}…")
        print("\nMigration complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
