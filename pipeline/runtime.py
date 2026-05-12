"""
Per-request runtime context for the LangGraph pipeline.

Kept OUT of GraphState deliberately — alphalens' anti-pattern was stuffing
asyncio callbacks and timing data into the TypedDict state, which made state
non-serializable and bloated to 54 fields. We move all of that here.

Nodes access this via `RunnableConfig`:
    config = config_from_runnable(config)
    runtime = config["configurable"]["runtime"]
    runtime.emit("event_name", {...})

The HTTP layer in app.py drains `runtime.event_queue` and writes SSE.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from pipeline.token_tracker import TokenTracker, get_tracker


_SENTINEL = ("__done__", None)


@dataclass
class RuntimeContext:
    """Shared per-request runtime state. Not part of GraphState.

    `event_queue` is drained by the HTTP handler; nodes push (event, data).
    """
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    token_tracker: TokenTracker = field(default_factory=get_tracker)
    t_start: float = field(default_factory=time.perf_counter)
    latency_breakdown: dict = field(default_factory=dict)
    langsmith_run_id: Optional[str] = None
    session_id: Optional[str] = None
    cancel: bool = False
    # Shared pipeline workspace — used by the split search-pipeline nodes
    # (search_urls → extract_pages → chunk_pages → retrieve → generate) to
    # pass intermediate working state (search_results, pages, chunks, ranked
    # lists, citation maps) without bloating GraphState. Cleared by
    # node_embedding_cleanup after generation.
    workspace: dict = field(default_factory=dict)

    async def emit(self, event: str, data: dict) -> None:
        await self.event_queue.put((event, data))

    def emit_nowait(self, event: str, data: dict) -> None:
        self.event_queue.put_nowait((event, data))

    async def signal_done(self) -> None:
        await self.event_queue.put(_SENTINEL)

    def record_stage(self, stage: str, ms: int) -> None:
        self.latency_breakdown[stage] = ms

    @staticmethod
    def is_done_sentinel(item: tuple) -> bool:
        return item == _SENTINEL


def sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── ContextVar for per-request runtime ──────────────────────────────────────
# Using a contextvar instead of threading config through every node — LangGraph
# preserves contextvars across node invocations within the same ainvoke task,
# so each request gets its own RuntimeContext naturally.

_RUNTIME_CTX: contextvars.ContextVar[Optional[RuntimeContext]] = contextvars.ContextVar(
    "weblens_runtime", default=None
)


def set_runtime(rt: RuntimeContext) -> contextvars.Token:
    return _RUNTIME_CTX.set(rt)


def reset_runtime(token: contextvars.Token) -> None:
    _RUNTIME_CTX.reset(token)


def get_runtime() -> RuntimeContext:
    rt = _RUNTIME_CTX.get()
    if rt is None:
        raise RuntimeError("RuntimeContext not set — call set_runtime() before invoking the graph")
    return rt
