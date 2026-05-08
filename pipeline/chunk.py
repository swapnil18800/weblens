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

# ── Garbage chunk detection ────────────────────────────────────────────────────

_SOCIAL_KEYWORDS = frozenset([
    "share on x", "share on twitter", "share on linkedin",
    "share on facebook", "tweet this",
])

def _is_garbage_chunk(text: str) -> bool:
    """
    Return True if the chunk is navigation, social share, or image-only content.
    These patterns come from Jina Reader scraping page chrome instead of body.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
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

    # Mostly markdown image lines
    img_lines = sum(1 for l in lines if re.match(r"^!?\[!\[", l) or re.match(r"^\[!\[", l))
    if len(lines) >= 2 and img_lines / len(lines) > 0.55:
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

def chunk_page(page: ExtractedPage) -> List[Chunk]:
    """Chunk a single extracted page into overlapping, heading-aware segments."""
    sections = _extract_sections(page.markdown)
    chunks: List[Chunk] = []
    idx = 0

    for heading, body in sections:
        if not body.strip():
            continue

        paras = _split_paragraphs(body)
        paras = _merge_short_paras(paras)

        for para in paras:
            # Skip trivially short body content — navigation/ads residue
            if len(para) < MIN_CHUNK_BODY:
                continue

            context_prefix = f"{heading}\n\n" if heading else ""

            if len(context_prefix) + len(para) <= MAX_CHARS:
                chunk_text = (context_prefix + para).strip()
                if _is_garbage_chunk(chunk_text):
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
                        continue
                    chunk_text = (context_prefix + sub).strip()
                    if _is_garbage_chunk(chunk_text):
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
    return chunks


def chunk_pages(pages: List[ExtractedPage]) -> List[Chunk]:
    """Chunk all extracted pages. Returns flat list of chunks."""
    all_chunks: List[Chunk] = []
    for page in pages:
        all_chunks.extend(chunk_page(page))
    logger.info("[chunk] Total chunks: %d across %d pages", len(all_chunks), len(pages))
    return all_chunks
