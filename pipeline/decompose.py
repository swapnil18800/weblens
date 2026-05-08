"""
Query decomposition: splits complex queries into independent sub-questions.

Rationale:
  Multi-entity × multi-dimension questions benefit from separate URL discovery
  per entity/dimension, ensuring balanced web coverage and better retrieval.
  Single-concept questions pass through unchanged (zero LLM overhead).

Returns [query] for simple questions, up to 12 sub-queries for complex ones.
Decomposition strategy: N entities × D dimensions = N×D sub-queries.
  - Time ranges stay within each sub-query (don't fan-out on years).
  - e.g. "Apple vs MSFT revenue+challenges FY2023-FY2026" → 6 sub-queries.
"""
import json
import logging
from typing import List

from llm.openai_client import get_llm

logger = logging.getLogger(__name__)

_SYSTEM = """\
Decompose the user question into independent sub-questions for parallel web search.

Rules:
- Simple, single-concept question → return as JSON list with 1 item
- Multi-entity comparisons (N companies/entities):
    For each entity × each dimension (revenue, challenges, margins, etc.) → one sub-question
    Keep time ranges in each sub-question (don't fan-out on individual years)
    Example: "Apple vs Microsoft vs NVIDIA revenue and unique challenges FY2023-FY2026"
    → ["Apple revenue growth trend FY2023 to FY2026 annual",
       "Apple unique business challenges FY2023 to FY2026",
       "Microsoft revenue growth trend FY2023 to FY2026 annual",
       "Microsoft unique business challenges FY2023 to FY2026",
       "NVIDIA revenue growth trend FY2023 to FY2026 annual",
       "NVIDIA unique business challenges FY2023 to FY2026"]
- Multi-part labeled questions (a, b, c) → one sub-question per part
- Multi-year trend for one entity × one metric → keep as single query (don't split by year)
- Each sub-question must be self-contained (include entity name and time range explicitly)
- For technical questions include specific algorithm/parameter terms
- Generate AS MANY sub-questions as needed for full independent coverage — no more, no fewer.
  Prefer fewer when dimensions overlap; prefer more when each requires distinct sources.
- Return ONLY a valid JSON array of strings, nothing else

Examples:
Input: "What is BM25?"
Output: ["What is BM25?"]

Input: "Compare dense and sparse retrieval"
Output: ["How does dense retrieval work for information retrieval?", "How does sparse retrieval (BM25/TF-IDF) work for information retrieval?"]

Input: "Compare IVFFlat and HNSW: accuracy, speed, memory?"
Output: ["How does IVFFlat index work: k-means clustering, nprobe, training phase, memory usage?", "How does HNSW hierarchical graph index work: accuracy, speed, memory usage?"]

Input: "Apple vs Google FY2024 revenue and margins"
Output: ["Apple FY2024 total revenue and segment breakdown", "Apple FY2024 operating and net margins", "Google (Alphabet) FY2024 total revenue and segment breakdown", "Google (Alphabet) FY2024 operating and net margins"]
"""


async def decompose_query(query: str) -> List[str]:
    """
    Decompose a query into sub-queries for parallel search.
    Returns [query] for simple questions with minimal overhead.
    Fast path: if query < 60 chars, skip LLM call entirely.
    """
    if len(query) < 60:
        return [query]

    llm = get_llm()
    try:
        raw = await llm.acomplete(
            f"Decompose: {query}",
            system=_SYSTEM,
            max_tokens=500,
        )
        sub_queries = json.loads(raw.strip())
        if isinstance(sub_queries, list) and all(isinstance(q, str) for q in sub_queries):
            # Soft safety cap at 24 — only triggers on pathological compound questions
            result = [q.strip() for q in sub_queries if q.strip()][:24]
            if result:
                if len(result) > 1:
                    logger.info("[decompose] %d sub-queries for: %s", len(result), query[:80])
                return result
    except Exception as exc:
        logger.debug("[decompose] LLM failed (%s), using original", exc)
    return [query]
