"""
Full-page content extraction.

Strategy (in priority order):
  1. Check page_cache DB table — if valid (not expired), return cached markdown
  2. Fetch via Jina Reader (r.jina.ai) — returns clean markdown, no JS required
  3. Fallback: direct httpx fetch + trafilatura HTML→text extraction

Jina Reader handles JS-heavy pages, paywalls sometimes, and returns structured
markdown with headings preserved — ideal for our markdown-aware chunker.

All URLs extracted concurrently (asyncio.gather) with a shared semaphore to
avoid hammering Jina's free-tier rate limit (3 concurrent max).
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

import httpx

import db.client as db
from pipeline.search import SearchResult

logger = logging.getLogger(__name__)

_JINA_SEMAPHORE = asyncio.Semaphore(6)   # all URLs fetched in parallel
_JINA_TIMEOUT_S = 10                     # fail fast; fallback to trafilatura
_DIRECT_TIMEOUT_S = 8
_MIN_CONTENT_CHARS = 800                 # discard near-empty pages (failed extractions)

# Conservative boilerplate strip — kills cookie/newsletter/nav-only lines that
# slip through both Jina Reader and trafilatura. Pattern matched line-by-line,
# case-insensitive. Don't over-extend this list — _is_garbage_chunk catches the rest.
_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*("
    r"accept (all )?cookies?|"
    r"we (use|value) cookies|"
    r"this (site|website) uses cookies|"
    r"manage (your )?cookie preferences|"
    r"subscribe to (our )?newsletter|"
    r"sign up for (our )?newsletter|"
    r"follow us on (twitter|facebook|linkedin|instagram)|"
    r"share (this|on) (twitter|facebook|linkedin)|"
    r"(all rights reserved|©\s*\d{4})"
    r").*$",
    re.IGNORECASE,
)


def _strip_boilerplate(markdown: str) -> str:
    """Drop lines matching common cookie/newsletter/footer patterns."""
    if not markdown:
        return markdown
    kept = [ln for ln in markdown.split("\n") if not _BOILERPLATE_LINE_RE.match(ln)]
    return "\n".join(kept)


@dataclass
class ExtractedPage:
    url: str
    title: str
    markdown: str
    char_count: int
    from_cache: bool = False

    def summary(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "char_count": self.char_count,
            "from_cache": self.from_cache,
        }


@dataclass
class ExtractionResult:
    """Return value of extract_pages — successful pages plus per-URL failure reasons."""
    pages: List[ExtractedPage]
    failures: List[dict]  # [{url, reason}]  reason ∈ {timeout, http_error, too_short, parse_failed}


# ── DB cache helpers ───────────────────────────────────────────────────────────

async def _load_from_cache(urls: List[str]) -> dict[str, ExtractedPage]:
    """Batch-load non-expired pages from DB cache. Returns {url: ExtractedPage}."""
    if not urls:
        return {}
    try:
        rows = await db.fetch(
            """
            SELECT url, title, markdown
            FROM page_cache
            WHERE url = ANY($1) AND expires_at > NOW()
            """,
            urls,
        )
        result = {}
        for r in rows:
            # Strip Jina headers even from cached markdown (backwards-compat)
            md = _strip_jina_headers(r["markdown"])
            result[r["url"]] = ExtractedPage(
                url=r["url"],
                title=r["title"] or r["url"],
                markdown=md,
                char_count=len(md),
                from_cache=True,
            )
        return result
    except Exception as exc:
        logger.warning("[extract] Cache load failed: %s", exc)
        return {}


async def _save_to_cache(page: ExtractedPage) -> None:
    """Upsert a freshly extracted page into page_cache (fire-and-forget)."""
    try:
        await db.execute(
            """
            INSERT INTO page_cache (url, title, markdown)
            VALUES ($1, $2, $3)
            ON CONFLICT (url) DO UPDATE
              SET title = EXCLUDED.title,
                  markdown = EXCLUDED.markdown,
                  fetched_at = NOW(),
                  expires_at = NOW() + INTERVAL '24 hours'
            """,
            page.url, page.title, page.markdown,
        )
    except Exception as exc:
        logger.debug("[extract] Cache save failed for %s: %s", page.url, exc)


# ── Jina Reader extraction ─────────────────────────────────────────────────────

def _parse_jina_title(markdown: str, fallback: str) -> str:
    """Extract title from Jina's 'Title: ...' header or first H1."""
    m = re.match(r"Title:\s*(.+)", markdown)
    if m:
        return m.group(1).strip()
    m = re.match(r"#\s+(.+)", markdown)
    if m:
        return m.group(1).strip()
    return fallback


def _strip_jina_headers(markdown: str) -> str:
    """
    Remove Jina Reader metadata preamble lines before returning markdown.
    Jina prepends: "Title: ...\nURL Source: ...\nMarkdown Content:\n"
    These lines add noise to chunking and embeddings.
    """
    lines = markdown.split("\n")
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("URL Source:"):
            start = i + 1
            continue
        if stripped == "Markdown Content:":
            start = i + 1
            break
        # Stop scanning after first 5 lines — preamble is always at top
        if i > 5:
            break
    return "\n".join(lines[start:]).strip()


async def _extract_via_jina(
    url: str, client: httpx.AsyncClient
) -> tuple[Optional[ExtractedPage], Optional[str]]:
    """Returns (page, failure_reason). page is None iff failure_reason is set."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"Accept": "text/markdown"}
    if hasattr(__builtins__, '__import__'):
        from config import settings
        if settings.jina_api_key:
            headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    async with _JINA_SEMAPHORE:
        try:
            resp = await client.get(jina_url, headers=headers, timeout=_JINA_TIMEOUT_S)
            resp.raise_for_status()
            markdown = resp.text.strip()
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            logger.debug("[extract] Jina timeout for %s: %s", url, exc)
            return None, "timeout"
        except Exception as exc:
            logger.debug("[extract] Jina failed for %s: %s", url, exc)
            return None, "http_error"

    if len(markdown) < _MIN_CONTENT_CHARS:
        logger.debug("[extract] Jina returned too little content for %s (%d chars)", url, len(markdown))
        return None, "too_short"

    title = _parse_jina_title(markdown, fallback=url)
    markdown = _strip_jina_headers(markdown)
    markdown = _strip_boilerplate(markdown)
    logger.info("[extract] Jina OK: %s (%d chars)", url, len(markdown))
    return ExtractedPage(url=url, title=title, markdown=markdown, char_count=len(markdown)), None


# ── Direct fetch + trafilatura fallback ───────────────────────────────────────

async def _extract_via_trafilatura(
    url: str, client: httpx.AsyncClient
) -> tuple[Optional[ExtractedPage], Optional[str]]:
    """Returns (page, failure_reason). page is None iff failure_reason is set."""
    try:
        resp = await client.get(
            url,
            timeout=_DIRECT_TIMEOUT_S,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WebSearchRAG/1.0)"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        logger.debug("[extract] Direct fetch timeout for %s: %s", url, exc)
        return None, "timeout"
    except Exception as exc:
        logger.debug("[extract] Direct fetch failed for %s: %s", url, exc)
        return None, "http_error"

    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if not text or len(text) < _MIN_CONTENT_CHARS:
            return None, "too_short"
        text = _strip_boilerplate(text)
        logger.info("[extract] trafilatura OK: %s (%d chars)", url, len(text))
        return ExtractedPage(url=url, title=url, markdown=text, char_count=len(text)), None
    except Exception as exc:
        logger.debug("[extract] trafilatura parse failed for %s: %s", url, exc)
        return None, "parse_failed"


# ── Main public API ────────────────────────────────────────────────────────────

async def extract_pages(results: List[SearchResult]) -> ExtractionResult:
    """
    Extract full content for all search result URLs.
    1. Batch-check DB cache
    2. Fetch missing URLs in parallel (Jina → trafilatura fallback)
    3. Cache new pages (fire-and-forget)
    Returns ExtractionResult(pages, failures) — failures is a list of
    {url, reason} dicts so the UI can explain why URLs were dropped.
    """
    urls = [r.url for r in results]
    url_to_title = {r.url: r.title for r in results}

    # 1. Cache lookup
    cached = await _load_from_cache(urls)
    missing_urls = [u for u in urls if u not in cached]

    logger.info(
        "[extract] %d cached, %d to fetch", len(cached), len(missing_urls)
    )

    # 2. Parallel extraction for uncached URLs
    fresh: List[ExtractedPage] = []
    failures: List[dict] = []
    if missing_urls:
        async with httpx.AsyncClient() as client:
            tasks = [_fetch_one(u, url_to_title.get(u, u), client) for u in missing_urls]
            results_raw = await asyncio.gather(*tasks, return_exceptions=True)

        for url, item in zip(missing_urls, results_raw):
            if isinstance(item, Exception):
                logger.debug("[extract] Task exception: %s", item)
                failures.append({"url": url, "reason": "parse_failed"})
                continue
            page, reason = item  # type: ignore[misc]
            if page is not None:
                fresh.append(page)
            else:
                failures.append({"url": url, "reason": reason or "parse_failed"})

    # 3. Cache new pages (non-blocking)
    if fresh:
        asyncio.create_task(_cache_batch(fresh))

    # Merge, preserving original URL order
    all_pages = {**cached, **{p.url: p for p in fresh}}
    ordered = [all_pages[u] for u in urls if u in all_pages]
    logger.info("[extract] %d pages ready, %d failures", len(ordered), len(failures))
    return ExtractionResult(pages=ordered, failures=failures)


async def _fetch_one(
    url: str, title_hint: str, client: httpx.AsyncClient
) -> tuple[Optional[ExtractedPage], Optional[str]]:
    page, reason = await _extract_via_jina(url, client)
    if page is None:
        page, reason = await _extract_via_trafilatura(url, client)
    if page and not page.title:
        page.title = title_hint
    return page, reason


async def _cache_batch(pages: List[ExtractedPage]) -> None:
    for page in pages:
        await _save_to_cache(page)
