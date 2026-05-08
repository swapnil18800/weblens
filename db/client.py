"""
asyncpg connection pool — created once at startup, shared across all requests.
statement_cache_size=0 required for PgBouncer transaction-mode (Supabase pooler).
"""
import logging
from typing import Optional, Any, List
import asyncpg
from config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def create_pool() -> asyncpg.Pool:
    global _pool
    logger.info("[db] Creating connection pool…")
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        command_timeout=60,
        statement_cache_size=0,  # pgbouncer transaction-mode compatibility
    )
    logger.info(f"[db] Pool ready (min={settings.db_pool_min} max={settings.db_pool_max})")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        logger.info("[db] Pool closed")
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call create_pool() at startup")
    return _pool


async def fetch(query: str, *args, timeout: float = 30.0) -> List[asyncpg.Record]:
    return await get_pool().fetch(query, *args, timeout=timeout)


async def fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    return await get_pool().fetchrow(query, *args)


async def fetchval(query: str, *args) -> Any:
    return await get_pool().fetchval(query, *args)


async def execute(query: str, *args) -> str:
    return await get_pool().execute(query, *args)


async def executemany(query: str, args_list: list) -> None:
    await get_pool().executemany(query, args_list)
