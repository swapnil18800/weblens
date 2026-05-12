"""
Run once to create web_chunks and page_cache tables.
  python db/setup.py
"""
import asyncio
import logging
from pathlib import Path
import asyncpg
from dotenv import load_dotenv
import os

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set in .env")

    schema_sql = (Path(__file__).parent / "schema.sql").read_text()

    logger.info("Connecting to database…")
    conn = await asyncpg.connect(dsn=database_url, statement_cache_size=0)
    try:
        logger.info("Applying schema…")
        await conn.execute(schema_sql)
        logger.info("Schema applied successfully.")

        # Verify tables exist
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('page_cache', 'web_chunks', 'rag_sessions', 'rag_session_messages', 'query_cache')"
        )
        for t in tables:
            logger.info(f"  ✓ table: {t['tablename']}")

        # ── One-shot cleanup: enforce shorter TTL on existing cache rows ─────
        # Existing rows still carry the old 24h / 6h TTLs from their insert
        # time. Cap them to the new defaults (2h) and drop anything already
        # expired so the cache doesn't grow unbounded.
        logger.info("Enforcing TTL caps on existing cache rows…")
        await conn.execute(
            "UPDATE page_cache "
            "SET expires_at = LEAST(expires_at, fetched_at + INTERVAL '2 hours') "
            "WHERE expires_at > fetched_at + INTERVAL '2 hours'"
        )
        n_page_deleted = await conn.execute("DELETE FROM page_cache WHERE expires_at < NOW()")
        await conn.execute(
            "UPDATE query_cache "
            "SET expires_at = LEAST(expires_at, created_at + INTERVAL '2 hours') "
            "WHERE expires_at > created_at + INTERVAL '2 hours'"
        )
        n_query_deleted = await conn.execute("DELETE FROM query_cache WHERE expires_at < NOW()")
        logger.info(f"  ↳ page_cache: {n_page_deleted}")
        logger.info(f"  ↳ query_cache: {n_query_deleted}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
