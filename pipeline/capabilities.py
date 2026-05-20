"""
WebLens capability registry.

Single source of truth for what WebLens supports and what it doesn't.
The router (pipeline/analyze.py) injects these lists into its system prompt
so the LLM can decline unsupported artifact requests politely. There is NO
Python-side keyword matching here — these constants are LLM context only.

Adding a new capability later (e.g. PDF export) means moving one entry from
UNSUPPORTED_ARTIFACTS to SUPPORTED_CAPABILITIES — no other code change needed.
"""
from __future__ import annotations

SUPPORTED_CAPABILITIES: list[str] = [
    "Answer questions with cited web sources",
    "Summarize and explain topics in plain text and markdown (headings, lists, tables)",
    "Provide clickable markdown hyperlinks to sources when relevant",
    "Multi-turn conversation with context carried across follow-up questions",
    "Compare entities, list options, give recommendations grounded in sources",
]

UNSUPPORTED_ARTIFACTS: list[str] = [
    "PDF export / generation",
    "Diagram, chart, graph, infographic, or mind-map generation",
    "Image generation",
    "Downloadable files of any kind (docx, pptx, xlsx, csv, zip, etc.)",
    "Video or audio generation",
    "Code execution or running tools on the user's behalf",
]


def supported_block() -> str:
    return "Supported:\n" + "\n".join(f"- {c}" for c in SUPPORTED_CAPABILITIES)


def unsupported_block() -> str:
    return "Not supported yet:\n" + "\n".join(f"- {c}" for c in UNSUPPORTED_ARTIFACTS)
