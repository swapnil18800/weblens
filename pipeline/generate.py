"""
LLM answer generation — concise, grounded, citation-first.
"""
import logging
from typing import AsyncIterator, List

from llm.openai_client import get_llm
from pipeline.retrieve import RankedChunk

logger = logging.getLogger(__name__)

# ── System prompts ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a precise research assistant answering one sub-question using the numbered sources below.

Rules:
- Length: aim for 150–250 words. Enough to answer well and give downstream synthesis useful context — not a dissertation.
- Cite every specific number, claim, or fact inline with [N]. Multiple [N] markers per sentence are fine when claims draw from multiple chunks.
- Use ONLY the chunks that genuinely support the answer — don't force-cite every chunk. Trust the retrieval ranking.
- Start directly with the answer — no preamble.
- For comparisons with ≥3 items use a compact markdown table.
- If a fact is NOT in any chunk, say "not found in sources" rather than fabricating. Don't approximate or guess.
- Prefer one tight paragraph; use a short heading + paragraph only when structure genuinely helps the reader."""

_SYNTHESIS_SYSTEM = """\
You are a synthesis expert. Merge the sub-answers below into one cohesive final answer to the original question.

Rules:
- Length: 350–500 words. Substantive but not bloated.
- Preserve every specific number, figure, and [N] citation marker from the sub-answers.
- When the question compares ≥2 entities, include a markdown comparison table.
- Structure: a short opening framing, the body (paragraphs or table), then a trailing "## Key Takeaways" section with 3–5 concise bullets.
- Synthesize — don't concatenate. Cut redundancy across sub-answers, surface contrasts and patterns.
- If a sub-answer says "not found in sources", carry that forward honestly."""


# ── Prompt builder ──────────────────────────────────────────────────────────

def _build_prompt(query: str, ranked_chunks: List[RankedChunk]) -> str:
    """Format retrieved chunks as numbered source blocks."""
    citation_map: dict[str, int] = {}
    for rc in ranked_chunks:
        if rc.chunk.url not in citation_map:
            citation_map[rc.chunk.url] = len(citation_map) + 1

    url_chunks: dict[str, list[str]] = {}
    for rc in ranked_chunks:
        url_chunks.setdefault(rc.chunk.url, []).append(rc.chunk.chunk_text)

    source_blocks = []
    for url, num in citation_map.items():
        title = next(
            (rc.chunk.title for rc in ranked_chunks if rc.chunk.url == url), url
        )
        combined = "\n\n".join(url_chunks[url])[:4_000]
        source_blocks.append(f"[{num}] {title}\nURL: {url}\n---\n{combined}")

    sources_text = "\n\n".join(source_blocks)
    citation_legend = "\n".join(f"[{num}] {url}" for url, num in citation_map.items())

    return (
        f"Question: {query}\n\n"
        f"Sources:\n{sources_text}\n\n"
        f"Answer the question using the sources above. "
        f"Cite inline with [N] notation.\n\n"
        f"Citation reference:\n{citation_legend}"
    )


# ── Streaming generators ────────────────────────────────────────────────────

async def generate_stream(
    query: str,
    ranked_chunks: List[RankedChunk],
    max_tokens: int = 900,
) -> AsyncIterator[str]:
    """Stream answer tokens for a single sub-query (concise mode)."""
    if not ranked_chunks:
        yield "No relevant sources found for this question."
        return

    prompt = _build_prompt(query, ranked_chunks)
    llm = get_llm()
    logger.debug("[generate] chunks=%d prompt_chars=%d", len(ranked_chunks), len(prompt))

    async for token in llm.astream(prompt, system=_SYSTEM_PROMPT, max_tokens=max_tokens):
        yield token


async def synthesize_stream(
    original_query: str,
    sub_answers: List[dict],
    max_tokens: int = 1600,
) -> AsyncIterator[str]:
    """
    Synthesize N sub-answers into one final answer.
    sub_answers: list of {query, answer, citations}.
    """
    if not sub_answers:
        return

    if len(sub_answers) == 1:
        for ch in sub_answers[0]["answer"]:
            yield ch
        return

    parts = [
        f"### Sub-answer {i + 1}: {sa['query']}\n{sa['answer']}"
        for i, sa in enumerate(sub_answers)
    ]
    sub_text = "\n\n---\n\n".join(parts)

    prompt = (
        f"Original question: {original_query}\n\n"
        f"You have {len(sub_answers)} sub-answers. "
        f"Synthesize into one concise final answer.\n\n"
        f"{sub_text}"
    )

    llm = get_llm()
    logger.debug("[synthesize] sub_answers=%d", len(sub_answers))

    async for token in llm.astream(prompt, system=_SYNTHESIS_SYSTEM, max_tokens=max_tokens):
        yield token


def build_citations(ranked_chunks: List[RankedChunk]) -> List[dict]:
    """Return deduplicated citations with snippet for the UI."""
    seen: set = set()
    citations = []
    for rc in ranked_chunks:
        url = rc.chunk.url
        if url not in seen:
            seen.add(url)
            citations.append({
                "num": len(citations) + 1,
                "url": url,
                "title": rc.chunk.title,
                "snippet": rc.chunk.chunk_text[:300],
            })
    return citations
