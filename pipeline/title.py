"""Cheap-LLM session-title generator.

Used to label chat sessions with a short human-readable string instead of
the raw question prefix.  Falls back to the first 60 chars of the question
on any failure (network, parse, missing key).
"""
import logging
import re

from llm.openai_client import get_llm

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Return a 4-7 word title summarizing the user question. "
    "No quotes. No trailing period. Plain text only. "
    "Be specific (mention companies / metrics / years if present)."
)


async def generate_title(question: str) -> str:
    fallback = question.strip()[:60].rstrip()
    q = fallback
    if not q:
        return "Untitled"
    try:
        llm = get_llm()
        raw = await llm.acomplete(q, system=_SYSTEM, max_tokens=24)
        title = re.sub(r'^["\'`\s]+|["\'`.\s]+$', "", raw).strip()
        # Drop any leading "Title:" prefix the model might add
        title = re.sub(r"^(?i:title)\s*[:\-]\s*", "", title)
        if not title or len(title) > 90:
            return fallback
        return title
    except Exception as exc:
        logger.debug("[title] LLM failed (%s), using fallback", exc)
        return fallback
