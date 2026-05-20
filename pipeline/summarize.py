"""
Incremental rolling-summary memory.

Industry-standard `ConversationSummaryBufferMemory` pattern (LangChain): never
re-summarize the entire chat. Each time turns are evicted from the verbatim
buffer, the summarizer is fed only:

  - the existing summary (≤120 words)
  - the evicted turns (the ones falling outside the recent-N window)

…and returns an updated summary of the same bounded size. Per-update cost is
O(1) in turns regardless of conversation length.

This module is intentionally tiny (one LLM call, one prompt). It is called
fire-and-forget from `node_emit_done` AFTER the answer has been fully streamed
to the user, so it adds zero latency to the user-visible critical path.
"""
from __future__ import annotations

import logging
from typing import Iterable

from llm.openai_client import get_llm

logger = logging.getLogger(__name__)

_SUMMARY_WORD_BUDGET = 120
_SUMMARY_MAX_TOKENS = 220  # leaves headroom over the word budget

_SYSTEM = """\
You compress a multi-turn conversation into a tight rolling summary.

Goals (in priority order):
1. Preserve the user's current goals, constraints, preferences, and unresolved tasks.
2. Preserve named entities (people, products, companies, papers, places, datasets).
3. Preserve decisions made and any conclusions the assistant has reached.
4. Drop or supersede stale details when newer turns override them.
5. No filler, no preamble, no headings — output the summary text only.

Hard cap: ≤120 words. Be terse and factual.
"""

_USER_TEMPLATE = """\
Existing summary (may be empty):
{prev_summary}

New exchanges to fold into the summary:
{new_exchanges}

Return the updated ≤120-word summary."""


def _format_exchanges(turns: Iterable[dict]) -> str:
    lines: list[str] = []
    for t in turns:
        q = (t.get("question") or "").strip()
        a = (t.get("answer") or "").strip()
        if len(a) > 400:
            a = a[:400].rstrip() + " …"
        if q:
            lines.append(f"User: {q}")
        if a:
            lines.append(f"Assistant: {a}")
    return "\n".join(lines) or "(none)"


async def incremental_summary(prev_summary: str, evicted_turns: list[dict]) -> str:
    """Fold `evicted_turns` into `prev_summary` via a single small LLM call.

    On any failure returns `prev_summary` unchanged — the rolling summary
    becomes slightly stale for one turn but the conversation is never broken.
    """
    if not evicted_turns:
        return prev_summary or ""
    new_block = _format_exchanges(evicted_turns)
    prompt = _USER_TEMPLATE.format(
        prev_summary=(prev_summary.strip() if prev_summary else "(empty)"),
        new_exchanges=new_block,
    )
    try:
        llm = get_llm()
        raw = await llm.acomplete(prompt, system=_SYSTEM, max_tokens=_SUMMARY_MAX_TOKENS)
    except Exception as exc:
        logger.debug("[summarize] LLM call failed: %s", exc)
        return prev_summary or ""
    if not raw:
        return prev_summary or ""
    out = raw.strip()
    # Defensive word-cap — if the model overshoots, hard-trim.
    words = out.split()
    if len(words) > _SUMMARY_WORD_BUDGET + 30:
        out = " ".join(words[: _SUMMARY_WORD_BUDGET + 30]) + " …"
    return out
