# Implementation Summary — v5

End-to-end UI/UX refactor pass focused on premium feel, persistence, and trace fidelity.
Reference: [v4 baseline](implementation-summary-v4.md).

## Sidebar — collapse / resize

- **Collapsed rail moved below the header.** The chevron + `+` buttons used to mount at
  `top: 16px` and visually overlap the WebLens logo. They now anchor at
  `top: HEADER_HEIGHT + 8px` (56 px) so they always sit cleanly under the header.
  ([Sidebar.tsx](../frontend/src/components/Sidebar.tsx))
- **Single protruding-toggle component.** The arrow protrudes from the right edge of
  the sidebar (or the left edge of the screen when collapsed) as a 40 × 40 rounded
  pill. The chevron animates a 180° `rotate` via Framer Motion when toggled instead
  of swapping between two icons.
- **`+` New-chat tile** is the same 40 × 40 pill, stacked under the toggle when
  collapsed.
- **Drag-to-resize** still works — the sidebar's `position: relative` containing
  block is intact, so the absolute resize handle on the right edge is positioned
  against the sidebar (not the page).

## Tag chips — finally visible

- v4 used `@apply bg-emerald-400/12 …` inside `@layer components`. The `/12`
  arbitrary opacity didn't generate valid CSS in our Tailwind build, leaving every
  tag rendered as plain white text on no background.
- The `Tag` component now uses literal class strings (`bg-emerald-500/10`,
  `border-emerald-500/30`, …) so Tailwind's content scanner picks them up
  unconditionally and the soft pastel palette (yellow / blue / red / green) renders
  consistently. ([ReasoningTrace.tsx](../frontend/src/components/ReasoningTrace.tsx))

## Trace persistence — never flush again

Trace rows used to disappear on session reload, leaving only Search / Cross-encoder /
Generate per sub-Q and dropping the global Combining + Final phases entirely.

### Backend ([app.py](../app.py))

`latency_breakdown` is now an enriched, frontend-canonical schema:

```json
{
  "decompose_ms": 2526,
  "decompose_mode": "fast_path",
  "search_ms": 4193,
  "extract_ms": 1023,
  "chunk_ms": 34,
  "embed_ms": 3654,
  "retrieve_ms": 3654,
  "rerank_ms": 3654,
  "synthesis_ms": 1180,
  "pages_count": 6,
  "chunks_count": 18,
  "embed_device": "cpu",
  "sub_queries_count": 1
}
```

The same payload flows through the `done` SSE event, the persisted
`rag_session_messages.latency_breakdown` JSONB column, and (for new runs)
`evals/results/*.json`.

### Frontend ([chatStore.ts](../frontend/src/state/chatStore.ts))

`rehydrateSteps(trace, breakdown)` now produces the **exact same six step rows**
the live SSE pipeline emits, with matching labels and copy:

| Kind     | Label                  | Detail                                |
|----------|------------------------|---------------------------------------|
| search   | Searched the web       | `Found N sources`                     |
| extract  | Read pages             | `Read N pages`                        |
| chunk    | Split into passages    | `Built N passages`                    |
| embed    | Indexed passages       | `N passages ready for ranking`        |
| rerank   | Picked best evidence   | `Selected top N passages`             |
| generate | Drafted answer         | `N words`                             |

`loadSession` also restores `combiningStatus: "done"` and `finalStatus: "done"`
on the rehydrated turn so the `Combining sub-answers` and
`Generating final answer` rows render. Old eval JSON without the new fields
falls back gracefully (page/passage counts derived from `urls.length` and
`chunks.length`).

### Eval adapter ([eval-adapter.ts](../frontend/src/lib/eval-adapter.ts))

`evalQuestionToTurn` mirrors the same six-step reconstruction so the eval-page
trace is byte-identical to the live + history paths. Sets the synthesis-phase
status fields too.

## Sub-query collapse on load

`ReasoningTrace.tsx` previously kept the single-Q sub-trace open by default
(`defaultOpen={turn.subqueries.length === 1}`). Hydrated/eval/stopped turns now
render with sub-Q traces collapsed by default, matching the parent reasoning
trace's auto-collapse behaviour:

```ts
defaultOpen={isStreaming && turn.subqueries.length === 1}
```

## Citation routing

| Click target                              | v4 behaviour            | v5 behaviour            |
|-------------------------------------------|-------------------------|-------------------------|
| `[N]` in **final answer**                 | Inline expand below     | Inline expand below     |
| `[N]` in **sub-answer card**              | Inline (nested + ugly)  | Right-side panel        |
| Chunk row in trace                        | Right-side panel        | Right-side panel        |
| Toolbar **Citations N** pill              | Right-side panel        | Right-side panel        |

The split is now explicit in `ChatTurn.tsx` via `onCiteClick` (final-answer
inline) and `onSubCiteClick` (sub-answer side-panel).

## Citation panel — single-window inline preview

[CitationPreview.tsx](../frontend/src/components/CitationPreview.tsx) was
refactored from a two-mode panel (list vs preview) into a **single chunk list
with inline expand-below preview**:

- One row open at a time. Clicking another row collapses the previous one.
- Clicking the same row toggles it closed.
- Pre-expanded selection honoured when the panel is opened from a chunk-click in
  the trace (the matching citation is auto-expanded).
- Preview animates with `AnimatePresence` height + opacity easing
  (`[0.16, 1, 0.3, 1]`).
- Inline metadata chips: rank uses accent (blue), score uses metric (purple),
  matching the rest of the chrome.

## Chunk preview theming

Chunk text used `chip-info` (sky) and `surface` (neutral). Both the inline
citation card and the panel chunk preview now use a soft accent → metric
gradient:

```css
background-image: linear-gradient(
  135deg,
  rgba(91, 140, 255, 0.06)  0%,   /* accent  #5b8cff */
  rgba(139, 92, 246, 0.06) 100%   /* metric  #8b5cf6 */
);
```

Same gradient is reused in `ChatTurn.tsx`'s `InlineCitationCard` so the two
preview surfaces feel related.

## Eval page parity

`QuestionDetail.tsx` was already wired to render via the shared `ReasoningTrace`
component plus ground truth, key facts, judge reasoning, and the M1/M3/M7 chips.
With the eval-adapter rewrite, the trace section now renders identically to the
live chat and persisted-history paths.

### Smoke verification

Real smoke runs require the FastAPI server + Tavily/DeepSeek/OpenAI keys, so a
static smoke check was performed against the existing
`evals/results/20260508T041306Z_v6_smoke/*.json` outputs:

| File                                    | Sub-Qs | URLs | Pages | Passages (top-K) |
|-----------------------------------------|-------:|-----:|------:|-----------------:|
| `01_single_simple_…`                    |      1 |    6 |     6 |                8 |
| `02_cross_company_simple_…`             |      2 |   12 |    12 |               16 |
| `03_strict_refusal_…`                   |      3 |   17 |    17 |               24 |

All three resolve through the new adapter to the canonical six-step trace
(`Searched the web → Read pages → Split into passages → Indexed passages →
Picked best evidence → Drafted answer`) plus `Combining sub-answers` and
`Generating final answer` synthesis rows. New eval runs (after the backend
update) replace the `len(urls)` / `len(chunks)` fallbacks with the precise
`pages_count` / `chunks_count` from the pipeline.

## Verification

- `npx tsc --noEmit` — clean.
- `npx vite build` — clean (525 kB / 163 kB gzipped).
- `python -c "import ast; ast.parse(open('app.py').read())"` — clean.

## Files touched

```
app.py                                     +18  -5
frontend/src/components/CitationPreview.tsx ~  full rewrite of preview surface
frontend/src/components/ChatTurn.tsx       +13  -1   (linter-merged)
frontend/src/components/ReasoningTrace.tsx +12  -3   (Tag colour fix + sub-Q gate)
frontend/src/components/Sidebar.tsx        full rewrite
frontend/src/lib/eval-adapter.ts           +30 -22
frontend/src/state/chatStore.ts            +44 -12
docs/implementation-summary-v5.md          new
```

---

## v5.1 — fine-tuning corrections

Follow-up pass after the first v5 build was reviewed.

### Sidebar chrome cleanup ([Sidebar.tsx](../frontend/src/components/Sidebar.tsx))

- **Removed the in-pane "+ New session" button and the "Conversations" header
  label.** The session list now starts at the top of the sidebar with a small
  `pt-2` breathing-room.
- **Toggle no longer overlaps the list.** The protruding chevron pill used to
  sit at `transform: translateX(50%)` (centred on the right edge → half inside
  the sidebar, overlapping the now-removed New Session button). It now sits at
  `translateX(100%)` so the toggle's *left* edge kisses the sidebar's *right*
  edge — fully outside the content area.
- **Toggle vertical position** moved from the header centre line down to
  `top: HEADER_HEIGHT + 8px`, matching the collapsed rail anchor exactly so
  toggling the sidebar doesn't make the chevron jump.

### Synthesis-phase elapsed chips
([ReasoningTrace.tsx](../frontend/src/components/ReasoningTrace.tsx),
[chatStore.ts](../frontend/src/state/chatStore.ts),
[types.ts](../frontend/src/lib/types.ts))

- New `Turn` fields: `combiningStartedAt`, `combiningCompletedAt`,
  `finalStartedAt`, `finalCompletedAt`. Wall-clock timestamps drive the new
  green tag on the **Combining sub-answers** and **Final answer ready** trace
  rows.
- Store transitions now stamp these timestamps:
  - All sub-answers done → `combiningStartedAt = now`; for single-Q runs the
    combining phase is treated as instant (`combiningCompletedAt = now`,
    `finalStartedAt = now`).
  - `synthesis_start` (multi-Q) → `combiningCompletedAt = now`,
    `finalStartedAt = now`.
  - `done` → `finalCompletedAt = now` (and any unset earlier marks are
    backfilled).
- Loaded sessions and eval turns reconstruct the timestamps from
  `latency_breakdown.synthesis_ms` so the chips render on history too.
- New `phaseElapsed(startedAt, completedAt, isStreaming, now)` helper resolves
  the chip value: frozen if the phase completed, live (counting up) while
  running, hidden otherwise.

### Citation [N] always opens the side panel
([ChatTurn.tsx](../frontend/src/components/ChatTurn.tsx))

- Dropped the inline `InlineCitationCard` entirely (and the
  `inlineCiteNum`/`inlineCitation`/`inlineChunk` state). All `[N]` clicks —
  whether from the final answer, a sub-answer card, or a chunk row in the trace
  — now route through the same `setPanelCiteNum` + `setPanelOpen` path.
- The slide-in side panel pre-expands the matching citation row, so the user
  sees the chunk immediately without an extra click.
- Removed unused imports (`ExternalLink`, `X`, `shortHost`).

### Chunk preview truncation + blur-fade expand
([CitationPreview.tsx](../frontend/src/components/CitationPreview.tsx))

- New `ChunkBody` component: the chunk text starts capped at 140 px with a
  bottom-edge fade-to-bg gradient + small `ChevronsDown` button. Clicking the
  button animates `maxHeight` to its full size; a "Collapse" pill appears below
  to reverse it.
- Overflow detection is measured (`scrollHeight > collapsed + 4`) so short
  chunks don't render the fade or arrow at all — no false affordance.
- Same accent → metric (blue → purple) gradient on the text container, so
  the truncated and expanded views look identical aside from height.

### Floating scroll-to-end button — right side, solid accent
([ChatThread.tsx](../frontend/src/components/ChatThread.tsx))

- Moved from `bottom-4 left-4` (low-contrast surface chip) to `bottom-4 right-5`
  so it sits at the right edge of the chat column, directly above the chat
  input.
- Re-styled to **solid accent** (`bg-accent/90 hover:bg-accent text-white`)
  with an accent-tinted shadow so it reads as a primary affordance instead of
  a quiet utility chip. 40 × 40 (up from 36 × 36).

### Verification

- `npx tsc --noEmit` — clean.
- `npx vite build` — clean (525 kB / 163 kB gzipped, +0.18 kB CSS for the new
  truncation overlay).

