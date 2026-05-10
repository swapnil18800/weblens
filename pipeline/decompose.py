"""
Query decomposition + conversation-aware query rewriting.

Two-stage flow:
  1. (optional) Rewrite the raw user query into a self-contained question using
     prior turns. Resolves anaphora ("and microsoft", "what about FY2024", "yes").
  2. Decompose the rewritten query into the MINIMUM set of useful sub-questions.

Both stages always go through the LLM — no length / shape heuristics. The user
specifically asked: "make sure all questions pass through llm for analyses and
decomposition, and use a good model for reasoning for decomposition. don't keep
any heuristics."

Returns the list of sub-queries. The caller is responsible for using the
rewritten query downstream — see `decompose_with_rewrite()`.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from llm.openai_client import get_llm

logger = logging.getLogger(__name__)


@dataclass
class DecompositionResult:
    rewritten_query: str         # self-contained version of the user input
    sub_queries: List[str]       # 1..N decomposition
    rewrote: bool                # whether the rewrite changed the input


# ── System prompts ──────────────────────────────────────────────────────────

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

**General principle**: prior context is a tool to *resolve under-specification*,
not a frame to *force every new query into*. If the new query isn't
under-specified, leave it alone.

When in doubt, prefer leaving the query unchanged. A correctly under-specified
query that gets retried is far less harmful than a contaminated rewrite that
returns confidently wrong results.

## Output format

- Output ONLY the rewritten question as plain text.
- No prefixes ("Rewrite:"), no quotes, no JSON.
- Do NOT answer the question. Only rewrite it.
- Do NOT add information that isn't supported by the prior turns or message.

## Examples — continuation (apply context)

History:
- User: What was NVIDIA's revenue in FY2024?
- Assistant: NVIDIA's FY2024 revenue was $60.9B …
Latest: and microsoft
Rewrite: What was Microsoft's revenue in FY2024?

History:
- User: How does BM25 work?
- Assistant: BM25 is a probabilistic ranking function …
Latest: explain its k1 and b parameters
Rewrite: Explain the k1 and b parameters in BM25.

History:
- User: What was Tesla's Q4 revenue?
- Assistant: Tesla's Q4 revenue was $25.2B …
Latest: and Q3?
Rewrite: What was Tesla's Q3 revenue?

History:
- User: Who is the CEO of Anthropic?
- Assistant: Dario Amodei is the CEO of Anthropic.
Latest: When did they start the company?
Rewrite: When did Dario Amodei start Anthropic?

History:
- User: Tell me about the Burj Khalifa.
- Assistant: The Burj Khalifa is a skyscraper in Dubai …
Latest: how tall is it?
Rewrite: How tall is the Burj Khalifa?

History:
- User: Compare AWS vs Azure for startups
- Assistant: …
Latest: which one is cheaper for inference workloads
Rewrite: Between AWS and Azure, which is cheaper for inference workloads for startups?

## Examples — topic shift (DO NOT apply context, keep query unchanged)

History:
- User: What is React's reconciliation algorithm?
- Assistant: React's reconciliation uses a virtual DOM diffing algorithm …
Latest: best Italian restaurants in Rome
Rewrite: best Italian restaurants in Rome

History:
- User: NVIDIA earnings call summary
- Assistant: NVIDIA reported strong Q4 earnings …
Latest: sadhguru vs osho?
Rewrite: sadhguru vs osho?

History:
- User: How does TLS 1.3 handshake work?
- Assistant: TLS 1.3 reduces the handshake to a single round trip …
Latest: weather in Tokyo today
Rewrite: weather in Tokyo today

History: (empty)
Latest: What is pgvector used for?
Rewrite: What is pgvector used for?

## Counter-examples — mistakes to avoid

- WRONG: History "NVIDIA Blackwell" / Latest "best Italian restaurants" →
  rewrite "best Italian restaurants near NVIDIA HQ" — invents a connection
  that wasn't asked for.
- WRONG: History "Apple Q4" / Latest "explain transformers" →
  rewrite "Apple's transformer-related products in Q4" — blends topics.
- WRONG: History "Sam Altman bio" / Latest "history of Pakistan" →
  rewrite "Sam Altman's connection to Pakistan" — fabricates a relationship.
"""

_DECOMPOSE_SYSTEM = """\
You are an expert query decomposition engine.

## Temporal Reasoning

Today's date is **{today}**. Apply these rules to every sub-question you produce:

1. **Current-events queries** — if the user asks about "recent", "latest",
   "this year", "right now", "currently", OR omits any time reference for an
   answer that obviously evolves over time (earnings, prices, leadership,
   product roadmaps, market share, partnerships, regulations): assume the user
   wants information from the **last 12 months ending today**. Phrase
   sub-questions with explicit absolute dates or rolling windows (e.g. "in the
   last 12 months", "in the most recent quarter", or the current calendar
   year and prior quarter).

2. **Do NOT anchor to your training-data defaults.** Never default to a
   specific past fiscal year (e.g. "FY2024") just because that was the most
   recent in your training. If the user did not specify a year, infer the
   rolling window from `{today}`.

3. **For periodic events** (quarterly earnings, monthly reports, annual
   conferences, scheduled releases): the most recent occurrence is the one
   closest to but not after `{today}`. Determine which calendar quarter,
   month, or year that falls in based on `{today}`, not on training-data
   familiarity.

4. **If the user explicitly named a year, quarter, or date, honor it
   exactly** — do not "correct" it to the current year.

5. **Ambiguity escape hatch** — if you cannot infer a window with confidence
   (e.g. the topic is timeless, or the user might mean either historical or
   current), produce sub-questions that don't specify a year — let retrieval
   surface what's available.

Concrete temporal examples:
- "What did NVIDIA's CEO say about Blackwell production timeline in earnings
  calls?" → today is {today} → sub-questions reference the most recent
  earnings calls (current quarter and prior 1–2 quarters), NOT a specific
  past fiscal year that happens to predate today.
- "Latest iPhone release" → today is {today} → assume the most recent annual
  launch relative to today (Apple's pattern is September each year).
- "AMD revenue 2024" → user explicit → keep 2024 even though today is
  newer.

## Decomposition rules

Break the user query into the MINIMUM set of useful sub-questions required to
answer it well.

Rules:
- Do not split mechanically.
- Avoid over-decomposition.
- Separate retrieval from computation when needed.
- For comparisons, decompose by meaningful comparison dimensions.
- Each sub-question must independently help answer the original query.
- Each sub-question must be self-contained (include entity name, time range, etc.).
- Avoid vague or redundant sub-questions.
- Prefer fewer high-quality sub-questions over many shallow ones.
- For purely factual single-entity questions, ONE sub-question is correct.
- For comparisons or multi-part queries, decompose into the natural dimensions.

Return ONLY a JSON array of strings.

-----------------------------------
GOOD DECOMPOSITION EXAMPLES
-----------------------------------

Query:
"What was Microsoft's Intelligent Cloud revenue for FY2022–FY2024 and the YoY growth?"

Output:
[
  "Retrieve Microsoft's Intelligent Cloud revenue for FY2022.",
  "Retrieve Microsoft's Intelligent Cloud revenue for FY2023.",
  "Retrieve Microsoft's Intelligent Cloud revenue for FY2024.",
  "Compute the YoY growth from FY2022 to FY2023.",
  "Compute the YoY growth from FY2023 to FY2024."
]

Why: separates retrieval from computation; isolates calculations cleanly.

-----------------------------------

Query:
"Compare AWS vs Azure for startups"

Output:
[
  "How do AWS and Azure compare in pricing for startups?",
  "How do AWS and Azure compare in ease of use and learning curve?",
  "How do AWS and Azure compare in startup ecosystem support and credits?",
  "How do AWS and Azure compare in scalability and production readiness?"
]

Why: decomposes by comparison dimensions; avoids useless entity definitions.

-----------------------------------

Query:
"Sadhguru vs Osho differences and ashram life"

Output:
[
  "What are the philosophical similarities and differences between Sadhguru and Osho?",
  "How do their meditation and spiritual approaches differ?",
  "How does life in Isha Ashram compare with Osho communes?"
]

Why: captures conceptual and experiential dimensions; avoids shallow biography splits.

-----------------------------------

Query:
"Samsung vs iPhone pricing — where is it cheapest?"

Output:
[
  "How do Samsung and iPhone compare in flagship pricing across regions?",
  "How do Samsung and iPhone compare in mid-range pricing?",
  "Which countries have the cheapest pricing for Samsung flagships and iPhones?"
]

Why: decomposes by pricing tier and the geographic question.

-----------------------------------

Query:
"Meta Reality Labs operating loss FY2022–FY2024"

Output:
[
  "Meta Reality Labs operating loss for FY2022.",
  "Meta Reality Labs operating loss for FY2023.",
  "Meta Reality Labs operating loss for FY2024."
]

Why: each fiscal year is a distinct retrieval target.

-----------------------------------

Query:
"NVIDIA stock rise after ChatGPT launch"

Output:
[
  "How did ChatGPT increase demand for NVIDIA GPUs?",
  "What role does AI training infrastructure play in NVIDIA's growth?",
  "How did investor sentiment around AI affect NVIDIA stock performance?"
]

Why: decomposes causal reasoning into meaningful drivers.

-----------------------------------

Query:
"Best laptop for ML under $1500"

Output:
[
  "Which laptops under $1500 offer strong GPU performance for machine learning?",
  "Which laptops under $1500 offer the best RAM and upgradeability for ML workflows?",
  "Which laptops under $1500 balance portability, thermals, and battery life for ML development?"
]

Why: decomposes recommendation by decision dimensions.

-----------------------------------

Query:
"Evolution of transformers from BERT to GPT-4"

Output:
[
  "What architectural ideas were introduced with BERT?",
  "How did GPT models evolve differently from encoder-based transformers?",
  "What major scaling and training innovations led from early GPT models to GPT-4?"
]

Why: decomposes temporally and conceptually.

-----------------------------------
BAD DECOMPOSITION EXAMPLES
-----------------------------------

Query: "What is Kafka?"
BAD: ["What is Kafka?", "What are Kafka features?", "Why is Kafka used?"]
Why bad: unnecessary decomposition, simple query inflated artificially.
GOOD: ["What is Kafka?"]

Query: "Microsoft cloud revenue growth"
BAD: ["What is Microsoft?", "What is cloud computing?", "What is revenue?"]
Why bad: introduces irrelevant retrieval; doesn't reduce reasoning.

Query: "Samsung vs iPhone"
BAD: ["What is Samsung?", "What is iPhone?"]
Why bad: misses actual comparison dimensions.

Query: "What is the capital of France?"
BAD: ["What is France?", "What is a capital city?"]
Why bad: absurd over-decomposition.
GOOD: ["What is the capital of France?"]

-----------------------------------

Now decompose the user's query.
"""


# ── Helpers ────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.IGNORECASE)


def _extract_json_array(raw: str) -> List[str] | None:
    """Tolerantly extract a JSON array of strings from an LLM response."""
    if not raw:
        return None
    text = raw.strip()
    # Strip code fences if any
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # Heuristic: find the first '[' and last ']'
    first, last = text.find("["), text.rfind("]")
    if first == -1 or last == -1 or last <= first:
        return None
    blob = text[first : last + 1]
    try:
        parsed = json.loads(blob)
    except Exception:
        return None
    if isinstance(parsed, list) and all(isinstance(q, str) for q in parsed):
        cleaned = [q.strip().rstrip(",") for q in parsed if q.strip()]
        return cleaned or None
    return None


def _format_history(history: List[dict]) -> str:
    """Render prior turns as a compact transcript for the rewriter."""
    if not history:
        return "(empty)"
    lines: List[str] = []
    for t in history[-4:]:
        q = (t.get("question") or "").strip()
        a = (t.get("answer") or "").strip()
        # Truncate the answer — only the high-level topic context matters
        if len(a) > 360:
            a = a[:360].rstrip() + " …"
        lines.append(f"- User: {q}")
        if a:
            lines.append(f"- Assistant: {a}")
    return "\n".join(lines)


# ── Public API ─────────────────────────────────────────────────────────────

def _today() -> str:
    """ISO date used to anchor temporal reasoning in both prompts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def rewrite_query(query: str, history: List[dict]) -> tuple[str, bool]:
    """Conversation-aware rewrite. Returns (rewritten, changed). Best-effort —
    on any failure returns the original query unchanged."""
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
        logger.debug("[decompose] rewrite failed (%s)", exc)
        return query, False
    if not raw:
        return query, False
    # Strip quotes / leading "Rewrite:" if the model added them
    rewritten = raw.strip().strip('"').strip("'")
    rewritten = re.sub(r"^Rewrite:\s*", "", rewritten, flags=re.IGNORECASE).strip()
    if not rewritten or len(rewritten) > 400:
        return query, False
    changed = rewritten.lower() != query.strip().lower()
    if changed:
        logger.info("[decompose] rewrote: %r → %r", query[:60], rewritten[:60])
    return rewritten, changed


async def decompose_query(query: str) -> List[str]:
    """LLM-only decomposition. No heuristics. Returns at least [query] on failure."""
    llm = get_llm()
    system = _DECOMPOSE_SYSTEM.format(today=_today())
    try:
        raw = await llm.acomplete(
            f"Decompose this query:\n\n{query}",
            system=system,
            max_tokens=600,
        )
    except Exception as exc:
        logger.warning("[decompose] LLM call failed (%s) — using single-Q fallback", exc)
        return [query]

    parsed = _extract_json_array(raw)
    if parsed is None:
        logger.warning("[decompose] could not parse LLM output, using single-Q fallback")
        return [query]

    # Soft safety cap
    result = parsed[:24]
    if not result:
        return [query]
    if len(result) > 1:
        logger.info("[decompose] %d sub-queries for: %s", len(result), query[:80])
    return result


async def decompose_with_rewrite(
    query: str, history: List[dict],
) -> DecompositionResult:
    """Convenience wrapper: rewrite (if history) then decompose."""
    rewritten, changed = await rewrite_query(query, history)
    sub_queries = await decompose_query(rewritten)
    return DecompositionResult(
        rewritten_query=rewritten,
        sub_queries=sub_queries,
        rewrote=changed,
    )
