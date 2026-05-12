"""
Conversation-history smoke test.

Verifies that multi-turn context flows correctly through the pipeline:
 - Turn 1 establishes a topic (e.g., NVIDIA FY24 data-center revenue).
 - Turn 2 is anaphoric ("and AMD?") — the rewriter must resolve the reference
   to "AMD data-center revenue" rather than answering as a fresh topic.
 - Turn 3 builds on both ("which grew faster YoY?") — both entities must
   appear in the answer.

Reuses the existing multi-turn scenario from `evals/question_dataset/multiturn.json`
(the `mt1` scenario tagged as `smoke_ids: ["mt1"]`).

Usage:
    python evals/smoke_conversation_history.py [--url http://localhost:8765]

Exits 0 on pass, 1 on fail. Cleans up the test session via
`DELETE /api/eval/sessions` at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

DEFAULT_URL = "http://localhost:8765"
MULTITURN_JSON = Path(__file__).parent / "question_dataset" / "multiturn.json"


def _load_smoke_scenario() -> dict:
    """Load the multiturn scenario marked for smoke runs (`mt1` by default)."""
    raw = json.loads(MULTITURN_JSON.read_text(encoding="utf-8"))
    smoke_ids = (raw.get("meta") or {}).get("smoke_ids") or ["mt1"]
    scenarios = raw.get("scenarios") or []
    for s in scenarios:
        if s.get("id") in smoke_ids:
            return s
    if scenarios:
        return scenarios[0]
    raise RuntimeError("No multi-turn scenarios in benchmark file")


async def _call_turn(
    client: httpx.AsyncClient,
    url: str,
    session_id: str,
    question: str,
    turn_idx: int,
) -> dict:
    body = {"query": question, "session_id": session_id}
    headers = {"X-Semantic-Cache": "off", "X-Langsmith-Trace": "false"}
    mode = "?"
    answer_chars = 0
    answer_text = ""
    error: Optional[str] = None
    sub_queries: list = []
    t0 = time.monotonic()
    try:
        async with client.stream("POST", f"{url}/api/search",
                                 json=body, headers=headers, timeout=200.0) as resp:
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
                        sub_queries = data.get("sub_queries") or []
                    elif event_type in ("sub_answer_token", "token"):
                        chunk = data.get("text", "")
                        answer_chars += len(chunk)
                        answer_text += chunk
                    elif event_type == "done":
                        mode = data.get("mode", mode)
                    elif event_type == "error":
                        error = data.get("message", "unknown error")
    except Exception as exc:
        error = str(exc)
    return {
        "turn":         turn_idx,
        "question":     question,
        "answer":       answer_text,
        "answer_chars": answer_chars,
        "mode":         mode,
        "sub_queries":  sub_queries,
        "elapsed_s":    round(time.monotonic() - t0, 2),
        "error":        error,
    }


async def main(url: str) -> int:
    scenario = _load_smoke_scenario()
    turns = scenario.get("turns") or []
    if not turns:
        print(f"[FAIL] scenario {scenario.get('id')} has no turns")
        return 1

    session_id = f"eval-mt-smoke-{int(time.time())}"
    print(f"=== Conversation-history smoke ({scenario.get('id')}: {scenario.get('name')}) ===")
    print(f"Session: {session_id}")
    print(f"Server:  {url}")

    results = []
    async with httpx.AsyncClient() as client:
        for i, turn in enumerate(turns, 1):
            q = turn.get("question") or ""
            print(f"\n[Turn {i}/{len(turns)}] {q}")
            r = await _call_turn(client, url, session_id, q, i)
            results.append(r)
            preview = r["answer"][:160].replace("\n", " ")
            print(f"   mode={r['mode']}  chars={r['answer_chars']}  elapsed={r['elapsed_s']}s")
            print(f"   preview: {preview}{'…' if len(r['answer']) > 160 else ''}")
            if r["error"]:
                print(f"[FAIL] Turn {i} errored: {r['error']}")
                return 1

        # ── Cleanup ─────────────────────────────────────────────────────────
        try:
            r = await client.delete(f"{url}/api/eval/sessions", timeout=10)
            print(f"\nCleanup: deleted {r.json().get('deleted', '?')} eval session(s).")
        except Exception as exc:
            print(f"\nCleanup failed (non-fatal): {exc}")

    # ── Verdict ────────────────────────────────────────────────────────────
    if len(results) < 2:
        print("[FAIL] need at least 2 turns to verify history flow")
        return 1

    # Turn 2 must mention the entity introduced in its OWN question (e.g., "AMD"
    # for "and AMD?"). The rewriter must have resolved the anaphora.
    t2 = results[1]
    t2_text = t2["answer"].lower()
    t2_q = (turns[1].get("question") or "").lower()
    # Look for new key_facts of turn 2 in its answer
    t2_keys = [k.lower() for k in (turns[1].get("key_facts") or [])]
    missing_t2 = [k for k in t2_keys if k.lower() not in t2_text]
    if t2["answer_chars"] < 30:
        print(f"[FAIL] Turn 2 answer empty/too-short ({t2['answer_chars']} chars)")
        return 1
    # If `key_facts` exist, require at least one of them to appear
    if t2_keys and len(missing_t2) == len(t2_keys):
        print(f"[FAIL] Turn 2 answer missed ALL key_facts {t2_keys}; likely lost context.")
        return 1

    if len(results) >= 3:
        t3 = results[2]
        t3_text = t3["answer"].lower()
        t3_keys = [k.lower() for k in (turns[2].get("key_facts") or [])]
        missing_t3 = [k for k in t3_keys if k not in t3_text]
        if t3["answer_chars"] < 30:
            print(f"[FAIL] Turn 3 answer empty/too-short ({t3['answer_chars']} chars)")
            return 1
        if t3_keys and len(missing_t3) == len(t3_keys):
            print(f"[FAIL] Turn 3 answer missed ALL key_facts {t3_keys}; likely lost context.")
            return 1

    total_elapsed = sum(r["elapsed_s"] for r in results)
    print(f"\n[PASS] All {len(results)} turns completed in {total_elapsed:.1f}s total.")
    print(f"       Turn 2 used: {results[1]['sub_queries']}")
    if len(results) >= 3:
        print(f"       Turn 3 used: {results[2]['sub_queries']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main(args.url)))
