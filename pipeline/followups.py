"""
Suggested follow-up questions.

Given a user question and the assistant's answer, return 3 short, click-worthy
follow-up questions that meaningfully extend the conversation. Used to render
clickable chips below the citations panel in the chat UI.

Best-effort — any failure returns []. Never blocks the answer.
"""
import json
import logging
import re
from typing import List

from llm.openai_client import get_llm

logger = logging.getLogger(__name__)

_SYSTEM = """\
You suggest follow-up questions a curious user might ask next, given the prior
question and the assistant's answer.

Rules:
- Return EXACTLY 3 follow-up questions.
- Each must be a single short question (≤ 14 words).
- Make them genuinely interesting — surface a comparison, a deeper drill-down,
  a contrasting angle, a related entity, or a "what if". Avoid restating the
  original question.
- Stay grounded in the topic of the answer; don't drift into unrelated subjects.
- Each question must be self-contained (a stranger could understand it without
  the chat context).
- Do not number them. Output ONLY a valid JSON array of 3 strings.

Examples:

Question: What was NVIDIA's revenue in FY2024?
Answer: NVIDIA's FY2024 revenue was $60.9B, up 126% YoY, driven by Data Center …
Output:
["How does NVIDIA's data center revenue compare to AMD's in FY2024?",
 "What were NVIDIA's gross margins in FY2024 and why?",
 "How is NVIDIA guiding revenue for FY2025?"]

Question: How does BM25 work?
Answer: BM25 is a probabilistic ranking function that scores documents using …
Output:
["How does BM25 compare to dense retrieval like SBERT?",
 "What do the k1 and b parameters control in BM25?",
 "When does BM25 outperform learned rankers in practice?"]
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.IGNORECASE)


def _parse_array(raw: str) -> List[str]:
    if not raw:
        return []
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    first, last = text.find("["), text.rfind("]")
    if first == -1 or last == -1 or last <= first:
        return []
    try:
        parsed = json.loads(text[first : last + 1])
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out = [q.strip() for q in parsed if isinstance(q, str) and q.strip()]
    return out[:3]


async def generate_followups(question: str, answer: str) -> List[str]:
    """Return up to 3 follow-up questions. Best-effort; returns [] on failure."""
    if not answer or not answer.strip():
        return []
    # Cap the answer fed to the LLM — we only need topic context.
    answer_excerpt = answer[:1800]
    user_msg = (
        f"Question: {question}\n\nAnswer:\n{answer_excerpt}\n\n"
        f"Now produce 3 follow-up questions as a JSON array."
    )
    llm = get_llm()
    raw = await llm.acomplete(user_msg, system=_SYSTEM, max_tokens=180)
    return _parse_array(raw)
