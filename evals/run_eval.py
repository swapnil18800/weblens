"""
WebLens RAG — evaluation harness v7.

Five core metrics + two diagnostic metrics:
    Core (averaged into aggregate):
        - faithfulness          (LLM judge: claims supported by retrieved chunks?)
        - context_recall        (heuristic: key_facts present in chunks)
        - context_precision     (LLM judge: are retrieved chunks relevant?)
        - answer_correctness    (heuristic + LLM-assist on key_facts)
        - routing_decomposition (structural: actual mode + sub-query count vs expected)
    Diagnostic (reported, NOT averaged):
        - answer_relevancy      (embedding cosine of Q,A)
        - latency               (pipeline_seconds + per-stage breakdown)

Run modes:
    --smoke      6 questions (one per major category)
    --full       30 single-turn questions
    --multiturn  5 scenarios (~12 turns)
    --all        full + multiturn

CLI:
    python evals/run_eval.py --smoke
    python evals/run_eval.py --full --trace off
    python evals/run_eval.py --multiturn --judge openai
    python evals/run_eval.py --full --concurrency 2

Output: evals/results/<UTC_TS>_<mode>/
        per_question/NN_<category>_<slug>.json
        summary.json
        report.md
        failures.md
        eval.log
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

# Allow `from pipeline.embed import ...` when running this file from the evals/ folder.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

EVALS_DIR  = Path(__file__).parent
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_URL = os.environ.get("WEBLENS_URL", "http://localhost:8765")


# ── Benchmark loading ────────────────────────────────────────────────────────

def load_benchmark(mode: str) -> dict:
    """Load benchmark questions + multi-turn scenarios for the given mode."""
    bench_path = EVALS_DIR / "question_dataset" / "benchmark.json"
    multi_path = EVALS_DIR / "question_dataset" / "multiturn.json"
    bench = json.loads(bench_path.read_text(encoding="utf-8"))
    multi = json.loads(multi_path.read_text(encoding="utf-8"))

    if mode == "smoke":
        smoke_ids = set(bench["meta"].get("smoke_ids", []))
        questions = [q for q in bench["questions"] if q["id"] in smoke_ids]
        scenarios = []
    elif mode == "full":
        questions = list(bench["questions"])
        scenarios = []
    elif mode == "multiturn":
        questions = []
        scenarios = list(multi["scenarios"])
    elif mode == "all":
        questions = list(bench["questions"])
        scenarios = list(multi["scenarios"])
    else:
        raise ValueError(f"Unknown mode: {mode}")

    return {"questions": questions, "scenarios": scenarios,
            "bench_meta": bench["meta"], "multi_meta": multi["meta"]}


# ── SSE pipeline call ────────────────────────────────────────────────────────

async def run_pipeline_via_api(
    client: httpx.AsyncClient,
    base_url: str,
    question: str,
    session_id: str,
    timeout: float = 180.0,
    trace: bool = False,
    cache: Optional[str] = None,  # "on" | "off" | None (server default)
) -> dict:
    """Call POST /api/search, parse the SSE stream, return everything we need."""
    tokens: list = []
    sub_answer_tokens: dict[int, list] = {}
    chunks: list = []
    citations: list = []
    urls: list = []
    sub_queries: list = [question]
    rewritten_query: str = question
    rewrote: bool = False
    mode: str = "search"
    rationale: str = ""
    latency_breakdown: dict = {}
    total_latency_ms: int = 0
    error: Optional[str] = None
    token_cost: dict = {}

    body = {"query": question, "session_id": session_id}
    headers: dict[str, str] = {}
    if trace:
        headers["X-Langsmith-Trace"] = "true"
    if cache is not None:
        headers["X-Semantic-Cache"] = cache
    t0 = time.monotonic()

    try:
        async with client.stream("POST", f"{base_url}/api/search",
                                 json=body, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            buf = ""
            async for raw in resp.aiter_bytes():
                buf += raw.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    event_type, data_str = "", ""
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
                        sub_queries = data.get("sub_queries", [question])
                        rewritten_query = data.get("rewritten_query", question)
                        rewrote = data.get("rewrote", False)
                        mode = data.get("mode", "search")
                        rationale = data.get("rationale", "")
                    elif event_type == "search_done":
                        urls = data.get("urls", [])
                    elif event_type == "sub_answer_start":
                        for c in data.get("chunks", []):
                            chunks.append(c)
                    elif event_type == "sub_answer_token":
                        idx = data.get("index", 0)
                        sub_answer_tokens.setdefault(idx, []).append(data.get("text", ""))
                    elif event_type == "token":
                        tokens.append(data.get("text", ""))
                    elif event_type == "done":
                        citations = data.get("citations", [])
                        latency_breakdown = data.get("latency_breakdown", {})
                        total_latency_ms = data.get("total_latency_ms", 0)
                        token_cost = latency_breakdown.get("token_cost", {})
                        mode = data.get("mode", mode)
                    elif event_type == "error":
                        error = data.get("message", "Unknown error")

    except Exception as exc:
        error = str(exc)

    # Final answer: synthesis tokens win; else concat sub-answers in order
    if tokens:
        answer = "".join(tokens)
    else:
        parts = []
        for idx in sorted(sub_answer_tokens.keys()):
            parts.append("".join(sub_answer_tokens[idx]))
        answer = "\n\n".join(parts)

    return {
        "answer":           answer,
        "chunks":           chunks,
        "citations":        citations,
        "urls":             urls,
        "sub_queries":      sub_queries,
        "rewritten_query":  rewritten_query,
        "rewrote":          rewrote,
        "mode":             mode,
        "rationale":        rationale,
        "latency_breakdown": latency_breakdown,
        "total_latency_ms": total_latency_ms,
        "elapsed_s":        round(time.monotonic() - t0, 2),
        "token_cost":       token_cost,
        "error":            error,
    }


# ── Heuristic key_fact matcher ───────────────────────────────────────────────

_STOP = {"from", "their", "with", "that", "this", "have", "been", "were", "the",
         "and", "for", "its", "was", "are", "per", "into", "than", "will",
         "what", "when", "where", "which", "would", "should", "about", "after",
         "also", "such", "while"}


def _normalize_num(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").replace("$", ""))
    except Exception:
        return None


def _matches_fact(fact: str, text: str) -> bool:
    """Light heuristic: numeric match within ±5%, or ≥60% of significant terms present."""
    if not fact or not text:
        return False
    text_lower = text.lower()
    fact_lower = fact.lower()

    # Numeric match (±5%)
    num_matches = re.findall(r"\$?([\d,]+\.?\d*)\s*([BMK%]?)", fact)
    for raw, unit in num_matches:
        val = _normalize_num(raw)
        if val is None or val == 0:
            continue
        # Look for matching number in text with same suffix unit (or unitless)
        text_nums = re.findall(r"\$?([\d,]+\.?\d*)\s*([BMK%]?)", text)
        for t_raw, t_unit in text_nums:
            t_val = _normalize_num(t_raw)
            if t_val is None:
                continue
            if unit == t_unit and abs(val - t_val) / max(abs(val), 1) <= 0.05:
                return True

    # Term-overlap: significant words from fact, ≥60% present in text
    terms = [w for w in re.sub(r"[^a-z0-9 ]", " ", fact_lower).split()
             if len(w) > 3 and w not in _STOP]
    if not terms:
        return fact_lower in text_lower
    hits = sum(1 for t in terms if t in text_lower)
    return hits >= max(1, len(terms) * 0.6)


# ── Metrics: heuristics ──────────────────────────────────────────────────────

def metric_context_recall(key_facts: list, chunks: list, expected_mode: str = "search") -> float:
    """% of key_facts whose evidence is in the retrieved chunks.

    Parametric questions intentionally have no chunks, so retrieval-side metrics
    are N/A and we return 1.0 (don't penalize the route).
    """
    if expected_mode == "parametric":
        return 1.0
    if not key_facts:
        return 1.0
    if not chunks:
        return 0.0
    all_text = " ".join(c.get("chunk_text", "") for c in chunks)
    return round(sum(1 for f in key_facts if _matches_fact(f, all_text)) / len(key_facts), 3)


def metric_answer_correctness_heuristic(key_facts: list, answer: str) -> tuple[float, list[bool]]:
    """Heuristic side of answer-correctness — returns (score, per-fact hit/miss list)."""
    if not key_facts:
        return (1.0, [])
    hits = [_matches_fact(f, answer) for f in key_facts]
    score = round(sum(hits) / len(key_facts), 3)
    return (score, hits)


def metric_routing_decomposition(actual_mode: str, actual_sub_count: int,
                                  expected_mode: str, expected_sub_count: str) -> float:
    """Structural check: mode match AND decomposition appropriateness.

    v9: `expected_mode` may be "either" for benchmark questions where BOTH
    parametric and search are defensible (textbook-stable facts with a tolerant
    label). Such questions still grade the sub-query count, but the mode is
    always considered correct.
    """
    if expected_mode == "either":
        mode_ok = True
    else:
        mode_ok = (actual_mode == expected_mode) or (
            # Treat "cache" as a satisfactory replacement for "search" — both serve
            # from sourced answers.
            actual_mode == "cache" and expected_mode == "search"
        )
    if not mode_ok:
        # Mode wrong is a critical fail (zero credit)
        return 0.0

    # Sub-query count check (only meaningful for search/cache; parametric is always 1)
    if expected_mode == "parametric":
        return 1.0

    if expected_sub_count == "single":
        return 1.0 if actual_sub_count == 1 else 0.5  # partial credit if over-decomposed
    if expected_sub_count.startswith("multi:"):
        rng = expected_sub_count.split(":", 1)[1]
        # rng like "2-3" or "4-6"
        if "-" in rng:
            lo, hi = map(int, rng.split("-"))
            if lo <= actual_sub_count <= hi:
                return 1.0
            # Partial credit for being within ±1
            if abs(actual_sub_count - lo) <= 1 or abs(actual_sub_count - hi) <= 1:
                return 0.5
            return 0.0 if actual_sub_count == 1 else 0.25
    return 1.0


# ── Metrics: LLM-assisted ────────────────────────────────────────────────────

def _build_judge():
    """Return (provider_label, base_url, api_key, model)."""
    explicit = os.environ.get("WEBLENS_EVAL_JUDGE")
    if explicit == "openai" or (not explicit and os.getenv("OPENAI_API_KEY") and not os.getenv("DEEPSEEK_API_KEY")):
        return ("openai", "https://api.openai.com/v1", os.getenv("OPENAI_API_KEY"), "gpt-4o-mini")
    # default: deepseek
    return ("deepseek", "https://api.deepseek.com/v1", os.getenv("DEEPSEEK_API_KEY"), "deepseek-chat")


async def _judge_json(client: httpx.AsyncClient, prompt: str, system: str,
                      max_tokens: int = 400, temperature: float = 0.0) -> Optional[dict]:
    """Call the judge, expect JSON, return parsed dict (or None on failure)."""
    label, base_url, api_key, model = _build_judge()
    if not api_key:
        return None
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=45.0,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip fences
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").rstrip().rstrip("`").strip()
        first, last = raw.find("{"), raw.rfind("}")
        if first == -1 or last == -1:
            return None
        return json.loads(raw[first : last + 1])
    except Exception as exc:
        logger.warning("[judge] %s call failed: %s", model, exc)
        return None


_FAITH_SYSTEM = (
    "You evaluate whether an answer's claims are supported by the provided source chunks. "
    "Decompose the answer into a small set (≤8) of atomic factual claims; for each, mark TRUE if "
    "the chunks support it, FALSE otherwise. Return ONLY valid JSON: "
    '{"supported": <int>, "total": <int>, "reasoning": "<≤30 words>"}. '
    "If the answer says 'not found in sources' or refuses, set supported=total=0 and reasoning='refusal'."
)


async def metric_faithfulness(client: httpx.AsyncClient, answer: str, chunks: list,
                               expected_mode: str = "search") -> dict:
    """LLM judge: are answer claims supported by retrieved chunks?

    For parametric questions, faithfulness-to-chunks is N/A (there are no chunks)
    so we return 1.0 to avoid penalizing the route.
    """
    if not answer or not answer.strip():
        return {"score": 0.0, "supported": 0, "total": 0, "reasoning": "empty answer"}
    if expected_mode == "parametric":
        return {"score": 1.0, "supported": 0, "total": 0, "reasoning": "parametric (N/A)"}
    if not chunks:
        return {"score": 0.5, "supported": 0, "total": 0, "reasoning": "no chunks"}

    chunk_text = "\n\n".join(
        f"[{i+1}] {c.get('chunk_text','')[:500]}"
        for i, c in enumerate(chunks[:10])
    )
    prompt = (
        f"ANSWER:\n{answer[:1500]}\n\n"
        f"SOURCE CHUNKS:\n{chunk_text}\n\n"
        "Evaluate which claims in the answer are supported by the chunks."
    )
    parsed = await _judge_json(client, prompt, _FAITH_SYSTEM, max_tokens=200)
    if not parsed:
        return {"score": 0.5, "supported": 0, "total": 0, "reasoning": "judge unavailable"}
    supported = int(parsed.get("supported", 0))
    total = int(parsed.get("total", 1))
    score = supported / total if total > 0 else 0.0
    return {
        "score": round(score, 3),
        "supported": supported,
        "total": total,
        "reasoning": parsed.get("reasoning", "")[:150],
    }


_PRECISION_SYSTEM = (
    "You evaluate retrieval quality. For each numbered source chunk, decide whether it is "
    "RELEVANT to the question (would help answer it) or NOT RELEVANT. "
    "Return ONLY valid JSON: "
    '{"relevant": [<list of 0/1, length = num chunks>], "reasoning": "<≤25 words>"}.'
)


async def metric_context_precision(client: httpx.AsyncClient, question: str, chunks: list,
                                    expected_mode: str = "search") -> dict:
    if expected_mode == "parametric":
        return {"score": 1.0, "relevant": 0, "total": 0, "reasoning": "parametric (N/A)"}
    if not chunks:
        return {"score": 1.0, "relevant": 0, "total": 0, "reasoning": "no chunks"}
    chunks_for_judge = chunks[:8]
    chunk_text = "\n\n".join(
        f"[{i+1}] {c.get('chunk_text','')[:400]}"
        for i, c in enumerate(chunks_for_judge)
    )
    prompt = (
        f"QUESTION: {question}\n\n"
        f"CHUNKS:\n{chunk_text}\n\n"
        "For each chunk, mark 1 if relevant to the question, 0 if not."
    )
    parsed = await _judge_json(client, prompt, _PRECISION_SYSTEM, max_tokens=200)
    if not parsed:
        return {"score": 0.5, "relevant": 0, "total": len(chunks_for_judge), "reasoning": "judge unavailable"}
    flags = parsed.get("relevant", [])
    if not isinstance(flags, list) or not flags:
        return {"score": 0.5, "relevant": 0, "total": len(chunks_for_judge), "reasoning": "bad format"}
    flags = [1 if int(x) else 0 for x in flags[:len(chunks_for_judge)]]
    score = sum(flags) / len(flags) if flags else 0.0
    return {
        "score": round(score, 3),
        "relevant": sum(flags),
        "total": len(flags),
        "reasoning": parsed.get("reasoning", "")[:150],
    }


_CORRECTNESS_ASSIST_SYSTEM = (
    "You verify whether specific factual claims appear in a given answer text. For each numbered "
    "claim, decide if the answer contains supporting language (paraphrase OK). "
    "Return ONLY valid JSON: "
    '{"hits": [<0/1 per claim>], "reasoning": "<≤25 words>"}.'
)


async def metric_answer_correctness(
    client: httpx.AsyncClient,
    answer: str,
    key_facts: list,
    heuristic_score: float,
    heuristic_hits: list[bool],
) -> dict:
    """Heuristic + LLM-assist on key_facts not matched by regex."""
    if not key_facts:
        return {"score": 1.0, "hit_facts": [], "missed_facts": [], "reasoning": "no key_facts"}
    if not answer:
        return {"score": 0.0,
                "hit_facts": [], "missed_facts": list(key_facts),
                "reasoning": "empty answer"}

    # If all hits are positive, no need to call the LLM
    final_hits = list(heuristic_hits)
    missed_idx = [i for i, h in enumerate(heuristic_hits) if not h]
    if missed_idx:
        # Check the missed ones with the LLM in case heuristic missed paraphrases
        claims = [key_facts[i] for i in missed_idx]
        numbered = "\n".join(f"{n+1}. {c}" for n, c in enumerate(claims))
        prompt = (
            f"ANSWER:\n{answer[:1500]}\n\n"
            f"CLAIMS TO CHECK:\n{numbered}\n\n"
            "For each numbered claim, mark 1 if the answer asserts it (paraphrase OK), 0 otherwise."
        )
        parsed = await _judge_json(client, prompt, _CORRECTNESS_ASSIST_SYSTEM, max_tokens=150)
        if parsed:
            hits = parsed.get("hits", [])
            if isinstance(hits, list):
                for j, idx in enumerate(missed_idx):
                    if j < len(hits) and int(hits[j]) == 1:
                        final_hits[idx] = True

    score = sum(final_hits) / len(final_hits) if final_hits else 0.0
    hit_facts = [key_facts[i] for i, h in enumerate(final_hits) if h]
    missed_facts = [key_facts[i] for i, h in enumerate(final_hits) if not h]
    return {
        "score": round(score, 3),
        "hit_facts": hit_facts,
        "missed_facts": missed_facts,
        "reasoning": f"heuristic={heuristic_score:.2f}; LLM-assist promoted {sum(final_hits) - sum(heuristic_hits)} hit(s).",
    }


# ── Metric: answer relevancy (embedding cosine, diagnostic) ──────────────────

async def metric_answer_relevancy(question: str, answer: str) -> dict:
    """Embedding cosine similarity of Q and A. Diagnostic only."""
    try:
        from pipeline.embed import embed_texts_async
        import numpy as np
        if not answer.strip():
            return {"score": 0.0, "method": "embedding"}
        emb = await embed_texts_async([question, answer])
        if emb is None or len(emb) < 2:
            return {"score": 0.0, "method": "embedding"}
        a, b = emb[0], emb[1]
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
        sim = float(np.dot(a, b) / denom)
        return {"score": round(max(0.0, min(1.0, sim)), 3), "method": "embedding"}
    except Exception as exc:
        return {"score": 0.0, "method": "embedding", "error": str(exc)[:120]}


# ── Failure-mode classifier ──────────────────────────────────────────────────

def classify_failure(metrics: dict, q: dict, mode: str) -> Optional[str]:
    """Return a single dominant failure-mode tag, or None if not a failure."""
    aggregate = metrics.get("aggregate", 1.0)
    if aggregate >= 0.6:
        return None

    routing = metrics.get("routing_decomposition", 1.0)
    recall = metrics.get("context_recall", 1.0)
    faith = metrics.get("faithfulness", 1.0)
    precision = metrics.get("context_precision", 1.0)
    correctness = metrics.get("answer_correctness", 1.0)
    expected_mode = q.get("expected_mode")
    expected_sub_count = q.get("expected_sub_query_count", "single")

    # Wrong route
    if routing == 0.0:
        return "wrong_route"
    if routing < 1.0 and expected_sub_count == "single":
        return "over_decomposition"
    if routing < 1.0 and expected_sub_count.startswith("multi"):
        return "under_decomposition"

    # Refusal failure (expected refusal, but answered confidently)
    if q.get("category") == "refusal_unknown" and correctness < 0.4 and len((q.get("key_facts") or [])):
        return "refusal_failure"

    # Retrieval miss
    if recall < 0.4:
        return "retrieval_miss"

    # Hallucination: chunks were good but faithfulness low
    if recall >= 0.5 and faith < 0.5:
        return "hallucination"

    # Citation theater: many citation markers but low faithfulness
    markers = len(re.findall(r"\[\d+\]", metrics.get("_answer_for_classify", "")))
    if markers >= 3 and faith < 0.5:
        return "citation_theater"

    # Noisy retrieval
    if precision < 0.4:
        return "noisy_retrieval"

    # Temporal staleness — heuristic: mode=search but the answer references obviously stale year
    return "low_quality"


# ── Grader (composes all metrics) ────────────────────────────────────────────

async def grade(
    *,
    judge_client: httpx.AsyncClient,
    q: dict,
    pipeline: dict,
) -> dict:
    """Compute all metrics for one question."""
    key_facts = q.get("key_facts") or []
    answer = pipeline.get("answer", "")
    chunks = pipeline.get("chunks") or []
    sub_queries = pipeline.get("sub_queries") or []
    actual_mode = pipeline.get("mode", "search")
    actual_sub_count = len(sub_queries) if sub_queries else 1
    expected_mode = q.get("expected_mode", "search")
    expected_sub_count = q.get("expected_sub_query_count", "single")
    question = q["question"]

    # v9: "either" means BOTH parametric and search are defensible. For
    # retrieval-side metrics (recall, precision, faithfulness) we use the
    # ACTUAL mode so the question is graded against what the system actually
    # did, not penalized for the tolerant label.
    effective_expected_mode = actual_mode if expected_mode == "either" else expected_mode

    # Heuristics (instant)
    m_recall = metric_context_recall(key_facts, chunks, effective_expected_mode)
    m_correctness_heuristic, heuristic_hits = metric_answer_correctness_heuristic(key_facts, answer)
    m_routing = metric_routing_decomposition(actual_mode, actual_sub_count, expected_mode, expected_sub_count)

    # Parallel LLM-driven metrics
    faith_t, precision_t, correctness_t, relevancy_t = await asyncio.gather(
        metric_faithfulness(judge_client, answer, chunks, effective_expected_mode),
        metric_context_precision(judge_client, question, chunks, effective_expected_mode),
        metric_answer_correctness(judge_client, answer, key_facts,
                                  m_correctness_heuristic, heuristic_hits),
        metric_answer_relevancy(question, answer),
        return_exceptions=True,
    )

    def _val(r, default):
        return r if isinstance(r, dict) else default

    faith   = _val(faith_t,      {"score": 0.5, "supported": 0, "total": 0, "reasoning": "err"})
    prec    = _val(precision_t,  {"score": 0.5, "relevant": 0, "total": 0, "reasoning": "err"})
    correct = _val(correctness_t, {"score": m_correctness_heuristic, "hit_facts": [], "missed_facts": []})
    relev   = _val(relevancy_t,  {"score": 0.0, "method": "embedding", "error": "err"})

    aggregate = round(statistics.mean([
        faith["score"], m_recall, prec["score"], correct["score"], m_routing
    ]), 3)

    verdict = "pass" if aggregate >= 0.8 else ("partial" if aggregate >= 0.4 else "fail")

    metrics_short = {
        "faithfulness":            faith["score"],
        "context_recall":          m_recall,
        "context_precision":       prec["score"],
        "answer_correctness":      correct["score"],
        "routing_decomposition":   m_routing,
        "answer_relevancy":        relev["score"],
        "aggregate":               aggregate,
        "_answer_for_classify":    answer,
    }
    failure_mode = classify_failure(metrics_short, q, actual_mode)
    metrics_short.pop("_answer_for_classify", None)

    return {
        "verdict":  verdict,
        "aggregate": aggregate,
        "failure_mode": failure_mode,
        "metrics": metrics_short,
        "metric_details": {
            "faithfulness":        faith,
            "context_precision":   prec,
            "answer_correctness":  correct,
            "answer_relevancy":    relev,
            "context_recall_hits": [f for f in key_facts if _matches_fact(f, " ".join(c.get("chunk_text","") for c in chunks))],
        },
    }


# ── Phase orchestration ──────────────────────────────────────────────────────

async def run_one_question(
    *,
    http_client: httpx.AsyncClient,
    judge_client: httpx.AsyncClient,
    base_url: str,
    q: dict,
    session_id: str,
    sem_pipeline: asyncio.Semaphore,
    sem_grade: asyncio.Semaphore,
    trace: bool = False,
) -> dict:
    # Eval-aware cache policy:
    # - "paraphrase_cache" category: cache ON (so pc2 can hit pc1's stored answer)
    # - everything else: cache OFF (no leakage between eval runs / categories)
    cache = "on" if q.get("category") == "paraphrase_cache" else "off"
    async with sem_pipeline:
        pipeline = await run_pipeline_via_api(http_client, base_url, q["question"], session_id,
                                              trace=trace, cache=cache)
    async with sem_grade:
        if pipeline.get("error"):
            graded = {
                "verdict": "fail", "aggregate": 0.0, "failure_mode": "pipeline_error",
                "metrics": {"faithfulness": 0.0, "context_recall": 0.0,
                            "context_precision": 0.0, "answer_correctness": 0.0,
                            "routing_decomposition": 0.0, "answer_relevancy": 0.0,
                            "aggregate": 0.0},
                "metric_details": {"error": pipeline["error"]},
            }
        else:
            graded = await grade(judge_client=judge_client, q=q, pipeline=pipeline)
    return {"q": q, "pipeline": pipeline, "graded": graded, "session_id": session_id}


async def run_scenario(
    *,
    http_client: httpx.AsyncClient,
    judge_client: httpx.AsyncClient,
    base_url: str,
    scenario: dict,
    sem_grade: asyncio.Semaphore,
    trace: bool = False,
) -> dict:
    """Multi-turn scenario: turns run SERIALLY within one session_id."""
    session_id = f"eval-mt-{scenario['id']}-{uuid.uuid4().hex[:8]}"
    turns_out: list = []
    for turn in scenario["turns"]:
        # Each turn re-uses the same session so server-side history accumulates.
        q = {
            "id": f"{scenario['id']}-t{turn['turn']}",
            "category": "multiturn",
            "domain": "multiturn",
            "question": turn["question"],
            "expected_mode": "search",
            "expected_sub_query_count": "single",
            "expected_behavior": turn.get("expected_behavior", ""),
            "key_facts": turn.get("key_facts", []),
            "ground_truth": "",
            "tags": scenario.get("tags", []),
            "_scenario": scenario["id"],
            "_turn_index": turn["turn"],
        }
        # Multi-turn: cache OFF (each turn should be a fresh decision).
        pipeline = await run_pipeline_via_api(http_client, base_url, turn["question"], session_id,
                                              trace=trace, cache="off")
        async with sem_grade:
            graded = await grade(judge_client=judge_client, q=q, pipeline=pipeline) if not pipeline.get("error") else {
                "verdict": "fail", "aggregate": 0.0, "failure_mode": "pipeline_error",
                "metrics": {"faithfulness": 0.0, "context_recall": 0.0,
                            "context_precision": 0.0, "answer_correctness": 0.0,
                            "routing_decomposition": 0.0, "answer_relevancy": 0.0,
                            "aggregate": 0.0},
                "metric_details": {"error": pipeline.get("error")},
            }
        turns_out.append({"q": q, "pipeline": pipeline, "graded": graded})
    return {"scenario": scenario, "session_id": session_id, "turns": turns_out}


# ── Output writers ───────────────────────────────────────────────────────────

def _slug(text: str, n: int = 50) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text[:n]).strip("_")
    return s or "q"


def _write_per_question(out_dir: Path, idx: int, q: dict, pipeline: dict, graded: dict, session_id: str) -> None:
    per = out_dir / "per_question"
    per.mkdir(parents=True, exist_ok=True)
    fname = f"{idx:02d}_{q['category']}_{_slug(q['question'])}.json"

    # Pull a one-liner reasoning summary from whichever judge made the most
    # informative call. Used by the eval frontend's "Judge reasoning" section.
    details = graded.get("metric_details", {}) or {}
    judge_reasoning = (
        (details.get("faithfulness", {}) or {}).get("reasoning")
        or (details.get("context_precision", {}) or {}).get("reasoning")
        or (details.get("answer_correctness", {}) or {}).get("reasoning")
        or ""
    )

    breakdown = pipeline.get("latency_breakdown", {}) or {}
    metrics = graded.get("metrics", {}) or {}

    record = {
        "id":               q["id"],
        "category":         q["category"],
        "domain":           q.get("domain", ""),
        "question":         q["question"],
        "expected_mode":    q.get("expected_mode"),
        "expected_sub_query_count": q.get("expected_sub_query_count"),
        "expected_behavior": q.get("expected_behavior", ""),
        "key_facts":        q.get("key_facts", []),
        "ground_truth":     q.get("ground_truth", ""),
        "session_id":       session_id,
        "verdict":          graded["verdict"],
        "aggregate":        graded["aggregate"],
        "failure_mode":     graded.get("failure_mode"),
        # v7 metric names (canonical)
        "metrics": {
            **metrics,
            # Legacy aliases so the existing frontend eval-adapter keeps working
            # (it reads m1/m3/m7 keys). When a future frontend update lands,
            # these can be removed.
            "m1_factual_correctness": metrics.get("answer_correctness"),
            "m3_retrieval_recall":    metrics.get("context_recall"),
            "m7_judge_score":         metrics.get("aggregate"),
        },
        "metric_details":   details,
        # Top-level fields the eval frontend reads via `q.timing.*` and `q.judge_reasoning`.
        "timing": {
            "latency_breakdown": breakdown,
            "total_latency_ms":  pipeline.get("total_latency_ms", 0),
            "pipeline_s":        pipeline.get("elapsed_s", 0),
        },
        "judge_reasoning":   judge_reasoning,
        "pipeline": {
            "answer":           pipeline.get("answer", ""),
            "mode":             pipeline.get("mode"),
            "rewritten_query":  pipeline.get("rewritten_query"),
            "rewrote":          pipeline.get("rewrote"),
            "rationale":        pipeline.get("rationale"),
            "sub_queries":      pipeline.get("sub_queries", []),
            "citations":        pipeline.get("citations", []),
            # Keep URLs as objects (url/title/snippet) so the frontend trace
            # renders the source list properly.
            "urls":             pipeline.get("urls", []),
            "chunk_count":      len(pipeline.get("chunks", [])),
            "chunks":            pipeline.get("chunks", []),
            "latency_breakdown": breakdown,
            "total_latency_ms":  pipeline.get("total_latency_ms", 0),
            "elapsed_s":         pipeline.get("elapsed_s", 0),
            "token_cost":        pipeline.get("token_cost", {}),
            "error":             pipeline.get("error"),
        },
    }
    (per / fname).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _aggregate_failure_modes(records: list) -> dict:
    counts: dict[str, int] = {}
    for r in records:
        fm = r.get("graded", {}).get("failure_mode")
        if fm:
            counts[fm] = counts.get(fm, 0) + 1
    return counts


def _write_summary(out_dir: Path, mode: str, timestamp: str, records: list, qfile_meta: dict) -> dict:
    """Compute summary stats and write summary.json. Returns summary dict."""
    if not records:
        summary = {"meta": {"mode": mode, "timestamp": timestamp, "total": 0}, "metrics": {}}
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def _avg(key: str) -> float:
        vals = [r["graded"]["metrics"].get(key, 0.0) for r in records]
        return round(statistics.mean(vals), 3) if vals else 0.0

    pass_n    = sum(1 for r in records if r["graded"]["verdict"] == "pass")
    partial_n = sum(1 for r in records if r["graded"]["verdict"] == "partial")
    fail_n    = sum(1 for r in records if r["graded"]["verdict"] == "fail")
    latencies = [r["pipeline"].get("elapsed_s", 0) for r in records]
    total_cost = sum(r["pipeline"].get("token_cost", {}).get("cost_usd", 0) for r in records)

    by_category: dict[str, list] = {}
    for r in records:
        by_category.setdefault(r["q"]["category"], []).append(r)

    category_summary = {
        cat: {
            "n":            len(rows),
            "avg_aggregate": round(statistics.mean([r["graded"]["aggregate"] for r in rows]), 3),
            "pass":         sum(1 for r in rows if r["graded"]["verdict"] == "pass"),
            "partial":      sum(1 for r in rows if r["graded"]["verdict"] == "partial"),
            "fail":         sum(1 for r in rows if r["graded"]["verdict"] == "fail"),
        }
        for cat, rows in by_category.items()
    }

    mode_dist: dict[str, int] = {}
    for r in records:
        m = r["pipeline"].get("mode", "search")
        mode_dist[m] = mode_dist.get(m, 0) + 1

    summary = {
        "meta": {
            "mode":            mode,
            "timestamp":       timestamp,
            "total":           len(records),
            "pass":            pass_n,
            "partial":         partial_n,
            "fail":            fail_n,
            "avg_latency_s":   round(statistics.mean(latencies), 2) if latencies else 0.0,
            "p95_latency_s":   round(sorted(latencies)[int(0.95 * (len(latencies)-1))], 2) if latencies else 0.0,
            "total_judge_cost_usd": round(total_cost, 4),
            "bench_version":   qfile_meta.get("version", "unknown"),
        },
        "metrics_avg": {
            "faithfulness":          _avg("faithfulness"),
            "context_recall":        _avg("context_recall"),
            "context_precision":     _avg("context_precision"),
            "answer_correctness":    _avg("answer_correctness"),
            "routing_decomposition": _avg("routing_decomposition"),
            "answer_relevancy":      _avg("answer_relevancy"),
            "aggregate":             _avg("aggregate"),
        },
        "category_summary":   category_summary,
        "failure_modes":      _aggregate_failure_modes(records),
        "actual_mode_dist":   mode_dist,
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def _write_report(out_dir: Path, summary: dict, records: list) -> None:
    m = summary["meta"]
    a = summary["metrics_avg"]
    lines = [
        f"# WebLens Eval Report — {m['mode'].upper()}",
        f"**Timestamp**: {m['timestamp']}  ",
        f"**Bench version**: {m['bench_version']}",
        "",
        "## Score Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| **Aggregate (mean of 5 core)** | **{a['aggregate']:.3f}** |",
        f"| Faithfulness | {a['faithfulness']:.3f} |",
        f"| Context Recall | {a['context_recall']:.3f} |",
        f"| Context Precision | {a['context_precision']:.3f} |",
        f"| Answer Correctness | {a['answer_correctness']:.3f} |",
        f"| Routing & Decomposition | {a['routing_decomposition']:.3f} |",
        f"| Answer Relevancy (diagnostic) | {a['answer_relevancy']:.3f} |",
        "",
        f"**Verdicts**: ✅ {m['pass']} pass · ⚠️ {m['partial']} partial · ❌ {m['fail']} fail (of {m['total']})  ",
        f"**Latency**: avg {m['avg_latency_s']}s · p95 {m['p95_latency_s']}s  ",
        f"**Judge cost**: ${m['total_judge_cost_usd']:.4f} total",
        "",
        "## Mode Distribution (actual routing)",
        "",
        "| Mode | Count |",
        "|---|---|",
    ]
    for mode, n in sorted(summary.get("actual_mode_dist", {}).items()):
        lines.append(f"| {mode} | {n} |")

    lines += [
        "",
        "## Per-Category Breakdown",
        "",
        "| Category | N | Avg | Pass | Partial | Fail |",
        "|---|---|---|---|---|---|",
    ]
    for cat, stats in sorted(summary["category_summary"].items()):
        lines.append(f"| {cat} | {stats['n']} | {stats['avg_aggregate']:.3f} "
                     f"| {stats['pass']} | {stats['partial']} | {stats['fail']} |")

    lines += [
        "",
        "## Per-Question Results",
        "",
        "| # | ID | Category | Verdict | Agg | Faith | C-Rec | C-Prec | Correct | Route | Lat |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(records, 1):
        g = r["graded"]
        met = g["metrics"]
        p = r["pipeline"]
        lines.append(
            f"| {i} | {r['q']['id']} | {r['q']['category']} | {g['verdict']} "
            f"| {g['aggregate']:.2f} | {met['faithfulness']:.2f} | {met['context_recall']:.2f} "
            f"| {met['context_precision']:.2f} | {met['answer_correctness']:.2f} "
            f"| {met['routing_decomposition']:.2f} | {p.get('elapsed_s', 0):.1f}s |"
        )

    fm = summary.get("failure_modes") or {}
    if fm:
        lines += ["", "## Failure-mode distribution", "", "| Mode | Count |", "|---|---|"]
        for k, v in sorted(fm.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v} |")

    lines += ["", f"*Generated {m['timestamp']} · WebLens Eval v7*"]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_failures(out_dir: Path, summary: dict, records: list) -> None:
    """failures.md — focused failure analysis for the worst 5-10 questions."""
    sorted_records = sorted(records, key=lambda r: r["graded"]["aggregate"])
    worst = sorted_records[:10]
    fm = summary.get("failure_modes") or {}

    lines = [
        f"# Failure Analysis — {summary['meta']['mode'].upper()}",
        f"*{summary['meta']['timestamp']}*",
        "",
        "## Failure-mode distribution",
        "",
    ]
    if fm:
        for k, v in sorted(fm.items(), key=lambda x: -x[1]):
            lines.append(f"- **{k}**: {v}")
    else:
        lines.append("No failures classified above the partial threshold.")
    lines.append("")

    lines += ["## Worst-scoring questions", ""]
    for i, r in enumerate(worst, 1):
        if r["graded"]["aggregate"] >= 0.8:
            continue
        q = r["q"]
        g = r["graded"]
        p = r["pipeline"]
        details = g.get("metric_details", {})
        faith = details.get("faithfulness", {})
        prec = details.get("context_precision", {})
        corr = details.get("answer_correctness", {})

        lines += [
            f"### {i}. `{q['id']}` — {q['category']} — verdict={g['verdict']} (agg={g['aggregate']:.2f})",
            "",
            f"**Question**: {q['question']}",
            "",
            f"**Probable cause**: `{g.get('failure_mode') or 'low_quality'}`",
            "",
            f"**Expected**: {q.get('expected_behavior','')}",
            "",
            "**Metrics**:",
            "",
            f"- Faithfulness: {g['metrics']['faithfulness']:.2f} — {faith.get('reasoning','')[:120]}",
            f"- Context Recall: {g['metrics']['context_recall']:.2f}",
            f"- Context Precision: {g['metrics']['context_precision']:.2f} — {prec.get('reasoning','')[:120]}",
            f"- Answer Correctness: {g['metrics']['answer_correctness']:.2f} (missed: {corr.get('missed_facts', [])[:5]})",
            f"- Routing: {g['metrics']['routing_decomposition']:.2f} (expected mode={q.get('expected_mode')}, actual={p.get('mode')}, expected_count={q.get('expected_sub_query_count')}, actual={len(p.get('sub_queries', []))})",
            "",
            f"**Answer (first 400 chars)**: {(p.get('answer','') or '')[:400]}",
            "",
            f"**Citations**: {len(p.get('citations', []))}  · **Sub-queries**: {p.get('sub_queries', [])}",
            "",
            "---",
            "",
        ]

    (out_dir / "failures.md").write_text("\n".join(lines), encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────────────

async def main(mode: str, base_url: str, trace: str, judge: Optional[str], concurrency: int) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # v9: smoke runs live under results/smoke/{ts}; full/multiturn stay at results/{ts}_{mode}
    if mode == "smoke":
        out_dir = RESULTS_DIR / "smoke" / timestamp
    else:
        out_dir = RESULTS_DIR / f"{timestamp}_{mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy source question file into the run dir for traceability — answers
    # the "which question set produced this run?" question without grepping logs.
    try:
        bench_src = EVALS_DIR / "question_dataset" / ("multiturn.json" if mode == "multiturn" else "benchmark.json")
        if bench_src.exists():
            import shutil
            shutil.copy(bench_src, out_dir / "questions.json")
    except Exception:
        pass

    # ── Configure tracing ────────────────────────────────────────────────────
    # trace_enabled is sent as X-Langsmith-Trace header per request to the server.
    # The server uses tracing_context(enabled=...) per request, so tracing is
    # opt-in only during eval runs — it never affects normal traffic.
    trace_enabled = (trace == "on")
    os.environ["EVAL_RUN_ID"] = timestamp
    os.environ["EVAL_MODE"] = mode
    if judge:
        os.environ["WEBLENS_EVAL_JUDGE"] = judge

    log_fh = open(out_dir / "eval.log", "w", encoding="utf-8", buffering=1)

    def _log(line: str) -> None:
        print(line)
        log_fh.write(line + "\n")

    _log("=" * 72)
    _log(f"WebLens Eval v7 — mode={mode.upper()} concurrency={concurrency} trace={trace}")
    _log(f"Server: {base_url}")
    _log(f"Output: {out_dir}")
    _log("=" * 72)

    bench = load_benchmark(mode)
    questions = bench["questions"]
    scenarios = bench["scenarios"]
    qfile_meta = bench["bench_meta"]

    _log(f"Loaded {len(questions)} single-turn questions and {len(scenarios)} multi-turn scenarios.")

    sem_pipeline = asyncio.Semaphore(concurrency)
    sem_grade    = asyncio.Semaphore(concurrency * 2)

    # ── Snapshot query_cache before run (for cached_rows.json diff) ──────────
    baseline_hashes: set[str] = set()
    async with httpx.AsyncClient(timeout=15.0) as snap_client:
        try:
            snap_resp = await snap_client.get(f"{base_url}/api/admin/query_cache/snapshot")
            if snap_resp.status_code == 200:
                baseline_hashes = set(snap_resp.json().get("hashes", []))
                _log(f"Cache snapshot: {len(baseline_hashes)} existing row(s) before run.")
        except Exception as exc:
            _log(f"Cache snapshot failed (non-fatal): {exc}")

    async with httpx.AsyncClient(timeout=200.0) as http_client, \
               httpx.AsyncClient(timeout=60.0)  as judge_client:

        # ── Phase 1: single-turn pipelines + grading (concurrent) ────────────
        t_phase1 = time.monotonic()
        single_tasks = [
            run_one_question(
                http_client=http_client, judge_client=judge_client,
                base_url=base_url, q=q,
                session_id=f"eval-{timestamp}-{q['id']}",
                sem_pipeline=sem_pipeline, sem_grade=sem_grade,
                trace=trace_enabled,
            )
            for q in questions
        ]
        single_records: list = []
        if single_tasks:
            for i, fut in enumerate(asyncio.as_completed(single_tasks), 1):
                rec = await fut
                single_records.append(rec)
                g = rec["graded"]
                p = rec["pipeline"]
                _log(f"[{i}/{len(single_tasks)}] {rec['q']['id']:>5} "
                     f"verdict={g['verdict']:<8} agg={g['aggregate']:.2f} "
                     f"mode={p.get('mode','?'):<10} t={p.get('elapsed_s',0):.1f}s")
        # Preserve original benchmark order in records
        order = {q["id"]: i for i, q in enumerate(questions)}
        single_records.sort(key=lambda r: order.get(r["q"]["id"], 999))
        phase1_s = round(time.monotonic() - t_phase1, 1)
        _log(f"Phase 1 (single-turn) done in {phase1_s}s")

        # ── Phase 2: multi-turn scenarios (parallel scenarios, serial turns) ──
        all_turn_records: list = []
        if scenarios:
            t_phase2 = time.monotonic()
            scenario_tasks = [
                run_scenario(
                    http_client=http_client, judge_client=judge_client,
                    base_url=base_url, scenario=s, sem_grade=sem_grade,
                    trace=trace_enabled,
                )
                for s in scenarios
            ]
            scenario_results: list = []
            for i, fut in enumerate(asyncio.as_completed(scenario_tasks), 1):
                res = await fut
                scenario_results.append(res)
                _log(f"[scenario {i}/{len(scenario_tasks)}] {res['scenario']['id']}: "
                     f"{len(res['turns'])} turns")
            for sr in scenario_results:
                for t in sr["turns"]:
                    # Reformat as a flat record for shared writers
                    all_turn_records.append({
                        "q": t["q"],
                        "pipeline": t["pipeline"],
                        "graded": t["graded"],
                        "session_id": sr["session_id"],
                    })
            phase2_s = round(time.monotonic() - t_phase2, 1)
            _log(f"Phase 2 (multi-turn) done in {phase2_s}s")

    # Combine for downstream writers (single + multiturn turns are both "records")
    records: list = []
    for r in single_records:
        records.append({**r, "session_id": r.get("session_id") or f"eval-{timestamp}-{r['q']['id']}"})
    records.extend(all_turn_records)

    # ── Phase 3: per-question files ──────────────────────────────────────────
    _log("Writing per-question files…")
    for idx, r in enumerate(records, 1):
        _write_per_question(out_dir, idx, r["q"], r["pipeline"], r["graded"],
                            r.get("session_id") or "unknown")

    # ── Phase 4: summary + report + failures ─────────────────────────────────
    summary = _write_summary(out_dir, mode, timestamp, records, qfile_meta)
    _write_report(out_dir, summary, records)
    _write_failures(out_dir, summary, records)

    # ── Phase 4b: diff cache + write cached_rows.json ────────────────────────
    # Records which query_cache rows were CREATED during this eval run so:
    # a) users can inspect what got cached
    # b) Phase 5 can delete exactly those rows (not pre-existing ones)
    cached_rows: list = []
    async with httpx.AsyncClient(timeout=15.0) as diff_client:
        try:
            diff_resp = await diff_client.post(
                f"{base_url}/api/admin/query_cache/diff",
                json={"baseline_hashes": list(baseline_hashes)},
            )
            if diff_resp.status_code == 200:
                cached_rows = diff_resp.json().get("new_rows", [])
                if cached_rows:
                    (out_dir / "cached_rows.json").write_text(
                        json.dumps(cached_rows, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                    _log(f"Cache diff: {len(cached_rows)} new row(s) written to cached_rows.json")
                else:
                    _log("Cache diff: no new rows inserted during this run.")
        except Exception as exc:
            _log(f"Cache diff failed (non-fatal): {exc}")

    # ── Phase 5: cleanup eval state ──────────────────────────────────────────
    # - Drop eval session rows so the chat sidebar stays clean.
    # - Delete exactly the cache rows created during THIS run (from cached_rows.json diff).
    try:
        async with httpx.AsyncClient(timeout=20) as cleanup:
            r1 = await cleanup.delete(f"{base_url}/api/eval/sessions")
            n_sessions = r1.json().get("deleted", 0) if r1.status_code == 200 else 0
            # Delete precisely the new rows from this run (not pre-existing cache)
            n_cache = 0
            if cached_rows:
                for row in cached_rows:
                    q_text = row.get("query_text", "")
                    if q_text:
                        rr = await cleanup.post(f"{base_url}/api/admin/query_cache/delete",
                                                json={"query": q_text})
                        if rr.status_code == 200:
                            n_cache += rr.json().get("deleted", 0)
            else:
                # Fallback: delete paraphrase_cache category queries by rewritten query
                for r in records:
                    if r["q"].get("category") == "paraphrase_cache":
                        rr = await cleanup.post(f"{base_url}/api/admin/query_cache/delete",
                                                json={"query": r["pipeline"].get("rewritten_query") or r["q"]["question"]})
                        if rr.status_code == 200:
                            n_cache += rr.json().get("deleted", 0)
            _log(f"Cleanup: deleted {n_sessions} eval session(s), {n_cache} cache row(s)")
    except Exception as exc:
        _log(f"Cleanup failed (non-fatal): {exc}")

    _log("")
    _log("=" * 72)
    _log(f"Done. Results → {out_dir}")
    _log("=" * 72)
    a = summary["metrics_avg"]
    m_meta = summary["meta"]
    _log(f"Aggregate: {a['aggregate']:.3f} | "
         f"Faith {a['faithfulness']:.2f} | Recall {a['context_recall']:.2f} | "
         f"Precision {a['context_precision']:.2f} | Correct {a['answer_correctness']:.2f} | "
         f"Routing {a['routing_decomposition']:.2f}")
    _log(f"Pass {m_meta['pass']} · Partial {m_meta['partial']} · Fail {m_meta['fail']} "
         f"(of {m_meta['total']}) · avg {m_meta['avg_latency_s']}s/Q · ${m_meta['total_judge_cost_usd']:.4f}")
    log_fh.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebLens RAG eval harness v7")
    parser.add_argument("--smoke",     action="store_true", help="6 questions (one per major category)")
    parser.add_argument("--full",      action="store_true", help="30 single-turn questions")
    parser.add_argument("--multiturn", action="store_true", help="5 multi-turn scenarios")
    parser.add_argument("--all",       action="store_true", help="full + multiturn")
    parser.add_argument("--url",       default=DEFAULT_URL, help="Server base URL")
    parser.add_argument("--trace",     default=None, choices=["on", "off"],
                        help="LangSmith tracing on/off. Default: on for smoke/multiturn, off for full.")
    parser.add_argument("--judge",     default=None, choices=["deepseek", "openai"],
                        help="Judge provider (default: deepseek if key present)")
    parser.add_argument("--concurrency", type=int, default=4, help="Pipeline concurrency (default 4)")
    args = parser.parse_args()

    if args.smoke:      mode = "smoke"
    elif args.full:     mode = "full"
    elif args.multiturn: mode = "multiturn"
    elif args.all:       mode = "all"
    else:
        parser.error("Specify one of --smoke, --full, --multiturn, --all")

    # Default trace policy: on for smoke/multiturn, off for full/all
    trace = args.trace
    if trace is None:
        trace = "on" if mode in ("smoke", "multiturn") else "off"

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(mode=mode, base_url=args.url, trace=trace,
                     judge=args.judge, concurrency=args.concurrency))
