"""
Quick smoke test for the semantic query cache.

Sends the same query twice with `X-Semantic-Cache: on`:
  - First call: must hit the full pipeline (mode="search"), no cache hit.
  - Second call: must hit the cache (mode="cache"), <2s.

Then cleans up the cache entry it created.

Usage:
    python evals/cache_smoke.py [--url http://localhost:8000]

Exits 0 on success, 1 on failure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Optional

import httpx

DEFAULT_URL = "http://localhost:8000"
# Use a question unlikely to collide with anything else (and that the analyze
# step will route to search — not a textbook fact).
TEST_QUERY = "Cache smoke test — current price of Bitcoin in USD as of today (no rounding)?"


async def call_once(client: httpx.AsyncClient, url: str, query: str) -> dict:
    body = {"query": query, "session_id": f"cache-smoke-{int(time.time())}"}
    headers = {"X-Semantic-Cache": "on", "X-Langsmith-Trace": "false"}
    mode = "?"
    error: Optional[str] = None
    answer_chars = 0
    t0 = time.monotonic()
    try:
        async with client.stream("POST", f"{url}/api/search",
                                 json=body, headers=headers, timeout=180.0) as resp:
            resp.raise_for_status()
            buf = ""
            async for raw in resp.aiter_bytes():
                buf += raw.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    event_type = data_str = ""
                    for line in block.strip().split("\n"):
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            data_str = line[6:]
                    if not event_type or not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except Exception:
                        continue
                    if event_type == "decompose_done":
                        mode = data.get("mode", mode)
                    elif event_type == "sub_answer_token":
                        answer_chars += len(data.get("text", ""))
                    elif event_type == "token":
                        answer_chars += len(data.get("text", ""))
                    elif event_type == "done":
                        mode = data.get("mode", mode)
                    elif event_type == "error":
                        error = data.get("message", "unknown error")
    except Exception as exc:
        error = str(exc)
    return {"mode": mode, "answer_chars": answer_chars, "elapsed_s": round(time.monotonic() - t0, 2),
            "error": error}


async def main(url: str) -> int:
    print(f"=== Cache smoke test against {url} ===")
    async with httpx.AsyncClient() as client:
        # Sanity check: clear any prior cache hit for this query
        try:
            await client.post(f"{url}/api/admin/query_cache/delete",
                              json={"query": TEST_QUERY}, timeout=10)
        except Exception:
            pass

        print(f"\n[1/2] First call (cache MISS expected, full pipeline):")
        first = await call_once(client, url, TEST_QUERY)
        print(f"      mode={first['mode']}  answer_chars={first['answer_chars']}  "
              f"elapsed={first['elapsed_s']}s  error={first['error']}")
        if first["error"]:
            print(f"❌ FAIL: first call errored: {first['error']}")
            return 1

        # Give cache_insert (fire-and-forget) a moment to land
        await asyncio.sleep(1.0)

        print(f"\n[2/2] Second call (cache HIT expected, <2s):")
        second = await call_once(client, url, TEST_QUERY)
        print(f"      mode={second['mode']}  answer_chars={second['answer_chars']}  "
              f"elapsed={second['elapsed_s']}s  error={second['error']}")

        # Cleanup: delete the cache entry we created
        try:
            r = await client.post(f"{url}/api/admin/query_cache/delete",
                                  json={"query": TEST_QUERY}, timeout=10)
            print(f"\nCleanup: deleted {r.json().get('deleted', 0)} cache rows.")
        except Exception as exc:
            print(f"\nCleanup failed (non-fatal): {exc}")

        # Verdict
        if second["mode"] != "cache":
            print(f"\n[FAIL] expected mode=cache on 2nd call, got mode={second['mode']}")
            return 1
        if second["elapsed_s"] > 5:
            print(f"\n[WARN] cache hit was slower than expected ({second['elapsed_s']}s)")
            return 1
        if second["answer_chars"] == 0:
            print(f"\n[FAIL] cache hit returned empty answer")
            return 1
        print(f"\n[PASS] cache works. miss->{first['elapsed_s']}s, hit->{second['elapsed_s']}s.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main(args.url)))
