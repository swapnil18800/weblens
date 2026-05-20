# Implementation Summary — v12 (Production-Grade RAG Improvements)

WebLens v12 lands seven targeted, low-regression improvements to conversational
quality, retrieval grounding, async efficiency, citation accuracy, hyperlink
support, generation lifecycle, and multi-turn context handling. All changes are
surgical and preserve the LangGraph topology, the public SSE event protocol,
the existing API shape, the frontend store contract, and LangSmith tracing.

---

## Phase 1 — Smarter routing (prompt-driven)

**Files**: `pipeline/analyze.py`, `pipeline/graph.py`, `pipeline/capabilities.py`

The routing decision (parametric vs search) is now done entirely by the
existing JSON-mode LLM router — no Python heuristics, no regex, no keyword
lists. The system prompt was rewritten to enumerate **categories** the LLM
should match (greetings, identity/capability, textbook-stable explanations,
freshness/news, comparisons, explicit-source requests) and to loosen the
former heavy "default to search" bias in favor of calibrated guidance.

`AnalyzeResult` gained two new fields surfaced for trace visibility:
- `route_reason` — ≤15-word free-text label of the routing decision
- `confidence` — LLM-reported confidence 0.0–1.0

A new SSE event `route_done` is emitted by `node_analyze` carrying
`{mode, route_reason, confidence, rationale}` so the frontend trace panel and
LangSmith spans both show **why** the pipeline took the path it did.

**Examples that now bypass retrieval**: "hi", "hello", "what can you do?",
"who are you?", "explain transformers", "what is a binary search tree?".

---

## Phase 2 — Unsupported-artifact handling

**Files**: `pipeline/analyze.py`, `pipeline/graph.py`, `pipeline/capabilities.py`

A new third routing mode `unsupported` was added. When the LLM detects a
request for an artifact WebLens cannot produce (PDFs, diagrams, downloadable
files, images, video/audio, code execution), it returns
`mode="unsupported"` plus a polite one-sentence decline that offers what
WebLens *can* do instead. The reply is replayed through the existing
`node_parametric_answer` path, so the SSE shape and frontend stay unchanged.

`pipeline/capabilities.py` holds the canonical supported / unsupported
capability lists; they are injected into the router system prompt as text.
Adding PDF support later only requires moving one entry from one list to the
other — no other code change.

---

## Phase 3 — Per-subquery async pipelining (incremental concurrency refactor)

**Files**: `pipeline/graph.py`

Previously, `retrieve` and `generate_answers` were two separate nodes joined by
a stage barrier: ALL N sub-queries had to complete retrieval before ANY
sub-query could start generation. Because generation is the dominant latency
cost (LLM tokens), this was the single biggest async waste.

The new node `node_retrieve_and_generate` **fuses** retrieve+generate per
sub-query: each sub-query starts its LLM stream the instant its own retrieval
finishes. Concurrency is bounded by `asyncio.Semaphore(subquery_concurrency)`
(defaults to N when ≤8). The shared global citation map is built
**incrementally** under an `asyncio.Lock`, so [N] numbering stays consistent
across sub-answers regardless of completion order.

Stage barriers preserved (each already parallelizes well internally across
URLs / sub-queries):
- `search_urls` — Tavily searches in parallel
- `extract_pages` — Jina fetches in parallel across URLs
- `chunk_pages` — in-process, ms latency

Stage barrier removed:
- **`retrieve → generate`**

A new `synthesis_waiting` SSE event is emitted before synthesis begins so the
UI can show "Waiting for all sub-query answers to complete…".

The legacy `node_retrieve` is kept as a deprecated shim so the eval harness
and any external imports continue to work, but it is no longer wired into the
graph.

**Trade-off (honest)**: the plan called for *fully* independent
`search → extract → retrieve → generate` per sub-query (i.e. removing the
search/extract stage barriers as well). That refactor is significantly larger
and would change the SSE event ordering more invasively. We chose the
incremental retrieve→generate fusion because it captures the dominant latency
win (generation begins per-subquery instead of waiting for the slowest retrieval) with a minimal-disruption surface.
Removing the search/extract barriers as well is straightforward follow-on work.

---

## Phase 4 — Chunk utilization (prompt + metrics)

**Files**: `pipeline/generate.py`, `pipeline/graph.py`

User-reported behavior: many chunks retrieved but few cited — the model was
under-using the available evidence. Two-pronged fix:

1. **Prompt tightening** in `pipeline/generate.py`:
   - Sub-answer system prompt now explicitly tells the model to "use as many
     sources as are genuinely relevant; corroborate with multiple [N] per
     sentence when sources agree; prefer a thorough answer that covers what
     the available sources collectively say over a terse one that ignores
     most of them."
   - Synthesis system prompt now explicitly forbids dropping `[N]` markers
     during merging — "fewer citations in the final answer than in the inputs
     is almost always a bug."

2. **Measurement** emitted on every `sub_answer_done`:
   - `chunks_available` — # retrieved chunks for this sub-query
   - `citations_used` — # distinct `[N]` referenced in the final sub-answer
   - `utilization_ratio = citations_used / chunks_available`
   - `hyperlinks_stripped` — Phase 6 safety-net count

Aggregates `utilization_ratio_overall` and `utilization_ratio_median` flow
through `latency_breakdown` into the final `done` event for monitoring and
LangSmith. Target post-change: median ≥ 0.6.

---

## Phase 5 — Detached generation lifecycle

**Files**: `pipeline/generation_registry.py` (new), `app.py`

Previously, switching sessions during generation cancelled the SSE stream,
which cancelled the server-side graph task, which aborted `node_emit_done` —
losing cache_insert and `sessions.save_message`. Now the producer task is
detached from the SSE consumer:

- **`GenerationRegistry`** — an in-process dict of `RunHandle`s keyed by
  `request_id`. Each handle has a producer task, a bounded replay buffer
  (4096 events; oldest non-token events dropped first under pressure), and a
  list of subscriber queues.
- `POST /api/search` registers a handle, runs the pipeline as a registered
  background task, and emits its first event `request_started`
  `{request_id, session_id}`. The SSE response is a thin **consumer** of the
  handle's broadcast.
- **Client disconnect no longer cancels the producer.** It keeps running to
  completion so the answer is persisted via `node_emit_done` (cache_insert,
  save_message, followups, memory_state update).
- **New endpoint** `GET /api/search/{request_id}/resume` — re-attaches a fresh
  subscriber, replays the buffered events, then tails live events until done.
  Frontend opt-in: legacy frontends simply ignore `request_started` and
  continue to work; updated frontends stash `request_id` and call `/resume` on
  session-switch return.
- **Cleanup**: handles are reaped 5 minutes after `done`, or 30 minutes after
  creation (hard cap). A background sweeper runs every 30 seconds.

**Scope**: in-process only — fine for the single-instance Railway deploy.
Horizontal scale (multiple workers) would require swapping the registry for a
Redis-backed implementation behind the same public surface.

---

## Phase 6 — Hyperlinks in answers

**Files**: `pipeline/generate.py`, `pipeline/graph.py`

Sub-answer and synthesis system prompts now explicitly instruct the model:
"When you mention a specific named resource (course, paper, tool, product,
repo, video) and the source material attributes it to a URL, link the name
with markdown `[name](url)`. Use ONLY URLs that appear in the provided
sources. Do not wrap [N] citation markers in links."

Safety net: `strip_unknown_links(answer, allowed_urls)` is applied
post-stream to every sub-answer AND the synthesized final answer. Any
`[text](url)` whose URL is not in the citation pool is stripped (text kept,
link removed), with a count emitted as `hyperlinks_stripped` per sub-answer.
URL normalization (lowercased scheme/host, trailing-slash strip) handles
trivial mismatches. `[N]` citation markers are never affected.

---

## Phase 7 — Conversation history & retrieval drift

**Files**: `pipeline/analyze.py`, `pipeline/summarize.py` (new), `pipeline/generate.py`,
`pipeline/graph.py`, `db/sessions.py`, `db/schema.sql`, `db/migrate_sessions.py`,
`app.py`

A single LLM call (the existing rewriter) now returns a richer JSON payload
including `is_topic_switch`, `active_topic`, `active_constraints`,
`clarification`, and `confidence`. No Python heuristics for topic-switch
detection — the LLM owns the decision.

**Topic anchor persistence**: a new `memory_state JSONB` column on
`rag_sessions` (idempotent migration) holds:
```
{
  "history_summary":    str,       # rolling ≤120-word summary of older turns
  "summarized_up_to":   int,       # # of messages already folded
  "active_topic":       str,
  "active_constraints": [str]
}
```

Helpers added to `db/sessions.py`:
- `get_memory_state(session_id)` / `update_memory_state(...)`
- `recent_context(session_id)` — returns composite
  `{history_summary, recent_turns, active_topic, active_constraints}`

**Retrieval-context isolation on topic switch**: when the rewriter returns
`is_topic_switch=True`, `node_rewrite_query` blanks `history` and
`history_summary` before they flow to decompose / generation / synthesis.
The new topic state still propagates so it is persisted.

**Rolling summary (incremental)** — industry-standard
`ConversationSummaryBufferMemory` pattern. New module `pipeline/summarize.py`
does a single small LLM call (DeepSeek `deepseek-chat`, ≤200 tokens) that
folds **only the evicted turn** into the existing summary. Per-update cost is
O(1) in turns, regardless of conversation length. Runs as a fire-and-forget
task at the very end of `node_emit_done` — **zero impact on user-visible
latency**. If the call fails, the prior summary is left as-is and the next
turn folds a 2-turn delta.

**Clarification**: when `confidence < 0.5` and the rewriter supplies a
one-line clarification question, a `clarification_needed` event is emitted
(carried in the `rewrite_done` payload). UI integration is opt-in;
back-compat preserved.

---

## SSE event protocol — what changed

Existing events are byte-compatible. New events emitted:

| Event | Phase | Payload |
|-------|-------|---------|
| `route_done` | 1, 2 | `{mode, route_reason, confidence, rationale, latency_ms}` |
| `synthesis_waiting` | 3 | `{sub_queries_count}` |
| `request_started` | 5 | `{request_id, session_id}` (first event of `/api/search`) |
| `request_resumed` | 5 | `{request_id, session_id, done}` (first event of `/resume`) |

`sub_answer_done` payload now also carries `chunks_available`,
`citations_used`, `utilization_ratio`, `hyperlinks_stripped` (Phase 4).
`rewrite_done` payload now also carries `is_topic_switch`, `active_topic`,
`active_constraints`, `confidence`, `clarification` (Phase 7).
`decompose_done` payload now also carries `route_reason`, `confidence`.

Legacy frontends ignore unknown fields and continue to work unchanged.

---

## Backwards compatibility

- The legacy `rewrite_query(query, history) -> (str, bool)` is preserved as a
  thin wrapper over `rewrite_query_full()`.
- `node_retrieve` is preserved as a deprecated shim (eval harness still
  imports it).
- All public SSE event names are preserved with byte-compatible payloads
  (additive fields only).
- `sessions.recent_turns()` is unchanged; `sessions.recent_context()` is a
  new sibling that returns the composite shape.
- `analyze_query()` unified entry point is preserved.

---

## Latency implications

- **Phase 3** is a net win: per-subquery generation overlaps with other
  sub-queries' retrievals. Expected p50 generation-phase improvement: 15–30%
  on multi-subquery (3+) workloads.
- **Phase 1/2**: parametric routes skip the entire search pipeline →
  multi-second wins on greetings/meta/textbook queries.
- **Phase 7**: rolling-summary call is fire-and-forget AFTER stream end — 0ms
  user impact. Rewriter prompt is longer; expected +50–150ms in `rewrite_ms`.
- **Phase 4/6**: prompt-only changes; no measurable latency impact. Cleaned
  text + utilization metrics are O(n) post-processing per sub-answer (≪1ms).
- **Phase 5**: zero latency cost on the happy path. Background sweeper is
  every 30s and trivial work.

---

## Future work / honest deferrals

- **Phase 3 fuller version**: also remove the search and extract stage
  barriers. Requires per-subquery URL deduplication via a shared
  `dict[url, asyncio.Task[ExtractedPage]]` and slightly invasive event-name
  changes for per-subquery progress.
- **Phase 5 frontend**: leverage `request_id` to re-attach via `/resume` on
  session-switch return. Backend is ready; frontend wiring is small but not
  yet done in this PR.
- **Phase 7 clarification UX**: `clarification_needed` event is emitted but
  the UI does not yet render it as an inline question prompt.
- **Multi-worker support**: replace `GenerationRegistry` with a Redis-backed
  implementation when scaling horizontally.

---

## Migration

```
python db/migrate_sessions.py
```
Adds the `memory_state JSONB` column to `rag_sessions` idempotently.

## Verification

- `python evals/cache_smoke.py`
- `python evals/langsmith_smoke.py`
- `python evals/smoke_conversation_history.py`
- `python evals/run_eval.py`
- Manual UX: "hi", "give me a PDF of the answer", session-switch during
  generation, "top dsa questions" → "give me top 30", "best Udemy courses on
  Agentic AI" (verify clickable markdown links).
