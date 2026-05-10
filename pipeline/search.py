"""
URL discovery via Tavily.

Tavily is used ONLY as a search index — we extract titles and URLs and
nothing else. The actual page content is fetched separately via Jina Reader,
which gives full markdown instead of sparse 200-char snippets.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import List

from config import settings

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT_S = 30
_DEFAULT_MAX_RESULTS = 6


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str  # kept for display only — NOT used as RAG context


async def discover_urls(
    query: str,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> tuple[List[SearchResult], str | None]:
    """
    Run Tavily search and return (urls, error_reason).
    error_reason ∈ {None, "no_api_key", "tavily_timeout", "tavily_http_error"}.
    Content/snippets from Tavily are intentionally ignored for RAG context —
    full pages are extracted separately in extract.py.
    """
    if not settings.tavily_api_key:
        logger.warning("[search] TAVILY_API_KEY not set — returning empty results")
        return [], "no_api_key"

    def _sync_search() -> List[SearchResult]:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(
            query,
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,  # we don't want Tavily's content
        )
        results = []
        for item in resp.get("results", []):
            url = item.get("url", "").strip()
            if not url:
                continue
            results.append(SearchResult(
                url=url,
                title=item.get("title", url),
                snippet=item.get("content", ""),
            ))
        return results

    try:
        results = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _sync_search),
            timeout=_SEARCH_TIMEOUT_S,
        )
        logger.info("[search] Tavily returned %d URLs for: %s", len(results), query[:60])
        return results, None
    except asyncio.TimeoutError:
        logger.warning("[search] Tavily timeout after %ds", _SEARCH_TIMEOUT_S)
        return [], "tavily_timeout"
    except Exception as exc:
        logger.error("[search] Tavily error: %s", exc)
        return [], "tavily_http_error"
