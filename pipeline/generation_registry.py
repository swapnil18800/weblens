"""
Phase 5 — Detached generation lifecycle.

A lightweight in-process registry of in-flight generation tasks. The pipeline
runs as a background task whose output is buffered in a per-request queue +
replay buffer. The SSE generator becomes a *consumer* of that queue; if the
client disconnects (session switch, tab close, network blip), the producer
task continues until completion. This way `node_emit_done` (persistence,
cache_insert, followups, memory_state update) always runs end-to-end and the
final answer is durably saved — instead of the prior behavior where client
disconnect cancelled the graph mid-flight.

Why in-process (not Redis):
  - WebLens is currently single-instance (Railway). One process owns all live
    generations, so an in-memory dict suffices and adds no infra.
  - When/if we scale horizontally, swap this module for a Redis-backed version
    behind the same public surface.

Lifecycle:
  - `register()` creates a RunHandle, starts the producer task. The handle
    immediately attaches one consumer (the original SSE response).
  - Each event is broadcast to ALL active subscribers AND appended to the
    replay buffer (bounded; oldest non-token events are dropped first).
  - `resume(request_id)` attaches a new subscriber, replays the buffer, then
    tails live events. Used by `GET /api/search/{request_id}/resume`.
  - Once the producer ends (sentinel), the handle is kept alive for a TTL so
    late resumers can still get the full replay; then it is reaped.

Bounded by:
  - per-handle replay buffer: REPLAY_MAX events (drop oldest non-token first)
  - registry: time-based eviction via a periodic sweep
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

# Tunables — keep modest; this is in-process state.
REPLAY_MAX = 4096                 # max events held for resume
DONE_TTL_SECONDS = 300            # keep a completed handle resumable for 5 min
HARD_TTL_SECONDS = 1800           # absolute upper bound on a handle's life
SWEEP_INTERVAL_SECONDS = 30       # cleanup sweep cadence

_DONE_SENTINEL = ("__rg_done__", None)


@dataclass
class RunHandle:
    """One generation run. Owns the producer task and broadcasts events to
    all attached consumers."""
    request_id: str
    task: Optional[asyncio.Task] = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    replay_buffer: deque = field(default_factory=lambda: deque(maxlen=REPLAY_MAX))
    done: bool = False
    created_at: float = field(default_factory=time.time)
    done_at: Optional[float] = None
    # Saved metadata for the resume endpoint.
    session_id: str = ""
    query: str = ""
    dropped_events: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def broadcast(self, event_name: str, data: dict) -> None:
        """Append to replay buffer and push to all attached subscribers."""
        if event_name == _DONE_SENTINEL[0]:
            # Internal sentinel: mark done, broadcast to subscribers as a
            # special tuple. Replay buffer does not store it.
            self.done = True
            self.done_at = time.time()
            for q in list(self.subscribers):
                try:
                    q.put_nowait(_DONE_SENTINEL)
                except asyncio.QueueFull:  # pragma: no cover — unbounded queues
                    pass
            return
        # Append to replay buffer (bounded by maxlen via deque). If we'd exceed
        # the cap we'd lose the oldest event; for backpressure-sensitivity, we
        # prefer to drop intermediate `sub_answer_token` events first since
        # final completed answer is also broadcast as `sub_answer_done`.
        if len(self.replay_buffer) >= REPLAY_MAX:
            # Walk from oldest and drop the first token event we find; else
            # drop the oldest event of any kind.
            for i, (en, _d) in enumerate(self.replay_buffer):
                if en == "sub_answer_token":
                    del self.replay_buffer[i]
                    self.dropped_events += 1
                    break
            else:
                self.replay_buffer.popleft()
                self.dropped_events += 1
        self.replay_buffer.append((event_name, data))
        # Fanout to subscribers (best-effort; their consumer drains them).
        for q in list(self.subscribers):
            try:
                q.put_nowait((event_name, data))
            except asyncio.QueueFull:  # pragma: no cover
                pass

    def attach(self) -> asyncio.Queue:
        """Add a new subscriber queue and return it. Caller is responsible for
        calling `detach(q)` when finished (e.g. in a `finally`)."""
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def detach(self, q: asyncio.Queue) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass


class GenerationRegistry:
    """In-process registry of RunHandles, keyed by request_id."""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._sweeper_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def _new_request_id(self) -> str:
        return uuid.uuid4().hex

    async def register(self, *, session_id: str = "", query: str = "") -> RunHandle:
        async with self._lock:
            rid = self._new_request_id()
            handle = RunHandle(request_id=rid, session_id=session_id, query=query)
            self._runs[rid] = handle
            self._ensure_sweeper()
            return handle

    def get(self, request_id: str) -> Optional[RunHandle]:
        return self._runs.get(request_id)

    async def mark_done(self, handle: RunHandle) -> None:
        await handle.broadcast(_DONE_SENTINEL[0], {})

    def _ensure_sweeper(self) -> None:
        if self._sweeper_task is None or self._sweeper_task.done():
            try:
                self._sweeper_task = asyncio.create_task(self._sweep_loop())
            except RuntimeError:  # no running loop yet — sweeper starts on first register
                self._sweeper_task = None

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
                now = time.time()
                stale: list[str] = []
                for rid, h in list(self._runs.items()):
                    age = now - h.created_at
                    if h.done and h.done_at is not None and (now - h.done_at) > DONE_TTL_SECONDS:
                        stale.append(rid)
                    elif age > HARD_TTL_SECONDS:
                        stale.append(rid)
                for rid in stale:
                    h = self._runs.pop(rid, None)
                    if h is not None:
                        logger.info(
                            "[reg] reaped run %s (done=%s, age=%.0fs, dropped=%d)",
                            rid[:8], h.done, time.time() - h.created_at, h.dropped_events,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover — sweeper must never die
                logger.debug("[reg] sweeper loop error: %s", exc)


# ── Singleton ───────────────────────────────────────────────────────────────

_REGISTRY: Optional[GenerationRegistry] = None


def get_registry() -> GenerationRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = GenerationRegistry()
    return _REGISTRY


# ── Consumer helper ─────────────────────────────────────────────────────────

async def consume(handle: RunHandle, *, replay: bool = True) -> AsyncIterator[tuple[str, dict]]:
    """Async iterator over a handle's events. Replays the buffered events
    first (if `replay=True`), then tails live events from a fresh subscriber
    queue until the run is done.
    """
    q = handle.attach()
    try:
        if replay:
            # Snapshot the buffer up to the current point.
            snapshot = list(handle.replay_buffer)
            for ev in snapshot:
                yield ev
            # If the run has already completed AND we've already replayed
            # everything, return — no live tail needed.
            if handle.done:
                return
        while True:
            item = await q.get()
            if item == _DONE_SENTINEL:
                return
            yield item
    finally:
        handle.detach(q)
