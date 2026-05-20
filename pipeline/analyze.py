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
from pipeline.capabilities import supported_block, unsupported_block

logger = logging.getLogger(__name__)


@dataclass
class AnalyzeResult:
    mode: Literal["parametric", "search", "unsupported"]
    rewritten_query: str
    sub_queries: List[str]
    parametric_answer: Optional[str] = None
    rationale: str = ""
    rewrote: bool = False
    # Phase 1/2 — surfaced for trace visibility and frontend display.
    route_reason: str = ""           # ≤15-word free-text explanation of mode choice
    confidence: Optional[float] = None  # 0.0–1.0; None if LLM omitted it


@dataclass
class RewriteResult:
    """Phase 7 — richer rewriter output. Backwards-compat: callers using the
    legacy (rewritten, changed) tuple are still served by `rewrite_query()`.
    """
    rewritten: str
    changed: bool
    is_topic_switch: bool = False
    active_topic: str = ""
    active_constraints: List[str] = field(default_factory=list)
    clarification: Optional[str] = None
    confidence: Optional[float] = None


# ── Rewriter (Phase 7: JSON output with topic-state) ───────────────────────

_REWRITE_SYSTEM = """\
You are the conversation-rewriter step of WebLens, a multi-turn web-RAG assistant.

Today's date is {today}.

You receive:
  - the user's LATEST message
  - up to 4 prior verbatim turns
  - a rolling summary of older turns (may be empty)
  - the prior `active_topic` and `active_constraints` (may be empty)

Your job is to produce a SELF-CONTAINED rewrite of the latest message AND to
classify whether the conversation is continuing the prior topic or switching to
a new one. The downstream pipeline uses your classification to isolate
retrieval context on topic switches.

## Output format (STRICT)

Output ONE valid JSON object — no prose, no markdown — with this shape:
{{
  "rewritten_query":    string,
  "is_topic_switch":    boolean,
  "active_topic":       string,           // ≤8 words
  "active_constraints": [string, ...],    // ≤6 short items
  "confidence":         number,           // 0.0–1.0
  "clarification":      string | null     // a one-line clarifying question, if needed
}}

## Rewriting rules

- If the latest message stands on its own (names its concrete subject and forms
  a complete question), keep it UNCHANGED in `rewritten_query` — do not blend
  topics from prior turns.
- If the latest message depends on prior context (pronouns like it/this/them/he/she,
  fragments like "and Q3?", "what about Microsoft?", "more like that", or
  transformations like "explain simpler", "in one sentence", "top 30 of those"),
  REWRITE it into a self-contained question that includes the missing subject(s),
  time range, qualifiers — drawn from `active_topic`, `active_constraints`, and
  the recent turns.
- Never answer the question. Only rewrite it.
- Preserve the user's wording style; do not paraphrase aggressively.
- Length cap: ≤300 characters.

## Topic-switch classification

`is_topic_switch = true` ONLY when the latest message introduces a clearly
different subject from the prior topic AND the message stands on its own. A
follow-up like "give me top 30" on a prior "top DSA questions" is CONTINUATION
(is_topic_switch=false), not a switch — extend `active_constraints` with the
new "top 30" requirement and keep `active_topic="DSA interview questions"`.

When `is_topic_switch=true`:
- Reset `active_topic` to the new topic (derived from the latest message).
- Reset `active_constraints` to any constraints stated in the latest message
  (often empty for a fresh question).

When `is_topic_switch=false`:
- KEEP the prior `active_topic` unless the user has explicitly broadened or
  narrowed it; merge new constraints from the latest message into
  `active_constraints` (drop superseded ones).

## active_topic / active_constraints

`active_topic` is a short noun phrase capturing what the conversation is about
right now (e.g. "DSA interview prep", "OpenAI API pricing", "Kyoto autumn trip").
`active_constraints` are the user's stated preferences, filters, scopes, or
quantities — short phrases like "top 30", "in 2026", "less touristy",
"under $100", "for beginners".

## clarification

Set `clarification` to a one-line question ONLY when:
- `confidence < 0.5`, AND
- A specific missing fact would unblock a confident rewrite (e.g. "did you mean
  Microsoft Azure or Microsoft Office?")

Otherwise set `clarification` to null. Prefer null unless truly ambiguous.

## Examples

History (recent): User: "top dsa questions"  Assistant: "[list…]"
Active topic: "DSA interview questions"
Latest: "give me top 30"
=>
{{"rewritten_query":"Give me the top 30 DSA interview questions","is_topic_switch":false,"active_topic":"DSA interview questions","active_constraints":["top 30"],"confidence":0.92,"clarification":null}}

History (recent): User: "What was NVIDIA's revenue in FY2024?"
Latest: "and microsoft"
=>
{{"rewritten_query":"What was Microsoft's revenue in FY2024?","is_topic_switch":false,"active_topic":"Big-tech FY2024 revenue","active_constraints":["FY2024"],"confidence":0.9,"clarification":null}}

History (recent): User: "What is React's reconciliation algorithm?"
Latest: "best Italian restaurants in Rome"
=>
{{"rewritten_query":"best Italian restaurants in Rome","is_topic_switch":true,"active_topic":"Italian restaurants in Rome","active_constraints":[],"confidence":0.97,"clarification":null}}

History: (empty)
Latest: "What is pgvector used for?"
=>
{{"rewritten_query":"What is pgvector used for?","is_topic_switch":false,"active_topic":"pgvector","active_constraints":[],"confidence":0.95,"clarification":null}}

History (recent): User: "OpenAI pricing"  Assistant: "[pricing for various APIs]"
Latest: "what about microsoft?"
=>
{{"rewritten_query":"What is Microsoft's API pricing comparable to OpenAI's?","is_topic_switch":false,"active_topic":"LLM API pricing","active_constraints":[],"confidence":0.7,"clarification":"Did you mean Microsoft Azure OpenAI pricing specifically, or Microsoft Copilot pricing?"}}
"""


# ── Analyze prompt: routes parametric vs search + decomposes ────────────────

_ANALYZE_SYSTEM = """\
You are the routing + planning step of WebLens, a conversational web-RAG assistant. Decide how to handle a user question.

Today's date is **{today}**.

Output ONE valid JSON object — no prose, no markdown — with this shape:
{{
  "mode": "parametric" | "search" | "unsupported",
  "sub_queries": [string, ...],
  "answer": string | null,
  "rationale": string,
  "route_reason": string,
  "confidence": number
}}

## Mode definitions

**parametric** — answer directly from your own knowledge, no web search. The pipeline
will replay your `answer` to the user verbatim. Use for:
- Greetings, chit-chat, small-talk ("hi", "hello", "how are you", "thanks").
- Identity / capability / meta questions ("who are you?", "what can you do?",
  "how does this work?", "what is this app?"). Describe WebLens at a high level —
  it answers questions with cited web sources, supports multi-turn conversation,
  and runs a search → extract → retrieve → generate pipeline under the hood.
- Textbook-stable explanations and definitions where citations add little value and
  the user has not asked for sources. Examples: "what is a hash table", "explain
  transformers", "summarize how TCP works", "what's the chain rule in calculus".
  Keep these answers concise (≤200 words) and accurate.
- Stable factual lookups: arithmetic, basic geography (capitals, well-known
  rivers), classic literature attribution, fundamental science constants.

**search** — run the full web-RAG pipeline. Use for:
- Freshness / recency: news, prices, scores, releases, leaderboards, "latest",
  "recent", "in 2026", "currently", current-year context.
- Named entities of the day, current people / companies / products where details
  drift (revenues, headcounts, valuations, roadmaps).
- Numerical precision that matters: market cap, population, percentages.
- Comparative / subjective questions where reading sources matters: "best X for
  Y in 2026", "X vs Y", reviews, recommendations, "top N courses/tools".
- The user explicitly asks for sources, links, citations, or web info — even on
  an otherwise stable topic.
- Any case where your internal knowledge has non-trivial chance of being stale
  or wrong and a citation would meaningfully help the user.

**unsupported** — the user is asking for an artifact WebLens cannot produce yet.
Set `answer` to a one-sentence polite decline that names the missing capability
and offers what WebLens *can* do instead (e.g. structured text + sources). Set
`sub_queries` to `[original_question]` for trace continuity.

{capabilities_block}

## Bias and tie-breaking

Choose the mode the user is most likely to want. Bias toward `parametric` for
greetings, identity, stable explanations, and definitional questions. Bias toward
`search` for freshness, named entities of the day, comparisons, and explicit
source requests. When genuinely ambiguous, prefer `search` only if there are
freshness/grounding cues; otherwise prefer `parametric` with a short answer.

## sub_queries (only meaningful when mode = "search")

Generate the smallest set of sub-questions that fully covers the question:
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

For `parametric` and `unsupported`, set `sub_queries` to `[original_question]`.

## Output fields

- `answer` — for parametric/unsupported: the response shown to the user (≤200 words for
  parametric, ≤60 words for unsupported). For search: `null`.
- `rationale` — one short sentence (≤20 words) for internal tracing.
- `route_reason` — ≤15-word user-facing explanation (e.g. "greeting", "stable CS concept",
  "current pricing requires sources", "PDF export not supported").
- `confidence` — 0.0–1.0 self-assessed confidence in the mode choice.

## Examples

Q: "hi"
{{"mode":"parametric","sub_queries":["hi"],"answer":"Hi! Ask me anything — I'll search the web, read pages, and answer with cited sources.","rationale":"Greeting.","route_reason":"greeting","confidence":0.98}}

Q: "what can you do?"
{{"mode":"parametric","sub_queries":["what can you do?"],"answer":"I'm WebLens — I answer questions by searching the web, reading the full pages, and citing the sources I used. I support multi-turn conversations and follow-up questions. I don't yet generate PDFs, diagrams, or downloadable files.","rationale":"Capability/meta question.","route_reason":"identity/capability","confidence":0.97}}

Q: "explain transformers"
{{"mode":"parametric","sub_queries":["explain transformers"],"answer":"Transformers are a neural-network architecture introduced in \\"Attention Is All You Need\\" (2017). They replace recurrence with self-attention: each token attends to every other token via learned query/key/value projections, producing weighted context vectors. Stacked layers of multi-head attention plus feed-forward blocks and residual connections enable parallel training and strong long-range modeling, which made them the basis of modern LLMs.","rationale":"Stable ML concept.","route_reason":"textbook ML concept","confidence":0.9}}

Q: "What is 12 squared?"
{{"mode":"parametric","sub_queries":["What is 12 squared?"],"answer":"144.","rationale":"Arithmetic.","route_reason":"arithmetic","confidence":0.99}}

Q: "What is a binary search tree?"
{{"mode":"parametric","sub_queries":["What is a binary search tree?"],"answer":"A binary search tree (BST) is a binary tree where each node has a key, and for every node the keys in its left subtree are less than the node's key and the keys in its right subtree are greater. This ordering enables average-case O(log n) lookup, insert, and delete; worst-case is O(n) for unbalanced trees, motivating self-balancing variants like AVL and red-black trees.","rationale":"Textbook CS concept.","route_reason":"stable CS concept","confidence":0.95}}

Q: "best Udemy courses on Agentic AI"
{{"mode":"search","sub_queries":["Best Udemy courses on Agentic AI in 2026 with ratings and instructors"],"answer":null,"rationale":"Course catalog drifts; needs current sources.","route_reason":"current recommendations require sources","confidence":0.95}}

Q: "Compare PostgreSQL and MySQL for OLTP workloads."
{{"mode":"search","sub_queries":["PostgreSQL strengths and weaknesses for OLTP workloads","MySQL strengths and weaknesses for OLTP workloads"],"answer":null,"rationale":"Comparison benefits from sourced evidence.","route_reason":"comparison benefits from sources","confidence":0.85}}

Q: "Who won the Champions League final in 2024?"
{{"mode":"search","sub_queries":["UEFA Champions League final 2024 winner and score"],"answer":null,"rationale":"Recent sports result.","route_reason":"recent event","confidence":0.97}}

Q: "Export this answer as a PDF"
{{"mode":"unsupported","sub_queries":["Export this answer as a PDF"],"answer":"I can't generate PDFs yet — but I can give you a structured answer with sources that you can copy or print from your browser.","rationale":"Artifact not supported.","route_reason":"PDF export not supported","confidence":0.99}}

Q: "Draw me a diagram of how transformers work"
{{"mode":"unsupported","sub_queries":["Draw me a diagram of how transformers work"],"answer":"I can't generate diagrams yet — but I can describe the transformer architecture in detail with text, and link to diagrams from published sources if you'd like.","rationale":"Artifact not supported.","route_reason":"diagram generation not supported","confidence":0.97}}

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


async def rewrite_query_full(
    query: str,
    history: List[dict],
    history_summary: str = "",
    active_topic: str = "",
    active_constraints: Optional[List[str]] = None,
) -> RewriteResult:
    """Phase 7 — full JSON-output rewriter that returns topic state.

    Returns a `RewriteResult`. On any LLM/parse failure returns a no-op result
    (rewritten=query, is_topic_switch=False, blank topic state) so callers
    never break.
    """
    active_constraints = active_constraints or []
    # No history AND no summary AND no active topic → trivial passthrough.
    if not history and not history_summary and not active_topic:
        return RewriteResult(
            rewritten=query,
            changed=False,
            is_topic_switch=False,
            active_topic="",
            active_constraints=[],
            clarification=None,
            confidence=None,
        )

    llm = get_llm()
    constraints_str = ", ".join(active_constraints) if active_constraints else "(none)"
    user_msg = (
        f"Recent verbatim turns:\n{_format_history(history)}\n\n"
        f"Rolling summary of older turns:\n{history_summary or '(empty)'}\n\n"
        f"Prior active_topic: {active_topic or '(none)'}\n"
        f"Prior active_constraints: {constraints_str}\n\n"
        f"Latest user message: {query}\n\n"
        f"Return the JSON object."
    )
    system = _REWRITE_SYSTEM.format(today=_today())
    try:
        raw = await llm.acomplete(user_msg, system=system, max_tokens=400)
    except Exception as exc:
        logger.debug("[analyze] rewrite_full LLM failed: %s", exc)
        return RewriteResult(rewritten=query, changed=False, active_topic=active_topic,
                             active_constraints=list(active_constraints))

    parsed = _extract_json_object(raw or "")
    if not parsed:
        # Tolerate the legacy plain-text rewrite shape — older deployments / model
        # quirks may return a bare line. Treat the line as the rewrite.
        cleaned = (raw or "").strip().strip('"').strip("'")
        cleaned = re.sub(r"^Rewrite:\s*", "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned and len(cleaned) <= 400:
            changed = cleaned.lower() != query.strip().lower()
            return RewriteResult(rewritten=cleaned, changed=changed,
                                 active_topic=active_topic,
                                 active_constraints=list(active_constraints))
        return RewriteResult(rewritten=query, changed=False, active_topic=active_topic,
                             active_constraints=list(active_constraints))

    rewritten = str(parsed.get("rewritten_query") or query).strip()
    if not rewritten or len(rewritten) > 400:
        rewritten = query

    is_switch = bool(parsed.get("is_topic_switch", False))
    new_topic = str(parsed.get("active_topic") or "").strip()[:120]
    raw_constraints = parsed.get("active_constraints") or []
    if not isinstance(raw_constraints, list):
        raw_constraints = []
    new_constraints = [
        str(c).strip()[:60]
        for c in raw_constraints
        if isinstance(c, (str, int, float)) and str(c).strip()
    ][:6]

    clarification_raw = parsed.get("clarification")
    clarification = (
        str(clarification_raw).strip()[:300]
        if isinstance(clarification_raw, str) and clarification_raw.strip()
        else None
    )

    confidence: Optional[float]
    try:
        c_raw = parsed.get("confidence")
        confidence = float(c_raw) if c_raw is not None else None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
    except Exception:
        confidence = None

    changed = rewritten.lower() != query.strip().lower()
    if changed:
        logger.info(
            "[analyze] rewrote (topic_switch=%s, topic=%r): %r → %r",
            is_switch, new_topic[:40], query[:60], rewritten[:60],
        )

    return RewriteResult(
        rewritten=rewritten,
        changed=changed,
        is_topic_switch=is_switch,
        active_topic=new_topic,
        active_constraints=new_constraints,
        clarification=clarification,
        confidence=confidence,
    )


async def rewrite_query(query: str, history: List[dict]) -> tuple[str, bool]:
    """Legacy entry point — preserved for backwards-compat with the eval
    harness, smoke tests, and any caller using the (rewritten, changed) tuple.

    Internally delegates to `rewrite_query_full()` with empty topic state.
    """
    result = await rewrite_query_full(query, history)
    return result.rewritten, result.changed


async def route_and_decompose(rewritten: str, rewrote: bool) -> AnalyzeResult:
    """Second-stage LLM call: takes an already-rewritten query and returns
    (mode, sub_queries, parametric_answer, rationale).

    Split out from `analyze_query()` so the graph can expose it as its own node
    distinct from the rewrite step. The pair is still composed by `analyze_query()`
    below for callers that want the unified entry point.
    """
    llm = get_llm()
    capabilities_block = f"{supported_block()}\n\n{unsupported_block()}"
    system = _ANALYZE_SYSTEM.format(today=_today(), capabilities_block=capabilities_block)
    try:
        raw = await llm.acomplete(
            f"Analyze this question:\n\n{rewritten}",
            system=system,
            max_tokens=700,
        )
    except Exception as exc:
        logger.warning("[analyze] LLM call failed (%s) — falling back to single-Q search", exc)
        return AnalyzeResult(
            mode="search",
            rewritten_query=rewritten,
            sub_queries=[rewritten],
            rationale="analyze fallback (LLM error)",
            route_reason="router error",
            confidence=None,
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
            route_reason="router parse error",
            confidence=None,
            rewrote=rewrote,
        )

    mode = parsed.get("mode", "search")
    if mode not in ("parametric", "search", "unsupported"):
        mode = "search"

    sub_queries_raw = parsed.get("sub_queries") or [rewritten]
    if not isinstance(sub_queries_raw, list):
        sub_queries_raw = [rewritten]
    sub_queries = [str(q).strip() for q in sub_queries_raw if str(q).strip()][:8]
    if not sub_queries:
        sub_queries = [rewritten]

    parametric_answer = None
    if mode in ("parametric", "unsupported"):
        raw_ans = parsed.get("answer")
        if isinstance(raw_ans, str) and raw_ans.strip():
            # Strip any [N] markers — no chunks → no citations.
            parametric_answer = re.sub(r"\[\d+\]", "", raw_ans).strip()
        else:
            # LLM said parametric/unsupported but didn't supply an answer → fall back to search
            # (only safe for parametric; for unsupported we still need a polite message).
            if mode == "parametric":
                mode = "search"
            else:
                parametric_answer = (
                    "That artifact isn't supported yet, but I can give you a structured "
                    "answer with sources you can copy or share."
                )

    rationale = str(parsed.get("rationale", "")).strip()[:200]
    route_reason = str(parsed.get("route_reason", "")).strip()[:120]

    confidence: Optional[float]
    try:
        c_raw = parsed.get("confidence")
        confidence = float(c_raw) if c_raw is not None else None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
    except Exception:
        confidence = None

    if mode == "parametric":
        logger.info(
            "[analyze] parametric route (conf=%s reason=%r): %s",
            confidence, route_reason, rewritten[:80],
        )
    elif mode == "unsupported":
        logger.info(
            "[analyze] unsupported route (conf=%s reason=%r): %s",
            confidence, route_reason, rewritten[:80],
        )
    elif len(sub_queries) > 1:
        logger.info(
            "[analyze] %d sub-queries (conf=%s) for: %s",
            len(sub_queries), confidence, rewritten[:80],
        )

    return AnalyzeResult(
        mode=mode,
        rewritten_query=rewritten,
        sub_queries=sub_queries,
        parametric_answer=parametric_answer,
        rationale=rationale,
        route_reason=route_reason,
        confidence=confidence,
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
