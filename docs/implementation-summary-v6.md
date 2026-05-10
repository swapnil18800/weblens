# Improvement Summary — May 2026

A pass over chat UX, pipeline trace honesty, decomposition reliability,
generation correctness, layout, and persistence parity.

---

## 1. Trace UX

### Rerank step text

**Before**: `candidates 24 → CE 16 → top 8 (7 per-URL cap)` — exposed the
BM25 funnel as if it were the whole story while the dense + RRF + cross-encoder
stages were silent. The "candidates" label was the BM25-pool size only.

**After**: `Selected top 8 passages` — honest about what the user sees.
The internal funnel is documented in code, not surfaced as misleading UI.

### Picked best evidence — expandable body

**Before**: clicking the rerank step expanded to the broken
`candidates: · top: score: –` placeholder (undefined values rendered).
A separate "Top passages used (8)" dropdown lived in `SubqueryTrace.tsx`.

**After**: the rerank step's expandable body is the top-N passages list itself
(chunk #, source title, score, snippet). The standalone dropdown is removed.
`sub_answer_start` backfills the chunks into the existing rerank step's payload.

### Source list — titles + status chips

**Before**: the "Read pages" expansion showed bare domains
(`hpcwire.com · 145.5k chars`) including domains that weren't in the per-sub-query
sources block. Failed pages were tucked behind a `details` summary.

**After**: each sub-query's "Read pages" shows the **Tavily source title**
(e.g. "Chart: Data Centers Almost Sole Driver of Nvidia's Revenue Boom |
Statista") with a single status chip on the right:

| status | meaning | colour |
|---|---|---|
| `extracted · 145.5k` | new fetch succeeded | green |
| `cached · 19.8k` | served from cache | blue |
| `http error` | network/HTTP failure | red |
| `too short` | body below min length | amber |
| `parse error` | extractor failed | red |

Sorted by char count desc; failed pages at the bottom. URLs are constrained to
the per-sub-query sources subset — no extra domains appear.

### Removed: per-URL chunks dropdown

The "Split into passages" expandable used to list every URL with its chunk
count (per the user, "useless"). Removed — the descriptive
`Built N passages (dropped M: ... boilerplate, ... short, ... duplicate)`
detail line carries all the useful info.

### Followup suggestions

**Before**: 3-column grid of chips with arrow icons.

**After**: vertical list, one per row. Each row has an indented
`↪` (`CornerDownRight`) icon and a dotted bottom border. Full-row highlight on
hover. Click loads the question into the input.

---

## 2. Per-sub-query stats

### The bug

Extraction and chunking run **once globally** on the deduplicated union of
URLs across all sub-queries (an architectural choice — extraction is the
expensive step). The previous trace echoed the SAME global counts into every
sub-query's "Read pages" / "Split into passages" rows. Three sub-queries with
totally different sources all showed `Built 306 passages (dropped 218: ...)`.
The user correctly called this dishonest.

### The fix

Extraction still runs once. Per-sub-query stats are now computed as
**post-hoc partitions** of the global outcome:

1. `app.py` preserves a `url_to_subqueries: dict[url, set[int]]` map at search
   time (multi-origin URLs keep all their sub-query indices).
2. After global `extract_pages`, for each sub-query `i`:
   - `pages_i` = pages whose URL belongs to sub-query `i`'s search results
   - `failures_i` = same for failures
   - extract event is enriched with a `per_subquery: PerSubqueryExtract[]`
     array carrying `{index, pages: [{url, title, status, char_count}],
     succeeded, attempted, failures}` per sub-query.
3. `chunk_pages` was extended to return `per_url_stats` so the global aggregate
   can be partitioned per-sub-query identically (each sub-query gets the
   `(garbage_dropped, min_body_dropped, dedup_dropped, kept)` breakdown
   computed from its own URLs). The dedup pass is inlined so each drop is
   attributed back to its source URL.
4. `chunk_done` and `embed_done` events also carry `per_subquery` slices.

The frontend SSE handlers prefer the per-sub-query slice when present and
fall back to the global counts for older event shapes.

### Pages-vs-URLs anomaly

User asked why "Found 6 sources" but "Read 20 of 24 pages". A startup log was
added in `app.py`:

```
[search] sub_queries=4 max_results=6 total_pre_dedup=24 after_dedup=18
```

This usually shows that decompose produced 4 sub-queries (not the 3 the user
counted in their screenshot), so 4 × 6 = 24 explains the gap. Each sub-query
now shows ITS OWN page count after Section 2, so the comparison is naturally
consistent.

---

## 3. Decomposition reliability

### Date anchor (recency)

**Before**: prompts had no current-date instruction; the LLM defaulted to its
training data, asking about "FY2024 Q4 earnings call" in May 2026.

**After**: both `_DECOMPOSE_SYSTEM` and `_REWRITE_SYSTEM` are format strings
with a `{today}` placeholder injected at call time. A new
**Temporal Reasoning** section in the decompose prompt teaches the model:

- Treat "recent / latest / currently" (or no time scope on a topic that
  obviously evolves) as "the last 12 months ending today".
- Never default to a specific past fiscal year just because it was the most
  recent in training data.
- For periodic events, the most recent occurrence is the one closest to but
  not after `today`.
- Honor explicit user-named years/quarters exactly.
- Escape hatch: when ambiguous, omit the year and let retrieval surface what
  exists.

### Topic-shift defense (anaphora rule)

**Before**: `_REWRITE_SYSTEM` always blended history into rewrites. After a
NVIDIA question, "sadhguru vs osho?" became
"What did NVIDIA's CEO say about Sadhguru?".

**After**: the rewriter is given a generalised rule:

> Apply prior context only if the latest message is dependent on it
> (anaphora, fragment, or transformation request).
>
> If the latest message names its own concrete subject and forms a complete
> question, REWRITE IT UNCHANGED — never blend topics.
>
> Prior context is a tool to *resolve under-specification*, not a frame to
> *force every new query into*.

Reinforced with positive examples (continuation), negative examples (topic
shift kept unchanged), and counter-examples (mistakes the LLM might be tempted
to make: inventing a connection, blending topics, fabricating a relationship).

---

## 4. Generation correctness — top-k → cited mismatch

### The bug

`_build_prompt` enforced a **6,000-char-per-URL hard cap** on the source
blocks fed into the LLM. If chunk #1 from URL X used 5,500 chars, chunks #2
and #3 from URL X were silently skipped — they reached `retrieve()` but never
the LLM. So the answer's `[N]` citations could only span a subset of the
top-K reranked chunks.

### The fix

`_build_prompt` now uses **round-robin packing** under a single shared budget:

- Group ranked chunks by URL.
- Round-robin: take one chunk from each URL's queue per pass.
- Append until total prompt size hits a generous budget (`_PROMPT_CHAR_BUDGET
  = 48,000` chars ≈ 12k tokens — well under model input limits).
- Logs a stderr warning if any chunk had to be dropped (rare with this budget).

Round-robin still prevents single-URL dominance (the original guardrail's
intent) without silently losing chunks.

---

## 5. Persistence parity

### The gap

Backend always persisted full traces in JSONB. But the frontend's
`rehydrateSteps` produced a **stripped-down** version (no failure breakdowns,
no chips, no source titles). So a session that looked rich while streaming
became sparse on reload or chat-switch — and vice versa for live vs persisted.

### The fix

Two pieces:

1. **Persisted shape extended.** Each entry in `traces` now carries
   `extract_stats`, `chunk_stats`, and `embed_count` — the same per-sub-query
   slices computed for live SSE. JSONB column, no schema change.
2. **`rehydrateSteps` upgraded.** Reads the new fields when present and
   builds steps with identical payloads to the live handlers — chips,
   failure breakdowns, descriptive drop counts, the works. Falls back to
   `latency_breakdown` counts for older traces.

Result: live trace and rehydrated trace are now visually identical.

---

## 6. Layout fixes

### Question lands mid-window after submit

The submitted question's chat bubble used to land in the middle of the chat
window instead of jumping to the top of the viewport (where there's room for
the streaming answer below it).

**Root cause**: `ChatThread.tsx`'s scroll snap (`scrollTop = node.offsetTop -
8`) was already correct, but `scrollTop` is **clamped** to
`scrollHeight - clientHeight`. With short content, max scrollTop < required
scrollTop, so the assignment silently clamped and the question stayed
wherever flex-flow placed it.

**Fix**: tail spacer at the end of the scroll container:

```tsx
<div aria-hidden style={{ height: 'calc(100vh - 200px)' }} />
```

Always guarantees enough scrollable headroom below the last turn for it to
reach the viewport top. The existing 320 ms / 800 ms re-snaps continue to
keep the question pinned as the answer streams in.

The "scroll to bottom" floating button was retargeted from
`scrollHeight` (now meaningless — lands inside the spacer) to the **last
turn's `offsetTop`**, with visibility tied to whether the last turn's bottom
edge is in view.

### Session-click scroll

Used to land at the very bottom of the page (`scrollTop = scrollHeight`),
which after the spacer change meant scrolling past the last turn into empty
space. Now uses double-rAF + `node.offsetTop - 8` of the last turn — the same
strategy as the new-question snap. Last turn lands at the TOP of the viewport.

### Question header hover icons

Bumped from `w-3.5 h-3.5 text-neutral-500` (small + faded) to
`w-4 h-4 text-neutral-300 hover:text-white` with `strokeWidth={2.25}` (bigger,
solid). Added a Copy button alongside Edit and Retry. Version pager bumped to
`text-sm font-medium text-neutral-300` with `w-4 h-4` chevrons.

### Retry on the answer toolbar

The Retry icon was previously only a hover icon on the question. Now it's a
first-class button on the answer toolbar (between thumbs-down and Retrieved).

---

## 7. Files changed

| Area | File | Change |
|---|---|---|
| Trace text | `frontend/src/state/chatStore.ts` | Rerank → simple text; backfill chunks into rerank payload from sub_answer_start; per-sub-query slices for extract / chunk / embed; rehydrateSteps reads new persisted fields |
| Trace UI | `frontend/src/components/PipelineStep.tsx` | Removed chunk dropdown; removed rerank gibberish fallback; added rerank → top-N passages expansion; added enriched extract rendering with status chips; added `ExtractStatusChip` |
| Trace UI | `frontend/src/components/SubqueryTrace.tsx` | Dropped `ChunksPanel` (folded into rerank step); pass `onChunkClick` to `PipelineStep` |
| Question UI | `frontend/src/components/ChatTurn.tsx` | Question header hover icons bigger + solid + Copy added; version pager bigger; Retry on answer toolbar; followups vertical list with `CornerDownRight` + dotted divider + hover highlight |
| Layout | `frontend/src/components/ChatThread.tsx` | Tail spacer; double-rAF session-load scroll → last turn TOP; scroll-to-latest button retargeted to last-turn `offsetTop` |
| Types | `frontend/src/lib/types.ts` | New `ExtractStatus`, `ExtractPageEntry`, `PerSubqueryExtract`, `PerSubqueryChunk`, `PerSubqueryEmbed`; SSE shapes extended; PersistedMessage trace extended |
| Decompose | `pipeline/decompose.py` | `_today()` helper; date injection into both prompts; Temporal Reasoning section added to `_DECOMPOSE_SYSTEM`; rewrite prompt rewritten with anaphora rule + positive/negative/counter examples |
| Generation | `pipeline/generate.py` | Round-robin packing under `_PROMPT_CHAR_BUDGET` (48k chars); replaces silent per-URL char cap |
| Chunking | `pipeline/chunk.py` | `chunk_pages` now returns `(chunks, global_stats, per_url_stats)`; dedup inlined to attribute drops per URL |
| Orchestration | `app.py` | `url_to_sq` map preserved during dedup; `_per_sq_extract_entries` and `_per_sq_chunk_entries` helpers; per-sub-query slices in extract_done / chunk_done / embed_done; `extract_stats` / `chunk_stats` / `embed_count` persisted per trace; max_results startup log |
| Doc | `docs/improvement-summary.md` | This file |
