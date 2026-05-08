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
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('page_cache', 'web_chunks')"
        )
        for t in tables:
            logger.info(f"  ✓ table: {t['tablename']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
