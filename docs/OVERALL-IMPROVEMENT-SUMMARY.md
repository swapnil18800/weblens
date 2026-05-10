# WebLens — Overall Improvement Summary (v1 → v6)

A consolidated change history across every shipped iteration. For the
canonical per-version detail, see the linked `implementation-summary-vN.md`
files. For the current architecture and on-disk layout see
[ARCHITECTURE.md](./ARCHITECTURE.md) and
[DIRECTORY-STRUCTURE.md](./DIRECTORY-STRUCTURE.md).

---

## At-a-glance timeline

| Version | Date | Theme | Detail |
|---|---|---|---|
| **v1** | 2026-05-07 | First end-to-end build | [implementation-summary-v1.md](./implementation-summary-v1.md) |
| **v3** | 2026-05-08 | Vite/React rewrite + parallel sub-query gen | [implementation-summary-v3.md](./implementation-summary-v3.md) |
| **v4** | 2026-05-08 | UX pass: loading, branding, sidebar, About modal | [implementation-summary-v4.md](./implementation-summary-v4.md) |
| **v5** | 2026-05-09 | Premium-feel pass: tag chips, persistence, sidebar polish | [implementation-summary-v5.md](./implementation-summary-v5.md) |
| **v6** | 2026-05-10 | Trace honesty + decomposition + persistence parity | [implementation-summary-v6.md](./implementation-summary-v6.md) |

(There is no v2 doc — v3 superseded an in-progress branch before it shipped.)

---

## What each version delivered

### v1 — First end-to-end build

The first shippable cut of the system. Established the core architecture
that survives unchanged today:

- **8-stage pipeline**: decompose → search → extract → chunk → embed →
  retrieve → rerank → generate.
- **Tavily** for URL discovery; **Jina Reader** (with **trafilatura**
  fallback) for full-page extraction; **all-MiniLM-L6-v2** for embeddings;
  **TinyBERT** cross-encoder for rerank; **DeepSeek V3** for generation.
- **Hybrid retrieval**: BM25 + dense → RRF fusion → cross-encoder rerank.
- **Per-sub-query streaming + synthesis**: each sub-query's answer
  streams independently; a final LLM call merges them into one cohesive
  answer with consistent `[N]` citations.
- **Session persistence** in Supabase (Postgres + pgvector). `page_cache`
  with 24h TTL keeps re-fetches cheap; `web_chunks` lets future queries
  reuse the same embeddings.
- **Eval harness** (`evals/run_eval.py`) — runs question files end-to-end
  and scores answers with a judge LLM.
- **Initial frontend**: monolithic `frontend/index.html` (~1700 lines).

Known limitations called out at the time: financial year-scope discipline,
transcript grounding, hallucination on niche data, and generation latency.

### v3 — Vite/React rewrite + concurrency

Two big shifts: the frontend became a proper Vite + React 18 + TypeScript +
Tailwind project, and the backend got real concurrency.

**Backend**
- Port moved to **8765** (8000 reserved for AlphaLens). CORS narrowed from
  wildcard to an explicit allow-list.
- **Parallel sub-query generation** via `asyncio.Queue` multiplexing —
  every sub-query coroutine starts concurrently and tokens interleave
  through one queue.
- Heavy work (`SentenceTransformer.encode`, `CrossEncoder.predict`) moved
  off the event loop with `loop.run_in_executor`.
- **GPU auto-detection** via `_pick_device()` with CPU fallback.
- `DELETE /api/sessions/{session_id}` endpoint added.

**Pipeline tuning**
- Decompose: hard cap removed; soft cap 24. Prompt rewritten to remove
  count bias and seeded examples.
- Retrieve: `EMBED_POOL` 20→24, `CE_POOL` 12→16, `TOP_K` 5→10 (later
  tuned back to 8 for prompt-budget reasons).
- Generate: prompts tightened (150–250 word sub-answers; 350–500 word
  syntheses with mandatory comparison tables for ≥2 entities and a "Key
  Takeaways" closer).

**Frontend (full rewrite)**
- New `frontend/` Vite project replaces `index.html`.
- Component-driven: `ChatPage`, `ChatThread`, `ChatTurn`, `ReasoningTrace`,
  `Answer`, `CitationPreview`, `Sidebar`, `Header`, `Hero`, etc.
- Zustand store (`chatStore.ts`) becomes the single source of truth.
- Tailwind theme: dark `bg`, single `accent`, status colours
  (`good`/`warn`/`bad`/`info`).

### v4 — UX pass

A grab-bag pass focused on first-impression polish and reducing visual
chrome:

- **Loading**: clicking a past session shows a spinner + skeleton instead
  of falling back to the Hero.
- **Scroll behaviour**: each turn carries `data-turn-id`; new turns
  `scrollIntoView({ block: "start" })`. (This is the foundation v6 fixes.)
- **Auto-scroll on final answer ready** when `finalStatus → done`.
- **Header reshuffle**: Examples moved to the header next to Eval; New
  chat button moved into the sidebar.
- **Branding**: logo click triggers New chat + nav home; favicon updated
  to the WebLens glyph.
- **Sidebar**: drag-to-resize handle (200–540 px, persisted in
  `localStorage`); edge-tab collapse replaces the floating Sessions pill.
- **About modal**: centered backdrop-blurred modal (replaces the popover);
  Esc / click-outside fade-out; LinkedIn + GitHub links.
- **Reasoning trace — semantic overhaul**: each step gets a clear label
  and a one-line detail string (the foundation v6 builds on).
- **Citation panel unified** into a single right-side panel.

### v5 — Premium feel + persistence

End-to-end UI/UX refactor focused on visual consistency, persistence
fidelity, and a few interaction quirks. Two themes:

**Sidebar polish**
- Collapsed rail moved below the header (was overlapping the logo).
- Single protruding-toggle component; chevron rotates 180° on toggle.
- `+` New-chat tile becomes a 40 × 40 pill stacked under the toggle when
  collapsed.

**Visual consistency**
- **Tag chips finally render** — v4 used `@apply bg-emerald-400/12 …`
  inside `@layer components`, but the `/12` arbitrary-opacity utilities
  weren't generated by the build. Fixed by switching to numeric opacity
  values.
- **Sub-query collapse on load**: loaded sessions now show sub-queries
  collapsed by default (was expanded → noisy).
- **Citation panel — single-window inline preview**: clicking `[N]` opens
  the side panel pre-expanded on that citation rather than scrolling
  the inline list.
- **Chunk preview**: truncation + blur-fade-on-expand; theming aligned
  with the rest of the surfaces.

**Trace persistence — never flush again**
- Backend writes the full per-sub-query trace into `traces` JSONB on
  every successful turn.
- Frontend `chatStore.loadSession` rehydrates `Turn[]` from persisted
  data; `rehydrateSteps` rebuilds the `ReasoningStep[]` sequence so
  loaded turns render identically to a fresh stream.
- Eval adapter (`eval-adapter.ts`) bridges persisted eval JSON into the
  same `Turn` shape so the eval inspector reuses chat-page components.

**v5.1 fine-tuning** (same doc, later additions)
- Sidebar chrome cleanup; synthesis-phase elapsed chips; `[N]` always
  opens the side panel; floating scroll-to-end moved to right side with
  solid accent fill.

### v6 — Trace honesty + decomposition + persistence parity

Latest pass. Fixes 17 distinct issues across UX, pipeline, decomposition,
generation, and persistence. Full detail in
[implementation-summary-v6.md](./implementation-summary-v6.md). Highlights:

**Trace UX**
- Rerank step text simplified from misleading `candidates 24 → CE 16 → top
  8 (7 per-URL cap)` to honest `Selected top 8 passages`.
- Broken `score: –` placeholder removed.
- "Top passages used" dropdown folded into the rerank step's expandable body.
- Source/page list rewritten: shows **Tavily titles** (not bare domains),
  with status chips (`extracted · 145.5k`, `cached`, `http error`,
  `too short`, `parse error`), sorted by char count desc, constrained to
  the per-sub-query URL subset.
- "Split into passages" per-URL chunk dropdown removed (pure noise).

**Per-sub-query stats (the big architectural fix)**
- Extraction and chunking still run **once globally** (cheap).
- `app.py` preserves a `url_to_subqueries` map at search time.
- After global extract / chunk, `_per_sq_extract_entries` and
  `_per_sq_chunk_entries` partition the global outcome into per-sub-query
  slices.
- `chunk_pages` extended to return `per_url_stats` so per-URL drop counts
  attribute correctly back to each sub-query.
- `extract_done` / `chunk_done` / `embed_done` events carry a
  `per_subquery: [{...}]` array; chatStore routes each slice into the
  matching sub-query.
- Per-sub-query trace blocks now show DIFFERENT numbers per sub-query
  (was identical-across-all-three before).

**Decomposition**
- `_today()` injected into both `_DECOMPOSE_SYSTEM` and `_REWRITE_SYSTEM`
  prompts.
- New **Temporal Reasoning** section in decompose: treat "recent /
  latest / no time scope" as the last 12 months ending today; never
  default to a training-data fiscal year; honor explicit user dates.
- New **anaphora rule** in rewrite: apply prior context only for
  pronouns / fragments / transformation requests; otherwise leave the
  query unchanged. Reinforced with positive (continuation), negative
  (topic shift), and counter (mistakes-to-avoid) examples.
- Fixes "FY2024 in May 2026" and "sadhguru vs osho? → NVIDIA's CEO on
  Sadhguru" failure modes.

**Generation**
- `_build_prompt` switched from per-URL 6,000-char hard cap (silently
  dropped chunks) to **round-robin packing** under
  `_PROMPT_CHAR_BUDGET = 48,000` chars.
- All top-K chunks now reach the LLM under typical workloads. Stderr
  warning if the budget bites (rare).

**Persistence parity**
- Persisted `traces[i]` extended with `extract_stats`, `chunk_stats`,
  `embed_count` — the per-sub-query slices.
- `rehydrateSteps` reads them and reproduces the full live trace
  (chips, drop breakdowns, source titles).
- Live and rehydrated traces are now visually identical.

**Layout**
- Tail spacer in `ChatThread` so the new question can always scroll to
  the viewport top (root cause: `scrollTop` was clamping with short
  content).
- Session-click scroll retargeted to the **last turn's `offsetTop - 8`**
  instead of `scrollHeight` (which now lands inside the spacer's empty
  region).
- Question-bubble hover icons bumped from `w-3.5 h-3.5 text-neutral-500`
  to `w-4 h-4 text-neutral-300 hover:text-white` with `strokeWidth=2.25`;
  Copy button added alongside Edit + Retry; version pager bumped to
  `text-sm font-medium`.
- **Retry button** added to the answer toolbar (was hover-only on the
  question).
- Followup suggestions redesigned: vertical list with `↪`
  (`CornerDownRight`) icon, dotted bottom border, full-row hover
  highlight (was a 3-col chip grid).

---

## Cumulative trajectory

Reading the versions in sequence, three threads run through every release:

### 1. From "approximate" to "honest" trace UI

- **v1**: trace existed but was minimal.
- **v3**: added enriched SSE payloads (per-sub-query search counts,
  rerank explain dicts).
- **v4**: semantic overhaul — every step row gained a clear label +
  one-line detail.
- **v5**: trace persistence (loaded sessions render the same trace) +
  visual fixes (tag chips actually rendering).
- **v6**: dropped the misleading bits (rerank funnel internals); per-
  sub-query stats now reflect each sub-query's own URLs; source list
  shows Tavily titles + status chips; live and rehydrated traces are
  visually identical.

The arc is from "show the user something" → "show them the truth."

### 2. From "single-LLM-call" to "concurrent multi-stage"

- **v1**: pipeline runs sequentially; sub-query gen is a `for` loop.
- **v3**: parallel sub-query generation via `asyncio.Queue`; encode /
  predict moved to executor; GPU auto-detection.
- **v6**: per-sub-query stats partitioning preserves the cheap "once
  globally" extraction model while still surfacing honest per-sub-query
  numbers.

The arc is "fast enough" → "fast and honest about what's parallel."

### 3. From "magic numbers" to "principled defaults"

- **v1**: hard-coded TOP_K=5, no decomposition cap rationale.
- **v3**: pool sizes tuned (EMBED_POOL=24, CE_POOL=16, TOP_K bumped);
  prompt word-count targets calibrated.
- **v6**: round-robin packing replaces per-URL char caps; date injection
  replaces training-cutoff defaults; anaphora rule replaces
  always-blend-history default.

The arc is from "guess and ship" → "every default has a reason."

---

## What's still on the roadmap

Carried forward from v1's "Scope of Improvements" and not yet shipped:

- **Year-scope discipline in generation prompt** — v6 fixed the
  decomposition side; the generation prompt could still be tightened to
  refuse uncited year claims more aggressively.
- **Transcript sourcing** — first-party investor relations sites are
  sometimes blocked by Jina Reader (403). A dedicated transcript fetcher
  (e.g. via SEC EDGAR for 10-Q transcripts) would help financial queries.
- **Strict refusal** — "I don't have enough information" is undertriggered.
- **Retrieval** — IVFFlat index could be re-tuned as `web_chunks` grows.
- **Eval** — judge prompt could be sharpened to reduce false-positive
  scoring on partial answers.
- **Infrastructure** — server logs aren't yet rotated; deployment is
  Railway single-instance.

---

## How to read these documents

If you want to know:

| Question | Read |
|---|---|
| What does the system look like today? | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Where is X on disk? | [DIRECTORY-STRUCTURE.md](./DIRECTORY-STRUCTURE.md) |
| How do I run it locally? | [how-to-run.md](./how-to-run.md) |
| How do I deploy it? | [DEPLOYMENT.md](./DEPLOYMENT.md) |
| Why was X built this way? | This file (overall) + version-specific summary |
| What changed in version N? | `implementation-summary-vN.md` |
| Interview-prep deep dive | [INTERVIEW.md](./INTERVIEW.md) |
