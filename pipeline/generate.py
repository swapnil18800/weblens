"""
LLM answer generation — concise, grounded, citation-first.
"""
import logging
from collections import defaultdict
from typing import AsyncIterator, List

from llm.openai_client import get_llm
from pipeline.retrieve import RankedChunk

logger = logging.getLogger(__name__)

# ── Prompt-packing budget ───────────────────────────────────────────────────
# We pack source blocks round-robin across URLs (instead of capping each URL
# at a fixed char count) so all top-K reranked chunks reach the LLM under a
# single total budget. The previous per-URL 6,000-char hard stop silently
# dropped chunks from URLs that had multiple high-ranking passages, which is
# why the answer often cited fewer chunks than retrieve returned.
#
# Budget is expressed in characters (~4 chars ≈ 1 token). 48,000 chars
# ≈ 12k tokens, well below the model's input limit and large enough for the
# default top_k=8 chunks at ~1500 chars each.
_PROMPT_CHAR_BUDGET = 48_000

# ── System prompts ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a precise research assistant answering one sub-question using the numbered sources below.

Citation discipline (the most important rule):
- Cite every specific number, claim, or fact inline with [N]. EVERY factual sentence
  must end in at least one [N] marker.
- Distribute citations: when multiple sources support a claim, cite multiple [N]s
  in the same sentence (e.g. "...rose 12% [3][7]."). Don't lean on one chunk.
- Aim to use AT LEAST 3 distinct sources when the source list has 3+ chunks. If
  you only end up citing 1–2 sources from a list of 8, you're under-using the
  evidence — go back and weave in more.
- Don't fabricate. If a fact isn't in any chunk, say "not found in sources".

Style:
- Length: 150–250 words.
- Start directly with the answer — no preamble.
- Use markdown for structure: short bolded sub-labels, bullet lists for parallel
  facts, compact tables for any ≥3-way comparison or year-over-year breakdown.
- Avoid long flat paragraphs. Break up multi-claim sentences into bullets when
  it improves scannability.
- For numeric series (e.g. revenue across 3 years), prefer a table over prose."""

_SYNTHESIS_SYSTEM = """\
You are a synthesis expert. Merge the sub-answers below into one cohesive final answer to the original question.

Citation discipline:
- Preserve EVERY [N] marker that the sub-answers used. Don't drop them when
  rewriting.
- When you combine claims from multiple sub-answers, stack citations
  ([N][M]) instead of dropping any.

Length: 350–550 words. Substantive but not bloated.

Structure (use these markdown elements liberally — readers should be able to
scan, not read a wall of text):
- Open with a 1–2 sentence framing of the answer.
- Use `##` section headings to separate distinct dimensions of the answer.
- Use bullet lists for parallel points and short comparisons.
- For ≥2-entity comparisons or numeric series across years, ALWAYS include a
  markdown comparison table. Put the citations in a final "Source" column
  (e.g. `[1][4]`).
- Close with a `## Key Takeaways` section: 3–5 concise bullets.

Synthesize — don't concatenate. Cut redundancy across sub-answers, surface
contrasts and patterns. If a sub-answer says "not found in sources", carry that
forward honestly."""


# ── Prompt builder ──────────────────────────────────────────────────────────

def _format_history_block(history: List[dict]) -> str:
    """Format prior turns as a 'Recent conversation context' block.

    Used by both generate_stream and synthesize_stream so the LLM can resolve
    references the rewriter couldn't fully bake into the rewritten query. The
    block is explicitly labeled 'do NOT cite — only sources' so history can
    never accidentally produce citations.
    """
    if not history:
        return ""
    lines: List[str] = []
    for t in history[-4:]:
        q = (t.get("question") or "").strip()
        a = (t.get("answer") or "").strip()
        if len(a) > 360:
            a = a[:360].rstrip() + " …"
        if q:
            lines.append(f"User: {q}")
        if a:
            lines.append(f"Assistant: {a}")
    if not lines:
        return ""
    block = "\n".join(lines)
    return (
        "Recent conversation context (do NOT cite this, only the numbered sources below):\n"
        f"{block}\n\n"
    )


def _build_prompt(
    query: str,
    ranked_chunks: List[RankedChunk],
    global_citation_map: "dict[str, int] | None" = None,
    history: "List[dict] | None" = None,
) -> str:
    """Format retrieved chunks as numbered per-chunk source blocks.

    When global_citation_map is provided, numbers come from the shared global map so
    every sub-query's LLM prompt uses the same [N] labels as the final answer.
    """
    if global_citation_map is not None:
        citation_map = global_citation_map
    else:
        citation_map = {}
        for rc in ranked_chunks:
            if rc.chunk.url not in citation_map:
                citation_map[rc.chunk.url] = len(citation_map) + 1

    # One block per chunk — LLM sees each passage as a discrete citation target.
    # Round-robin pack across URLs under a shared char budget so all top-K
    # chunks reach the LLM (rather than the previous per-URL hard cap that
    # silently dropped later chunks from the same URL).
    by_url: dict[str, list[RankedChunk]] = defaultdict(list)
    for rc in ranked_chunks:
        if citation_map.get(rc.chunk.url) is not None:
            by_url[rc.chunk.url].append(rc)

    source_blocks: List[str] = []
    used_chars = 0
    dropped = 0
    queues = [list(v) for v in by_url.values()]
    while any(queues):
        for q in queues:
            if not q:
                continue
            rc = q.pop(0)
            num = citation_map[rc.chunk.url]
            block = f"[{num}] {rc.chunk.title}\nURL: {rc.chunk.url}\n---\n{rc.chunk.chunk_text}"
            if used_chars + len(block) > _PROMPT_CHAR_BUDGET:
                dropped += 1 + sum(len(qq) for qq in queues)
                queues = [[] for _ in queues]
                break
            source_blocks.append(block)
            used_chars += len(block)
    if dropped:
        logger.warning(
            "[generate] prompt-budget hit: dropped %d chunks (budget=%d chars)",
            dropped, _PROMPT_CHAR_BUDGET,
        )

    sources_text = "\n\n".join(source_blocks)
    citation_legend = "\n".join(
        f"[{num}] {url}"
        for url, num in sorted(citation_map.items(), key=lambda x: x[1])
        if any(rc.chunk.url == url for rc in ranked_chunks)
    )

    history_block = _format_history_block(history or [])

    return (
        f"{history_block}"
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
    global_citation_map: "dict[str, int] | None" = None,
    max_tokens: int = 900,
    history: "List[dict] | None" = None,
) -> AsyncIterator[str]:
    """Stream answer tokens for a single sub-query (concise mode)."""
    if not ranked_chunks:
        yield "No relevant sources found for this question."
        return

    prompt = _build_prompt(query, ranked_chunks, global_citation_map, history=history)
    llm = get_llm()
    logger.debug("[generate] chunks=%d prompt_chars=%d", len(ranked_chunks), len(prompt))

    async for token in llm.astream(prompt, system=_SYSTEM_PROMPT, max_tokens=max_tokens):
        yield token


async def synthesize_stream(
    original_query: str,
    sub_answers: List[dict],
    max_tokens: int = 1600,
    history: "List[dict] | None" = None,
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

    history_block = _format_history_block(history or [])

    prompt = (
        f"{history_block}"
        f"Original question: {original_query}\n\n"
        f"You have {len(sub_answers)} sub-answers. "
        f"Synthesize into one concise final answer.\n\n"
        f"{sub_text}"
    )

    llm = get_llm()
    logger.debug("[synthesize] sub_answers=%d", len(sub_answers))

    async for token in llm.astream(prompt, system=_SYNTHESIS_SYSTEM, max_tokens=max_tokens):
        yield token


def build_citations(
    ranked_chunks: List[RankedChunk],
    global_citation_map: "dict[str, int] | None" = None,
) -> List[dict]:
    """Return deduplicated citations; snippet taken from the highest-score chunk per URL."""
    best_by_url: dict[str, RankedChunk] = {}
    for rc in ranked_chunks:
        url = rc.chunk.url
        if url not in best_by_url or rc.score > best_by_url[url].score:
            best_by_url[url] = rc
    seen_urls: list[str] = []
    for rc in ranked_chunks:
        if rc.chunk.url not in seen_urls:
            seen_urls.append(rc.chunk.url)
    citations = []
    for url in seen_urls:
        rc = best_by_url[url]
        num = (global_citation_map.get(url) if global_citation_map else None) or len(citations) + 1
        citations.append({
            "num": num,
            "url": url,
            "title": rc.chunk.title,
            "snippet": rc.chunk.chunk_text[:300],
        })
    return citations
