"""
Web Search RAG — standalone evaluation harness.

Calls the running server at localhost:8000 via HTTP, parses SSE stream,
computes M1 (factual correctness) and M7 (LLM judge), saves results.

Usage:
    python evals/run_eval.py --smoke         # question_v1_smoke.txt (2 questions)
    python evals/run_eval.py --full          # question_v1.txt (10 questions)
    python evals/run_eval.py --url http://localhost:8000

Output:
    evals/results/<timestamp>_<mode>/
        NN_<category>_<question>.json    (per-question)
        _summary.json
        _analysis.md
        eval.log
"""
import argparse
import asyncio
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

EVALS_DIR = Path(__file__).parent / "results"
BASE_URL   = "http://localhost:8000"

# ── Fact-checking (M1, M3) — no LLM ─────────────────────────────────────────

def _matches_fact(fact: str, text: str) -> bool:
    text_lower = text.lower()
    num_matches = re.findall(r'\$?([\d,]+\.?\d*)\s*([BMK%]?)', fact)
    if num_matches:
        for raw, unit in num_matches:
            try:
                val = float(raw.replace(",", ""))
                if val == 0:
                    continue
                text_nums = re.findall(r'\$?([\d,]+\.?\d*)\s*([BMK%]?)', text)
                for t_raw, t_unit in text_nums:
                    try:
                        t_val = float(t_raw.replace(",", ""))
                        if unit == t_unit and abs(val - t_val) / max(abs(val), 1) <= 0.05:
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
    stop = {"from", "their", "with", "that", "this", "have", "been", "were", "the",
            "and", "for", "its", "was", "are", "per", "into", "than", "will"}
    terms = [w for w in re.sub(r"[^a-z0-9 ]", " ", fact.lower()).split()
             if len(w) > 3 and w not in stop]
    if not terms:
        return fact.lower() in text_lower
    hits = sum(1 for t in terms if t in text_lower)
    return hits >= max(1, len(terms) * 0.6)


def fact_check(key_facts: list, answer: str) -> float:
    if not key_facts:
        return 1.0
    hits = sum(1 for f in key_facts if _matches_fact(f, answer))
    return round(hits / len(key_facts), 3)


def retrieval_recall(key_facts: list, chunks: list) -> float:
    if not key_facts:
        return 1.0
    if not chunks:
        return 0.0
    all_text = " ".join(c.get("chunk_text", "") for c in chunks)
    hits = sum(1 for f in key_facts if _matches_fact(f, all_text))
    return round(hits / len(key_facts), 3)


# ── SSE stream parser ─────────────────────────────────────────────────────────

async def call_search_api(
    client: httpx.AsyncClient,
    base_url: str,
    question: str,
    session_id: str,
    timeout: float = 120.0,
) -> dict:
    """Call POST /api/search, parse SSE stream, return collected data."""
    tokens: list[str] = []
    sub_answer_tokens: dict[int, list[str]] = {}  # index → tokens
    chunks: list = []
    citations: list = []
    urls: list = []
    sub_queries: list = [question]
    latency_breakdown: dict = {}
    total_latency_ms: int = 0
    error: Optional[str] = None

    body = {"query": question, "session_id": session_id}

    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/search",
            json=body,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            buf = ""
            async for raw_chunk in resp.aiter_bytes():
                buf += raw_chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    event_str, buf = buf.split("\n\n", 1)
                    lines = event_str.strip().split("\n")
                    event_type = ""
                    data_str = ""
                    for line in lines:
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

                    if event_type == "token":
                        # synthesis tokens
                        tokens.append(data.get("text", ""))
                    elif event_type == "sub_answer_token":
                        idx = data.get("index", 0)
                        sub_answer_tokens.setdefault(idx, []).append(data.get("text", ""))
                    elif event_type == "sub_answer_start":
                        # Capture per-sub-query chunks (each has top-k chunks)
                        for c in data.get("chunks", []):
                            chunks.append(c)
                    elif event_type == "search_done":
                        urls = data.get("urls", [])
                        sub_queries = data.get("sub_queries", [question])
                    elif event_type == "done":
                        citations = data.get("citations", [])
                        latency_breakdown = data.get("latency_breakdown", {})
                        total_latency_ms = data.get("total_latency_ms", 0)
                    elif event_type == "error":
                        error = data.get("message", "Unknown error")

    except Exception as exc:
        error = str(exc)

    # Build final answer: synthesis tokens if present, else concatenate sub-answer tokens
    if tokens:
        answer = "".join(tokens)
    else:
        # Join all sub-answers in order
        parts = []
        for idx in sorted(sub_answer_tokens.keys()):
            parts.append("".join(sub_answer_tokens[idx]))
        answer = "\n\n".join(parts)

    return {
        "answer": answer,
        "chunks": chunks,
        "citations": citations,
        "urls": urls,
        "sub_queries": sub_queries,
        "latency_breakdown": latency_breakdown,
        "total_latency_ms": total_latency_ms,
        "error": error,
    }


# ── LLM Judge (M7) ───────────────────────────────────────────────────────────

JUDGE_SYSTEM = """\
You are an expert evaluator for a web-search RAG system.
Evaluate the system response against the expected behavior and ground truth.

Scoring rubric:
- pass   (0.8–1.0): Accurate, well-cited, covers the key facts
- partial (0.4–0.79): Some correct, some missing or slightly off
- fail   (0.0–0.39): Significantly wrong, missing key facts, or fabricated

Return ONLY valid JSON (no markdown):
{"verdict": "pass"|"partial"|"fail", "score": <float 0-1>, "reasoning": "<brief>"}
"""

JUDGE_USER = """\
CATEGORY: {category}
EXPECTED BEHAVIOR: {expected_behavior}
GROUND TRUTH: {ground_truth}
M1 (factual correctness): {m1:.3f}

QUESTION: {question}

SYSTEM RESPONSE:
{answer}

KEY FACTS CHECK:
{facts_check}
"""


async def llm_judge(
    question: str,
    category: str,
    expected_behavior: str,
    answer: str,
    ground_truth: str,
    key_facts: list,
    m1: float,
) -> dict:
    """Call DeepSeek (or OpenAI fallback) to judge the answer."""
    facts_lines = "\n".join(
        f"  {'✓' if _matches_fact(f, answer) else '✗'} {f}"
        for f in key_facts
    )
    user_msg = JUDGE_USER.format(
        category=category,
        expected_behavior=expected_behavior,
        ground_truth=(ground_truth or "N/A")[:800],
        m1=m1,
        question=question,
        answer=(answer or "")[:1200],
        facts_check=facts_lines or "  (none)",
    )

    # Try DeepSeek first (cheaper), fall back to OpenAI
    providers = []
    if os.getenv("DEEPSEEK_API_KEY"):
        providers.append(("https://api.deepseek.com/v1", os.getenv("DEEPSEEK_API_KEY"), "deepseek-chat"))
    if os.getenv("OPENAI_API_KEY"):
        providers.append(("https://api.openai.com/v1", os.getenv("OPENAI_API_KEY"), "gpt-4o-mini"))

    for base_url, api_key, model in providers:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": JUDGE_SYSTEM},
                            {"role": "user",   "content": user_msg},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 200,
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                if raw.startswith("```"):
                    raw = "\n".join(raw.split("\n")[1:]).rstrip("```").strip()
                parsed = json.loads(raw)
                parsed["judge_model"] = model
                return parsed
        except Exception as exc:
            logger.warning("Judge failed with %s: %s", model, exc)

    return {"verdict": "fail", "score": 0.0, "reasoning": "Judge unavailable", "judge_model": "none"}


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(mode: str, base_url: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = EVALS_DIR / f"{timestamp}_{mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tee output to eval.log
    log_fh = open(out_dir / "eval.log", "w", encoding="utf-8", buffering=1)

    class _Tee:
        def __init__(self, a, b): self._a, self._b = a, b
        def write(self, t): self._a.write(t); self._b.write(t)
        def flush(self): self._a.flush(); self._b.flush()
        def fileno(self): return self._a.fileno()
        @property
        def encoding(self): return getattr(self._a, "encoding", "utf-8")
        @property
        def errors(self): return getattr(self._a, "errors", "replace")

    sys.stdout = _Tee(sys.__stdout__, log_fh)
    sys.stderr = _Tee(sys.__stderr__, log_fh)

    # Load questions
    qfile_map = {
        "smoke":    "question_v1_smoke.txt",
        "full":     "question_v1.txt",
        "v6_smoke": "question_v6_smoke.txt",
        "v6":       "question_v6.txt",
    }
    qfile = Path(__file__).parent / qfile_map[mode]
    data = json.loads(qfile.read_text(encoding="utf-8"))

    # Build task list: [(category, expected_behavior, question, gt_entry)]
    tasks = []
    for category, meta in data.items():
        expected = meta.get("expected_behavior", "")
        gt_map = meta.get("ground_truth_map", {})
        for q in meta.get("questions", []):
            gt = gt_map.get(q, {})
            tasks.append((category, expected, q, gt))

    print(f"{'='*60}")
    print(f"Web Search RAG Eval — {mode.upper()} ({len(tasks)} questions)")
    print(f"Server: {base_url}")
    print(f"Output: {out_dir}")
    print(f"{'='*60}\n")

    # ── Phase 1: Pipeline runs ────────────────────────────────────────────────
    pipeline_results = []
    session_ids = []

    async with httpx.AsyncClient() as client:
        for idx, (category, expected, question, gt) in enumerate(tasks, 1):
            session_id = f"eval-{timestamp}-{idx:02d}"
            session_ids.append(session_id)
            print(f"[{idx}/{len(tasks)}] [{category}] {question[:70]}{'…' if len(question) > 70 else ''}")

            t0 = time.monotonic()
            result = await call_search_api(client, base_url, question, session_id)
            elapsed = round(time.monotonic() - t0, 2)

            if result["error"]:
                print(f"   ERROR: {result['error']}")
            else:
                bd = result["latency_breakdown"]
                print(f"   {elapsed}s total | search={bd.get('search_ms',0)}ms "
                      f"extract={bd.get('extract_ms',0)}ms "
                      f"retrieve={bd.get('retrieve_ms',0)}ms | "
                      f"chunks={len(result['chunks'])} citations={len(result['citations'])}")
                if len(result["sub_queries"]) > 1:
                    print(f"   decomposed → {result['sub_queries']}")

            result["elapsed_s"] = elapsed
            pipeline_results.append(result)

    # ── Phase 2: Metrics ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Phase 2: Computing metrics (M1 factual, M3 retrieval recall, M7 judge)")
    print(f"{'='*60}")

    results = []
    for idx, (pipeline, (category, expected, question, gt)) in enumerate(
            zip(pipeline_results, tasks), 1):

        key_facts = gt.get("key_facts", [])
        ground_truth = gt.get("ground_truth", "")
        answer = pipeline.get("answer", "")
        chunks = pipeline.get("chunks", [])

        m1 = fact_check(key_facts, answer)
        m3 = retrieval_recall(key_facts, chunks)

        print(f"[{idx}/{len(tasks)}] Running judge… (M1={m1:.2f} M3={m3:.2f})")
        judgment = await llm_judge(
            question=question,
            category=category,
            expected_behavior=expected,
            answer=answer,
            ground_truth=ground_truth,
            key_facts=key_facts,
            m1=m1,
        )
        m7 = judgment.get("score", 0.0)
        verdict = judgment.get("verdict", "fail")
        icon = "[PASS]" if verdict == "pass" else ("[PART]" if verdict == "partial" else "[FAIL]")
        print(f"  {icon} {verdict} ({m7:.2f}) | M1={m1:.2f} M3={m3:.2f} | {judgment.get('reasoning','')[:80]}")

        record = {
            "category":          category,
            "expected_behavior": expected,
            "question":          question,
            "ground_truth":      ground_truth,
            "key_facts":         key_facts,
            "session_id":        session_ids[idx - 1],
            "metrics": {
                "m1_factual_correctness": m1,
                "m3_retrieval_recall":    m3,
                "m7_judge_score":         m7,
            },
            "timing": {
                "pipeline_s":       pipeline["elapsed_s"],
                "latency_breakdown": pipeline["latency_breakdown"],
                "total_latency_ms":  pipeline["total_latency_ms"],
            },
            "pipeline": {
                "answer":          answer,
                "citations":       pipeline["citations"],
                "urls":            pipeline["urls"],
                "chunks":          chunks,
                "sub_queries":     pipeline["sub_queries"],
                "error":           pipeline.get("error"),
            },
            "judgment": judgment,
        }
        results.append(record)

        # Save per-question JSON
        q_slug = question[:50].replace(" ", "_").replace("?", "").replace("/", "_")
        out_path = out_dir / f"{idx:02d}_{category}_{q_slug}.json"
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Phase 3: Summary ──────────────────────────────────────────────────────
    all_m7 = [r["metrics"]["m7_judge_score"] for r in results]
    overall_avg = round(sum(all_m7) / len(all_m7), 3) if all_m7 else 0.0
    pass_n    = sum(1 for r in results if r["judgment"]["verdict"] == "pass")
    partial_n = sum(1 for r in results if r["judgment"]["verdict"] == "partial")
    fail_n    = sum(1 for r in results if r["judgment"]["verdict"] == "fail")
    avg_m1 = round(sum(r["metrics"]["m1_factual_correctness"] for r in results) / max(len(results), 1), 3)
    avg_m3 = round(sum(r["metrics"]["m3_retrieval_recall"] for r in results) / max(len(results), 1), 3)
    latencies = [r["timing"]["pipeline_s"] for r in results]
    avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0

    summary = {
        "meta": {
            "timestamp":         timestamp,
            "mode":              mode,
            "questions_file":    qfile.name,
            "total_questions":   len(results),
            "overall_avg_score": overall_avg,
            "pass_count":        pass_n,
            "partial_count":     partial_n,
            "fail_count":        fail_n,
            "avg_m1":            avg_m1,
            "avg_m3":            avg_m3,
            "avg_latency_s":     avg_lat,
        },
        "category_summary": {
            cat: {
                "n": len([r for r in results if r["category"] == cat]),
                "avg_m7": round(sum(r["metrics"]["m7_judge_score"]
                                    for r in results if r["category"] == cat)
                                / max(1, sum(1 for r in results if r["category"] == cat)), 3),
            }
            for cat in dict.fromkeys(r["category"] for r in results)
        },
    }

    summary_path = out_dir / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Analysis markdown
    analysis_lines = [
        f"# Web Search RAG Eval — {mode.upper()}",
        f"**Timestamp**: {timestamp}  ",
        f"**Questions**: {qfile.name} ({len(results)} questions)",
        "",
        "## Score Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Overall avg M7 score | **{overall_avg:.3f}** |",
        f"| Pass | {pass_n} ({100*pass_n//max(len(results),1)}%) |",
        f"| Partial | {partial_n} |",
        f"| Fail | {fail_n} |",
        f"| Avg M1 (factual) | {avg_m1:.3f} |",
        f"| Avg M3 (retrieval recall) | {avg_m3:.3f} |",
        f"| Avg latency | {avg_lat}s/Q |",
        "",
        "## Per-Question Results",
        "",
        "| # | Category | Verdict | M7 | M1 | M3 | Latency |",
        "|---|----------|---------|-----|-----|-----|---------|",
    ]
    for i, r in enumerate(results, 1):
        v = r["judgment"]["verdict"]
        m = r["metrics"]
        t = r["timing"]
        analysis_lines.append(
            f"| {i} | {r['category']} | {v} | {m['m7_judge_score']:.2f} "
            f"| {m['m1_factual_correctness']:.2f} | {m['m3_retrieval_recall']:.2f} "
            f"| {t['pipeline_s']:.1f}s |"
        )
    analysis_lines += [
        "",
        "## Decomposition",
        "",
    ]
    for i, r in enumerate(results, 1):
        sqs = r["pipeline"].get("sub_queries", [])
        if len(sqs) > 1:
            analysis_lines.append(f"- Q{i}: decomposed into {len(sqs)} sub-queries: {sqs}")
    if not any(len(r["pipeline"].get("sub_queries", [])) > 1 for r in results):
        analysis_lines.append("- All questions used single sub-query (no decomposition triggered)")

    analysis_lines += ["", f"*Generated {timestamp} · Web Search RAG Eval Harness*"]
    (out_dir / "_analysis.md").write_text("\n".join(analysis_lines), encoding="utf-8")

    # Final print
    print(f"\n{'='*60}")
    print(f"Results → {out_dir}")
    print(f"{'='*60}")
    print(f"Overall avg M7: {overall_avg:.3f}  |  Pass: {pass_n}  Partial: {partial_n}  Fail: {fail_n}")
    print(f"Avg M1: {avg_m1:.3f}  Avg M3: {avg_m3:.3f}  Avg latency: {avg_lat}s/Q")

    log_fh.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Web Search RAG eval harness")
    parser.add_argument("--smoke",    action="store_true", help="v1 smoke (2 RAG/IR questions)")
    parser.add_argument("--full",     action="store_true", help="v1 full  (10 RAG/IR questions)")
    parser.add_argument("--v6-smoke", action="store_true", help="v6 smoke (financial multi-entity)")
    parser.add_argument("--v6",       action="store_true", help="v6 full  (all financial questions)")
    parser.add_argument("--url",      default=BASE_URL,   help="Server base URL")
    args = parser.parse_args()

    if args.smoke:      mode = "smoke"
    elif args.full:     mode = "full"
    elif args.v6_smoke: mode = "v6_smoke"
    elif args.v6:       mode = "v6"
    else:
        parser.error("Specify --smoke, --full, --v6-smoke, or --v6")

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(mode=mode, base_url=args.url))
