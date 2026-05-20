# Evaluation Summary — v12

Companion to `docs/implementation-summary-v12.md`. This file is intentionally
honest about what is, and is not, expected to move on the benchmark.

> **Note**: This document was authored alongside the code changes but a full
> eval suite run on the benchmark dataset was **not** executed in this PR —
> the live LLM calls and Tavily/Jina HTTP hits required real network and API
> budget. The numbers below describe expected directions and the
> instrumentation that makes them measurable, not measured deltas. Run
> `python evals/run_eval.py` post-deploy to populate the actual comparison.

---

## What the eval suite measures, and what should move

### Routing accuracy (Phase 1)

Add 20 routing cases to `evals/benchmark.json` covering:

- Greetings: "hi", "hello", "how are you"
- Identity/meta: "who are you?", "what can you do?", "how does this work?"
- Stable explanations: "explain transformers", "what is a binary search tree?",
  "summarize Kafka"
- Freshness: "best Udemy courses on Agentic AI", "latest LLM releases"
- Comparisons: "compare PostgreSQL vs MySQL"
- Artifact requests: "give me a PDF", "draw a diagram of how transformers work"

Assert `mode` matches expected for each. Expected accuracy ≥ 95% on this set.
Current baseline (heavy "default to search" bias): all greetings/meta/stable
queries routed as `search` — i.e. ~0% on the parametric subset.

### Per-subquery pipelining (Phase 3)

Instrument with a slow-page fixture (mock 5s extraction for one URL). Run a
3-subquery query.

- **Pre-v12**: first `sub_answer_done` cannot arrive until ALL subquery
  retrievals finish — so the slow subquery gates everyone.
- **Post-v12**: fast subqueries' `sub_answer_done` arrives independently of
  the slow one. Expected p50 multi-subquery generation latency improvement:
  **15–30%** on 3+ subquery queries (single-subquery queries unaffected).

### Citation utilization (Phase 4)

Captured directly in `sub_answer_done.utilization_ratio` and aggregated in
`latency_breakdown.utilization_ratio_overall` /
`utilization_ratio_median`. Target post-change:

- Median utilization ≥ 0.6 (was reported anecdotally low; e.g. 2/8 = 0.25).
- Expect prompt tightening alone to move this meaningfully because the prompt
  now explicitly forbids dropping relevant sources.

### Conversational drift (Phase 7)

Reuse `evals/smoke_conversation_history.py` and add a new fixture:

- Turn 1: "top dsa questions"
- Turn 2: "give me top 30"
- Expected: rewriter returns
  `{rewritten="Give me the top 30 DSA interview questions",
    is_topic_switch=false, active_topic="DSA interview questions",
    active_constraints=["top 30"]}`. Sub-queries stay on DSA, NOT on
  "largest companies / highest-grossing films / tourist attractions"
  (the documented regression).

Topic-switch test:

- Turn 1: "What is React reconciliation?"
- Turn 2: "best Italian restaurants in Rome"
- Expected: `is_topic_switch=true`. Decompose receives empty history;
  retrieval / synthesis context isolated to the new topic.

### Generation lifecycle (Phase 5)

Manual integration test:

1. Start a long-running query (multi-subquery, recent topic).
2. Close the browser tab mid-stream.
3. Wait 30s.
4. Reload the session via the sidebar.
5. Expected: the saved answer is present in the chat history (i.e. the
   generation completed server-side and was persisted by `node_emit_done`).
6. Pre-v12 expected behavior: answer missing or partial; session shows the
   aborted message.

For `/resume`: hit
`GET /api/search/{request_id}/resume` mid-flight and verify the replay buffer
+ live tail returns identical events to the original stream.

---

## Possible regressions (called out honestly)

- **Phase 1**: tuning the parametric/search bias may misclassify some edge
  cases. The `route_reason` field and LangSmith spans make
  misclassifications inspectable. Mitigation: extend the example list in
  `_ANALYZE_SYSTEM` if a category proves problematic.
- **Phase 3**: the global citation map is built incrementally now. If two
  sub-queries finish retrieve concurrently and share a URL, the `[N]`
  assigned to that URL depends on which acquires the lock first
  — slightly non-deterministic across runs. Numbering is still consistent
  within a run.
- **Phase 4**: the "use as many sources as relevant" instruction could make
  answers longer (sub-answer length cap raised from 250 → 280 words to
  accommodate). Watch for answer-length inflation in the eval.
- **Phase 6**: hyperlink instructions occasionally cause the model to link
  generic phrases. The safety-net strip catches hallucinated URLs but
  cannot fix links pointing to a real source where the model linked the
  wrong text. Mitigation: prompt forbids linking generic words; review eval
  examples.
- **Phase 7**: the rolling summary is fire-and-forget — if a session reaches
  `n > 4` turns AND the summary background task fails repeatedly, older
  context is effectively dropped for the rewriter. The next successful
  update will fold the accumulated evicted turns at once. No data is lost
  on the messages table.

---

## Latency table (expected directions)

| Metric | Pre-v12 baseline (estimated) | Post-v12 expected |
|---|---|---|
| Parametric route latency (greeting) | ~6–10s (full pipeline) | ~1–2s (LLM only) |
| Multi-subquery p50 (3 subqueries) | sum(slowest extract)+sum(slowest retrieve)+max(generate) | sum(slowest extract)+max(retrieve+generate per subquery) |
| Rewrite step latency | ~150–300ms | ~250–500ms (richer JSON output) |
| Memory-state update latency (user-visible) | n/a | **0ms** (fire-and-forget) |
| Hyperlink filter overhead | n/a | <1ms per sub-answer |
| Citation utilization (median) | ~0.25 (anecdotal) | ≥0.6 target |
| Cancellation cost (client disconnect) | answer lost | answer persisted |

---

## How to reproduce

```
# Migrate DB
python db/migrate_sessions.py

# Smoke
python evals/cache_smoke.py
python evals/langsmith_smoke.py
python evals/smoke_conversation_history.py

# Full eval
python evals/run_eval.py

# Manual UX
uvicorn app:app --reload --port 8000
# Then in browser: "hi", "give me a PDF", session-switch during generation,
# "top dsa questions" → "give me top 30", "best Udemy courses on Agentic AI"
```
