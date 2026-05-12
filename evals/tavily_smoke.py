"""Tavily API smoke test — verify the key in .env actually works.

Usage:
    python evals/tavily_smoke.py
    python evals/tavily_smoke.py "custom query"
    TAVILY_API_KEY=tvly-... python evals/tavily_smoke.py   # override key

Exits 0 on success, 1 on any failure. Prints the HTTP status, the raw response
body (truncated), and the parsed URL list so you can tell auth/quota/timeout
failures apart at a glance.

The Tavily SDK swallows non-200 responses inside a generic exception, which
makes 4xx/5xx hard to debug. This script does both:
  1) raw `requests.post` to https://api.tavily.com/search  (shows HTTP status)
  2) tavily.TavilyClient(...).search(...)                  (matches our app)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root regardless of cwd, and put the repo root on
# sys.path so `from config import settings` works when run as `python evals/tavily_smoke.py`.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_QUERY = "What is the current population of Brazil?"


def banner(s: str) -> None:
    print(f"\n-------- {s} --------")


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY

    # Read the key the SAME way the app does — settings cached at import.
    # Then compare against what's actually in .env on disk to surface the
    # "stale process / shell override" trap.
    from config import settings  # noqa: PLC0415  (after dotenv loaded)
    app_key = settings.tavily_api_key or ""
    env_key = os.environ.get("TAVILY_API_KEY", "")
    dotenv_key = ""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("TAVILY_API_KEY"):
                _, _, v = line.partition("=")
                # Strip surrounding whitespace, quotes, AND inline comments —
                # python-dotenv ignores `# ...` after the value, so if our
                # parser doesn't, we'd falsely report a longer key than the
                # app actually sees.
                v = v.strip()
                if v and v[0] in "\"'":
                    quote = v[0]
                    end = v.find(quote, 1)
                    v = v[1:end] if end > 0 else v[1:]
                else:
                    # Cut inline comment introduced by ` # ` or trailing `#`.
                    hash_idx = v.find("#")
                    if hash_idx >= 0:
                        v = v[:hash_idx]
                    v = v.strip()
                dotenv_key = v
                break

    def mask(k: str) -> str:
        if not k:
            return "<missing>"
        return f"{k[:8]}...{k[-4:]}  (length={len(k)})" if len(k) > 12 else "***"

    banner("Environment")
    print(f"  cwd:               {Path.cwd()}")
    print(f"  .env path:         {env_path}  exists={env_path.exists()}")
    print(f"  key in os.environ: {mask(env_key)}")
    print(f"  key in .env file:  {mask(dotenv_key)}")
    print(f"  key the app uses:  {mask(app_key)}    (config.settings.tavily_api_key)")
    if env_key and dotenv_key and env_key != dotenv_key:
        print("  WARN: os.environ and .env DISAGREE. os.environ wins for the app "
              "because app.py uses load_dotenv(..., override=False).")
        print("     -> unset TAVILY_API_KEY in your shell, or run with "
              "load_dotenv(..., override=True), or restart from a fresh shell.")
    if not app_key:
        print("\nFAIL: app would see no TAVILY_API_KEY")
        return 1
    print(f"  query:             {query!r}")
    key = app_key

    # ── 1) Raw HTTP call ───────────────────────────────────────────────────
    banner("Raw POST /search")
    try:
        import requests
    except ImportError:
        print("  requests not installed — `pip install requests`")
        return 1

    body = {
        "api_key":         key,
        "query":           query,
        "search_depth":    "basic",
        "max_results":     5,
        "include_answer":  False,
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(TAVILY_URL, json=body, timeout=20)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  HTTP {r.status_code}  ({elapsed:.0f} ms)")
        ct = r.headers.get("content-type", "")
        print(f"  content-type: {ct}")
        raw = r.text
        print(f"  body (first 800 chars):\n    {raw[:800]}")
        if r.status_code >= 400:
            print(f"\nFAIL: Tavily returned HTTP {r.status_code}")
            _explain_status(r.status_code, raw)
            return 1
        try:
            data = r.json()
        except json.JSONDecodeError:
            print("\nFAIL: response was not JSON")
            return 1
        urls = [x.get("url") for x in (data.get("results") or [])]
        print(f"  parsed {len(urls)} URLs:")
        for u in urls:
            print(f"    - {u}")
    except requests.Timeout:
        print(f"  timed out after {(time.perf_counter() - t0)*1000:.0f} ms")
        print("\nFAIL: Tavily timed out (network or provider slow)")
        return 1
    except Exception as exc:
        print(f"  exception: {type(exc).__name__}: {exc}")
        print("\nFAIL: raw request crashed")
        return 1

    # ── 2) Through the SDK (matches what app uses) ────────────────────────
    banner("via tavily.TavilyClient")
    try:
        from tavily import TavilyClient
    except ImportError:
        print("  tavily-python not installed — `pip install tavily-python`")
        return 1

    try:
        client = TavilyClient(api_key=key)
        t1 = time.perf_counter()
        result = client.search(query=query, search_depth="basic", max_results=5)
        elapsed = (time.perf_counter() - t1) * 1000
        print(f"  ok ({elapsed:.0f} ms)")
        urls = [x.get("url") for x in (result.get("results") or [])]
        print(f"  parsed {len(urls)} URLs:")
        for u in urls:
            print(f"    - {u}")
    except Exception as exc:
        print(f"  exception: {type(exc).__name__}: {exc}")
        print("\nFAIL: SDK call crashed")
        return 1

    print("\nPASS: Tavily key works for both raw HTTP and SDK paths.")
    return 0


def _explain_status(code: int, body: str) -> None:
    hints = {
        400: "Bad request — malformed body or invalid parameters.",
        401: "Unauthorized — the API key is wrong or revoked.",
        402: "Payment required — account out of credits or trial expired.",
        403: "Forbidden — key is valid but lacks permission for this endpoint.",
        429: "Rate limited — too many requests.",
        432: ("Non-standard status code. Tavily is not known to emit 432 from "
              "/search — verify you're hitting the right URL and the key prefix "
              "starts with 'tvly-'. A 432 from a reverse proxy usually means "
              "'Required field missing' (e.g. a Cloudflare WAF rule)."),
        500: "Tavily server error — try again later.",
        503: "Tavily unavailable — try again later.",
    }
    hint = hints.get(code, f"Unhandled status {code}.")
    print(f"  hint: {hint}")


if __name__ == "__main__":
    sys.exit(main())
