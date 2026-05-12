"""
Markdown-aware semantic chunker.

Strategy:
  1. Parse heading structure (H1/H2/H3) to find section boundaries
  2. Within each section, split on blank lines (paragraph boundaries)
  3. Merge tiny paragraphs (< MIN_PARA_CHARS) upward into the previous chunk
  4. Split oversized paragraphs with a sliding window + overlap
  5. Prepend heading context to each chunk text for better embedding quality

This produces structurally coherent chunks that the cross-encoder can score
accurately, unlike naive character-window chunking.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import List

from pipeline.extract import ExtractedPage

logger = logging.getLogger(__name__)

MAX_CHARS = 1_500    # target max chunk size
OVERLAP_CHARS = 200  # overlap between windowed sub-chunks (more context)
MIN_PARA_CHARS = 120 # merge paragraphs shorter than this with the next
MIN_CHUNK_BODY = 150 # skip chunk if body (excluding heading prefix) is shorter
MIN_CHUNK_WORDS = 8  # skip chunk if word count below this (catches "Read more"-style fragments)

# ── Garbage chunk detection ────────────────────────────────────────────────────

_SOCIAL_KEYWORDS = frozenset([
    "share on x", "share on twitter", "share on linkedin",
    "share on facebook", "tweet this",
])

# Markdown link pattern — counts `[text](url)` occurrences
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_WORD_RE = re.compile(r"\b\w+\b")

# Short navigation-only patterns: lines that are JUST a nav keyword
_NAV_ONLY_LINE_RE = re.compile(
    r"^\s*(home|menu|search|login|sign\s*(in|up)|register|"
    r"about( us)?|contact( us)?|previous|next|back to top|"
    r"all rights reserved|terms( of (use|service))?|privacy( policy)?)\s*$",
    re.IGNORECASE,
)


def _is_garbage_chunk(text: str) -> bool:
    """
    Return True if the chunk is navigation, social share, image-only,
    a sub-MIN_CHUNK_WORDS fragment, or has too-high link density.
    These patterns come from Jina Reader scraping page chrome instead of body.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return True

    # Word count floor — catches "Read more", "Share", short link lists
    word_count = len(_WORD_RE.findall(text))
    if word_count < MIN_CHUNK_WORDS:
        return True

    # Accessibility nav header
    if any("skip to" in l.lower() for l in lines[:6]):
        return True

    # Social share buttons block
    text_lower = text.lower()
    if sum(1 for kw in _SOCIAL_KEYWORDS if kw in text_lower) >= 2:
        return True

    # High bullet-link density → navigation menu
    bullet_links = sum(1 for l in lines if re.match(r"^\*\s+\[", l))
    if len(lines) >= 4 and bullet_links / len(lines) > 0.45:
        return True

    # Markdown link density across the whole chunk
    # If links account for >40% of words, this is mostly a list of links (navigation)
    link_matches = _MD_LINK_RE.findall(text)
    if link_matches and word_count > 0:
        # Approximate "link words" = sum of words in link anchor text
        link_word_count = sum(len(_WORD_RE.findall(m)) for m in link_matches)
        if link_word_count / word_count > 0.40 and len(link_matches) >= 3:
            return True

    # Mostly markdown image lines
    img_lines = sum(1 for l in lines if re.match(r"^!?\[!\[", l) or re.match(r"^\[!\[", l))
    if len(lines) >= 2 and img_lines / len(lines) > 0.55:
        return True

    # Lines that are JUST navigation keywords (case >50% of body lines)
    nav_only_lines = sum(1 for l in lines if _NAV_ONLY_LINE_RE.match(l))
    if len(lines) >= 3 and nav_only_lines / len(lines) > 0.50:
        return True

    return False


@dataclass
class Chunk:
    url: str
    title: str
    chunk_index: int
    chunk_text: str          # heading context + paragraph text
    heading: str             # nearest ancestor heading (for metadata)
    char_count: int = field(init=False)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.char_count = len(self.chunk_text)

    def to_db_row(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "heading": self.heading,
            "metadata": {**self.metadata, "char_count": self.char_count},
        }


# ── Heading detection ──────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _extract_sections(markdown: str) -> List[tuple[str, str]]:
    """
    Split markdown into (heading, body) pairs.
    The first section may have an empty heading (content before first heading).
    """
    matches = list(_HEADING_RE.finditer(markdown))
    if not matches:
        return [("", markdown)]

    sections = []
    prev_end = 0
    prev_heading = ""

    # Content before the first heading
    if matches[0].start() > 0:
        sections.append(("", markdown[:matches[0].start()]))

    for i, m in enumerate(matches):
        heading_text = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        sections.append((heading_text, body))

    return sections


# ── Paragraph splitting ────────────────────────────────────────────────────────

def _split_paragraphs(text: str) -> List[str]:
    """Split on blank lines, strip, and discard empty strings."""
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _merge_short_paras(paras: List[str]) -> List[str]:
    """Merge consecutive paragraphs that are too short to chunk on their own."""
    merged: List[str] = []
    buf = ""
    for para in paras:
        if buf and len(buf) + len(para) + 2 <= MAX_CHARS:
            buf = buf + "\n\n" + para
        else:
            if buf:
                merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)
    return merged


def _window_split(text: str) -> List[str]:
    """Slide a window over text that exceeds MAX_CHARS."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + MAX_CHARS
        if end >= len(text):
            chunks.append(text[start:])
            break
        # Try to break at a sentence boundary
        break_at = text.rfind(". ", start, end)
        if break_at == -1 or break_at <= start:
            break_at = end
        else:
            break_at += 1  # include the period
        chunks.append(text[start:break_at].strip())
        start = max(start + 1, break_at - OVERLAP_CHARS)
    return [c for c in chunks if c]


# ── Main API ───────────────────────────────────────────────────────────────────

def chunk_page(page: ExtractedPage) -> tuple[List[Chunk], dict]:
    """Chunk a single extracted page. Returns (chunks, stats) where stats counts
    {min_body_dropped, garbage_dropped} for that page."""
    sections = _extract_sections(page.markdown)
    chunks: List[Chunk] = []
    stats = {"min_body_dropped": 0, "garbage_dropped": 0}
    idx = 0

    for heading, body in sections:
        if not body.strip():
            continue

        paras = _split_paragraphs(body)
        paras = _merge_short_paras(paras)

        for para in paras:
            # Skip trivially short body content — navigation/ads residue
            if len(para) < MIN_CHUNK_BODY:
                stats["min_body_dropped"] += 1
                continue

            context_prefix = f"{heading}\n\n" if heading else ""

            if len(context_prefix) + len(para) <= MAX_CHARS:
                chunk_text = (context_prefix + para).strip()
                if _is_garbage_chunk(chunk_text):
                    stats["garbage_dropped"] += 1
                    continue
                chunks.append(Chunk(
                    url=page.url,
                    title=page.title,
                    chunk_index=idx,
                    chunk_text=chunk_text,
                    heading=heading,
                ))
                idx += 1
            else:
                for sub in _window_split(para):
                    if len(sub) < MIN_CHUNK_BODY:
                        stats["min_body_dropped"] += 1
                        continue
                    chunk_text = (context_prefix + sub).strip()
                    if _is_garbage_chunk(chunk_text):
                        stats["garbage_dropped"] += 1
                        continue
                    chunks.append(Chunk(
                        url=page.url,
                        title=page.title,
                        chunk_index=idx,
                        chunk_text=chunk_text,
                        heading=heading,
                    ))
                    idx += 1

    logger.debug("[chunk] %s → %d chunks", page.url, len(chunks))
    return chunks, stats


_DEDUP_FINGERPRINT_CHARS = 200
_WS_RE = re.compile(r"\s+")


def _fingerprint(text: str) -> str:
    """Lower-case, whitespace-collapsed prefix used to detect near-duplicate chunks
    produced by the OVERLAP_CHARS sliding window."""
    return _WS_RE.sub(" ", text.lower()).strip()[:_DEDUP_FINGERPRINT_CHARS]


def _dedupe_chunks(chunks: List[Chunk]) -> List[Chunk]:
    """Drop chunks whose first ~200 normalised chars match a chunk we've already
    kept. Preserves first-seen ordering and original `chunk_index` values."""
    seen: set[str] = set()
    out: List[Chunk] = []
    for c in chunks:
        fp = _fingerprint(c.chunk_text)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(c)
    return out


def chunk_pages(pages: List[ExtractedPage]) -> tuple[List[Chunk], dict, dict]:
    """Chunk all extracted pages, then dedupe near-duplicate windows.

    Returns (chunks, global_stats, per_url_stats):
      - global_stats: {garbage_dropped, min_body_dropped, dedup_dropped, kept}
      - per_url_stats: {url: {garbage_dropped, min_body_dropped, dedup_dropped, kept}}

    Per-URL stats are needed by app.py to partition the global aggregate into
    per-sub-query slices (each sub-query's stats reflect only its own URLs).

    The sliding-window overlap (OVERLAP_CHARS=200) is great for retrieval recall
    but produces visible duplicates in the Top Passages UI. We strip them here
    so downstream BM25 / embedding / rerank work on a clean candidate set.
    """
    all_chunks: List[Chunk] = []
    per_url_stats: dict[str, dict] = {}
    global_stats = {"garbage_dropped": 0, "min_body_dropped": 0, "dedup_dropped": 0, "kept": 0}

    for page in pages:
        page_chunks, page_stats = chunk_page(page)
        per_url_stats[page.url] = {
            "garbage_dropped": page_stats["garbage_dropped"],
            "min_body_dropped": page_stats["min_body_dropped"],
            "dedup_dropped": 0,  # populated during dedup pass below
            "kept": len(page_chunks),
        }
        all_chunks.extend(page_chunks)
        global_stats["garbage_dropped"] += page_stats["garbage_dropped"]
        global_stats["min_body_dropped"] += page_stats["min_body_dropped"]

    before = len(all_chunks)
    # Inline dedup so we can attribute each drop back to its source URL.
    seen: set[str] = set()
    deduped: List[Chunk] = []
    for c in all_chunks:
        fp = _fingerprint(c.chunk_text)
        if fp in seen:
            stats = per_url_stats.setdefault(c.url, {"garbage_dropped": 0, "min_body_dropped": 0, "dedup_dropped": 0, "kept": 0})
            stats["dedup_dropped"] += 1
            stats["kept"] -= 1
            continue
        seen.add(fp)
        deduped.append(c)

    global_stats["dedup_dropped"] = before - len(deduped)
    global_stats["kept"] = len(deduped)
    if global_stats["dedup_dropped"]:
        logger.info("[chunk] Dedup: %d → %d (dropped %d near-duplicates)",
                    before, len(deduped), global_stats["dedup_dropped"])
    logger.info("[chunk] Total chunks: %d across %d pages", len(deduped), len(pages))
    return deduped, global_stats, per_url_stats
