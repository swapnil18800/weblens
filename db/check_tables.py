import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()

async def run():
    conn = await asyncpg.connect(dsn=os.getenv("DATABASE_URL"), statement_cache_size=0)
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name IN ('sessions','session_messages') "
        "ORDER BY table_name, ordinal_position"
    )
    for r in rows:
        print(r["table_name"], "|", r["column_name"])
    await conn.close()

asyncio.run(run())
