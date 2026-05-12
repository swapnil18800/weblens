"""
Analyze step — replaces decompose.py.

Two LLM passes in one call (or one combined pass):
  1. Conversation-aware query rewrite (only if history present).
  2. Route + decompose: returns mode ∈ {"parametric", "search"} plus sub-queries
     and, when parametric, the final answer.

Routing bias: heavy default toward SEARCH. The analyze prompt's only
parametric-friendly examples are textbook-stable, 5+ years old, with no
numerical precision at stake. Anything time-sensitive, comparison, or numerical
falls to search even if the LLM "knows" the answer — citations matter.

The rewriter logic is preserved from decompose.py to avoid breaking the
multi-turn behavior the user confirmed is working.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Literal, Optional

from llm.openai_client import get_llm

logger = logging.getLogger(__name__)


@dataclass
class AnalyzeResult:
    mode: Literal["parametric", "search"]
    rewritten_query: str
    sub_queries: List[str]
    parametric_answer: Optional[str] = None
    rationale: str = ""
    rewrote: bool = False


# ── Rewriter (preserved verbatim behavior from decompose.py) ────────────────

_REWRITE_SYSTEM = """\
You are a conversation rewriter for a web-search RAG system.

Today's date is {today}.

Given the conversation history and the user's latest message, produce a single
self-contained question that captures the user's actual intent.

## When to apply conversation history

You receive the latest user message PLUS up to 4 prior turns of conversation.
Decide whether prior turns provide context the latest message NEEDS.

**Apply prior context only if the latest message is dependent on it.** A
message is dependent if it satisfies ANY of these:

- Contains a pronoun referring to a prior subject (it, this, that, they, them,
  the one, the company, the CEO, etc.) without naming the subject explicitly.
- Is a fragment that only makes sense as a continuation (e.g. "and Q3?",
  "what about overseas?", "compared to last year?", a single noun like "Intel.").
- Asks for a transformation of a prior answer ("explain that more simply",
  "give me the source", "summarize", "in one sentence").

**Do NOT apply prior context if the latest message stands on its own.** A
message stands on its own if it names its own concrete subject(s) and forms a
complete question or request, EVEN IF the subject is wildly different from the
prior conversation. In that case, REWRITE THE QUERY UNCHANGED — never blend
topics.

When in doubt, prefer leaving the query unchanged.

## Output format

- Output ONLY the rewritten question as plain text.
- No prefixes ("Rewrite:"), no quotes, no JSON.
- Do NOT answer the question. Only rewrite it.

## Examples — continuation (apply context)

History:
- User: What was NVIDIA's revenue in FY2024?
- Assistant: NVIDIA's FY2024 revenue was $60.9B …
Latest: and microsoft
Rewrite: What was Microsoft's revenue in FY2024?

History:
- User: Tell me about the Burj Khalifa.
- Assistant: The Burj Khalifa is a skyscraper in Dubai …
Latest: how tall is it?
Rewrite: How tall is the Burj Khalifa?

## Examples — topic shift (DO NOT apply context, keep query unchanged)

History:
- User: What is React's reconciliation algorithm?
- Assistant: …
Latest: best Italian restaurants in Rome
Rewrite: best Italian restaurants in Rome

History: (empty)
Latest: What is pgvector used for?
Rewrite: What is pgvector used for?
"""


# ── Analyze prompt: routes parametric vs search + decomposes ────────────────

_ANALYZE_SYSTEM = """\
You are the routing + planning step of a research assistant. Decide how to handle a user question.

Today's date is **{today}**.

Output ONE valid JSON object — no prose, no markdown — with this shape:
{{
  "mode": "parametric" | "search",
  "sub_queries": [string, ...],
  "answer": string | null,
  "rationale": string
}}

CRITICAL: Default to "search". Only choose "parametric" when you are HIGHLY confident the
answer is timeless, well-established, and does not benefit from sources. When in doubt,
choose "search". An incorrect "parametric" choice means the user gets a stale or wrong
answer with no citations — far worse than an unnecessary web fetch.

Choose "parametric" ONLY when ALL of these are true:
- Answer is timeless, textbook-stable, and at least 5 years old in established knowledge.
- A high-school or college textbook would have it. Examples: arithmetic, basic geography
  (capitals, well-known rivers), classic literature attribution, fundamental science
  (water boils at 100°C), elementary CS concepts (what is a hash table).
- The user is NOT asking "according to X", "in 2024", "latest", "recently", or referencing
  any specific source.
- No numerical precision is at stake (no prices, scores, market caps, populations within
  ~10% accuracy — those drift).
- The answer fits in ≤120 words and you can produce it with full confidence.

Choose "search" in every other case, including (but not limited to):
- Time-sensitive: news, prices, scores, releases, "latest", "recent", current year.
- Numerical where precision matters: revenue, population, market share, percentages.
- Comparative / subjective questions where reading sources matters: "best X for Y", "vs", "review".
- Domain-expert questions where you might be confident but a citation is still warranted.
- Anything you are not entirely certain about. Uncertainty → search.

When mode = "parametric": set "answer" to a concise, accurate response (≤120 words). Set
"sub_queries" to [original_question] for trace continuity. The pipeline skips web search.

When mode = "search": set "answer" to null. Generate the smallest set of sub-questions
that fully covers the question:
- 1 sub-question for a single self-contained idea.
- 2–3 for typical comparisons or two-part questions.
- 4–6 for genuine multi-entity × multi-dimension questions.
- Hard ceiling: 8.
- Each sub-question must stand alone — spell out entity names, time ranges, qualifiers.
- Don't fan out a single entity × single metric across years — keep that in one sub-question.
- Drop conversational filler ("can you tell me", "i want to know", "lol pls").

For time-sensitive queries, if the user said "latest" / "recent" / "current" without a
specific year, phrase sub-questions as a rolling window ending today ({today}) — e.g.
"in the last 12 months" or "most recent quarter".

"rationale" is one short sentence (≤20 words) explaining the choice.

Examples:

Q: "What is 12 squared?"
{{"mode":"parametric","sub_queries":["What is 12 squared?"],"answer":"144.","rationale":"Arithmetic, no source needed."}}

Q: "What is the capital of Japan?"
{{"mode":"parametric","sub_queries":["What is the capital of Japan?"],"answer":"Tokyo.","rationale":"Stable geographic fact."}}

Q: "Who wrote Pride and Prejudice?"
{{"mode":"parametric","sub_queries":["Who wrote Pride and Prejudice?"],"answer":"Jane Austen, published in 1813.","rationale":"Classic literature attribution, well-established."}}

Q: "What is a binary search tree?"
{{"mode":"parametric","sub_queries":["What is a binary search tree?"],"answer":"A binary search tree (BST) is a node-based binary tree where each node has a key, and for every node the keys in its left subtree are less than the node's key and the keys in its right subtree are greater. This ordering enables average-case O(log n) lookup, insert, and delete; worst-case is O(n) for unbalanced trees, motivating self-balancing variants (AVL, red-black).","rationale":"Textbook CS concept."}}

Q: "What is the population of Brazil?"
{{"mode":"search","sub_queries":["Current population of Brazil"],"answer":null,"rationale":"Population numbers drift; need a sourced recent figure."}}

Q: "Who won the Champions League final in 2024?"
{{"mode":"search","sub_queries":["UEFA Champions League final 2024 winner and score"],"answer":null,"rationale":"Recent sports result, must be sourced."}}

Q: "Compare PostgreSQL and MySQL for OLTP workloads."
{{"mode":"search","sub_queries":["PostgreSQL strengths and weaknesses for OLTP workloads","MySQL strengths and weaknesses for OLTP workloads"],"answer":null,"rationale":"Comparison benefits from sourced evidence."}}

Q: "What did Microsoft report for cloud revenue in their last quarter?"
{{"mode":"search","sub_queries":["Microsoft most recent quarterly Intelligent Cloud and Azure revenue"],"answer":null,"rationale":"Recent earnings figure, must cite filings."}}

Q: "best places to visit in kyoto in autumn? not too touristy?"
{{"mode":"search","sub_queries":["Best autumn destinations in Kyoto Japan","Less touristy autumn spots in Kyoto for foliage viewing"],"answer":null,"rationale":"Subjective travel question; sources help."}}

Q: "Is intermittent fasting effective for weight loss?"
{{"mode":"search","sub_queries":["Intermittent fasting effectiveness for long-term weight loss meta-analysis","Intermittent fasting risks and limitations"],"answer":null,"rationale":"Contested health topic; sources differ, must surface evidence."}}

Now analyze the user's question.
"""


# ── Helpers ────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.IGNORECASE)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_json_object(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    first, last = text.find("{"), text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        return None
    try:
        return json.loads(text[first : last + 1])
    except Exception:
        return None


def _format_history(history: List[dict]) -> str:
    if not history:
        return "(empty)"
    lines: List[str] = []
    for t in history[-4:]:
        q = (t.get("question") or "").strip()
        a = (t.get("answer") or "").strip()
        if len(a) > 360:
            a = a[:360].rstrip() + " …"
        lines.append(f"- User: {q}")
        if a:
            lines.append(f"- Assistant: {a}")
    return "\n".join(lines)


async def rewrite_query(query: str, history: List[dict]) -> tuple[str, bool]:
    """Conversation-aware rewrite. Returns (rewritten, changed)."""
    if not history:
        return query, False
    llm = get_llm()
    user_msg = (
        f"History:\n{_format_history(history)}\n\n"
        f"Latest: {query}\n\nRewrite:"
    )
    system = _REWRITE_SYSTEM.format(today=_today())
    try:
        raw = await llm.acomplete(user_msg, system=system, max_tokens=200)
    except Exception as exc:
        logger.debug("[analyze] rewrite failed (%s)", exc)
        return query, False
    if not raw:
        return query, False
    rewritten = raw.strip().strip('"').strip("'")
    rewritten = re.sub(r"^Rewrite:\s*", "", rewritten, flags=re.IGNORECASE).strip()
    if not rewritten or len(rewritten) > 400:
        return query, False
    changed = rewritten.lower() != query.strip().lower()
    if changed:
        logger.info("[analyze] rewrote: %r → %r", query[:60], rewritten[:60])
    return rewritten, changed


async def route_and_decompose(rewritten: str, rewrote: bool) -> AnalyzeResult:
    """Second-stage LLM call: takes an already-rewritten query and returns
    (mode, sub_queries, parametric_answer, rationale).

    Split out from `analyze_query()` so the graph can expose it as its own node
    distinct from the rewrite step. The pair is still composed by `analyze_query()`
    below for callers that want the unified entry point.
    """
    llm = get_llm()
    system = _ANALYZE_SYSTEM.format(today=_today())
    try:
        raw = await llm.acomplete(
            f"Analyze this question:\n\n{rewritten}",
            system=system,
            max_tokens=600,
        )
    except Exception as exc:
        logger.warning("[analyze] LLM call failed (%s) — falling back to single-Q search", exc)
        return AnalyzeResult(
            mode="search",
            rewritten_query=rewritten,
            sub_queries=[rewritten],
            rationale="analyze fallback (LLM error)",
            rewrote=rewrote,
        )

    parsed = _extract_json_object(raw)
    if not parsed:
        logger.warning("[analyze] could not parse JSON, falling back to search/single-Q")
        return AnalyzeResult(
            mode="search",
            rewritten_query=rewritten,
            sub_queries=[rewritten],
            rationale="analyze fallback (parse error)",
            rewrote=rewrote,
        )

    mode = parsed.get("mode", "search")
    if mode not in ("parametric", "search"):
        mode = "search"

    sub_queries_raw = parsed.get("sub_queries") or [rewritten]
    if not isinstance(sub_queries_raw, list):
        sub_queries_raw = [rewritten]
    sub_queries = [str(q).strip() for q in sub_queries_raw if str(q).strip()][:8]
    if not sub_queries:
        sub_queries = [rewritten]

    parametric_answer = None
    if mode == "parametric":
        raw_ans = parsed.get("answer")
        if isinstance(raw_ans, str) and raw_ans.strip():
            # Strip any [N] markers a parametric answer accidentally produced — no chunks → no citations.
            parametric_answer = re.sub(r"\[\d+\]", "", raw_ans).strip()
        else:
            # LLM said parametric but didn't supply an answer → fall back to search.
            mode = "search"

    rationale = str(parsed.get("rationale", "")).strip()[:200]

    if mode == "parametric":
        logger.info("[analyze] parametric route: %s", rewritten[:80])
    elif len(sub_queries) > 1:
        logger.info("[analyze] %d sub-queries for: %s", len(sub_queries), rewritten[:80])

    return AnalyzeResult(
        mode=mode,
        rewritten_query=rewritten,
        sub_queries=sub_queries,
        parametric_answer=parametric_answer,
        rationale=rationale,
        rewrote=rewrote,
    )


async def analyze_query(query: str, history: Optional[List[dict]] = None) -> AnalyzeResult:
    """Unified entry point: rewrite → route + decompose.

    The LangGraph pipeline calls `rewrite_query()` and `route_and_decompose()`
    as separate nodes instead, but this preserved-shape function is kept for
    backward compatibility (legacy callers, tests, the eval harness's smoke flow).
    """
    history = history or []
    rewritten, changed = await rewrite_query(query, history)
    return await route_and_decompose(rewritten, changed)
