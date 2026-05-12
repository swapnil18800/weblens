"""
Quick LangSmith smoke test — generates a trace in the configured project.

Usage:
    python evals/langsmith_smoke.py

Requires in .env:
    LANGCHAIN_API_KEY=<your key>
    LANGCHAIN_TRACING_V2=true          (or LANGSMITH_TRACING=true)
    LANGCHAIN_PROJECT=weblens          (optional, defaults to "weblens-smoke")
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

# LangSmith SDK accepts both LANGSMITH_* and LANGCHAIN_* prefixes
os.environ.setdefault("LANGSMITH_TRACING", os.getenv("LANGSMITH_TRACING", "true"))
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "weblens-smoke"))
os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "weblens-smoke"))

from langsmith import traceable, Client  # noqa: E402


@traceable(name="retrieve", run_type="retriever")
def fake_retrieve(query: str) -> list[dict]:
    time.sleep(0.05)
    return [
        {"content": "Reciprocal Rank Fusion (RRF) combines rankings from multiple retrieval systems.", "score": 0.92},
        {"content": "RRF uses a constant k=60 to smooth rank differences.", "score": 0.87},
    ]


@traceable(name="generate", run_type="llm")
def fake_generate(query: str, chunks: list[dict]) -> str:
    time.sleep(0.05)
    context = " ".join(c["content"] for c in chunks)
    return f"Based on retrieved context: {context[:120]}..."


@traceable(name="rag_pipeline", run_type="chain")
def run_rag(query: str) -> dict:
    chunks = fake_retrieve(query)
    answer = fake_generate(query, chunks)
    return {"query": query, "answer": answer, "num_chunks": len(chunks)}


def main() -> None:
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("ERROR: set LANGCHAIN_API_KEY (or LANGSMITH_API_KEY) in your .env")
        sys.exit(1)

    project = os.environ["LANGCHAIN_PROJECT"]
    print(f"Tracing to LangSmith project: {project}")

    query = "What is Reciprocal Rank Fusion and how does it work?"
    print(f"Running smoke query: {query!r}")

    result = run_rag(query)

    print("\n--- Result ---")
    print(f"Answer : {result['answer']}")
    print(f"Chunks : {result['num_chunks']}")

    # Give the SDK a moment to flush the trace
    time.sleep(1)

    client = Client(api_key=api_key)
    try:
        runs = list(client.list_runs(project_name=project, limit=1))
        if runs:
            run = runs[0]
            print(f"\nTrace URL: https://smith.langchain.com/o/-/projects/p/{run.session_id}/r/{run.id}")
        else:
            print("\nTrace submitted — visit smith.langchain.com to view it.")
    except Exception:
        print("\nTrace submitted — visit smith.langchain.com to view it.")


if __name__ == "__main__":
    main()
