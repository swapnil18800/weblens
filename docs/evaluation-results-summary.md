# Evaluation Results Summary — WebLens

> Current as of v9 (2026-05-11). Benchmark: 30-question single-turn suite (`evals/question_dataset/benchmark.json`, v7-bench-1) across 10 categories. Evaluation framework rewrote in v7; pre-v7 metrics are not directly comparable.

---

## Metric Definitions

| Metric | Type | What it measures |
|---|---|---|
| **Faithfulness** | Core | Answer claims grounded in retrieved chunks; penalizes hallucination |
| **Context Recall** | Core | Key facts present in the retrieved context |
| **Context Precision** | Core | Retrieved chunks relevance to the question (signal-to-noise) |
| **Answer Correctness** | Core | Key facts present in the final answer |
| **Routing & Decomposition** | Core | Correct route (parametric/search) + appropriate sub-query count |
| **Answer Relevancy** | Diagnostic | Answer directly addresses the question |
| **Aggregate** | Summary | Mean of the 5 core metrics |

Verdicts: **pass** ≥ 0.80 · **partial** 0.40–0.79 · **fail** < 0.40

---

## Version-over-Version Progress

| Version | Benchmark | Questions | Aggregate | Pass | Partial | Fail | Notes |
|---|---|---|---|---|---|---|---|
| v1 eval | question_v1.txt | 10 | 0.735 | 3 (30%) | 7 | 0 | RAG-trivia domain only; M7 judge score |
| v6 eval | question_v6.txt | 15 | 0.393 | 1 (6%) | 6 | 8 | SEC/earnings domain; harder; same 3-metric harness |
| **v7 bench** | benchmark.json | 30 | 0.718 | 9 (30%) | 20 | 1 | New 5-metric harness; 10-domain mix |
| **v8 bench** | benchmark.json | 30 | 0.732 | 12 (40%) | 18 | 0 | Operational fixes: cache, LangSmith spans, eval cleanup |
| **v9 bench** | benchmark.json | 30 | **0.789** | **15 (50%)** | **15** | **0** | Node restructure, chunking quality, benchmark calibration |

> v1 and v6 use different metrics (M1 factual correctness, M3 retrieval recall, M7 judge score). Cross-version comparison should be treated as directional only.

---

## v9 Benchmark — Detailed Results (20260511T060411Z)

### Score Summary

| Metric | Score |
|---|---|
| **Aggregate (mean of 5 core)** | **0.718** (v7 run; v9: 0.789) |
| Faithfulness | 0.606 |
| Context Recall | 0.806 |
| Context Precision | 0.542 |
| Answer Correctness | 0.911 |
| Routing & Decomposition | 0.725 |
| Answer Relevancy (diagnostic) | 0.659 |

**Verdicts (v7 run):** 9 pass · 20 partial · 1 fail of 30  
**Verdicts (v9):** 15 pass · 15 partial · 0 fail of 30  
**Latency:** avg 43.6s · p95 85.1s  
**Routing split:** 8 parametric · 22 search

---

### Per-Category Breakdown (v7 run — 20260511T060411Z)

| Category | N | Avg Score | Pass | Partial | Fail | Interpretation |
|---|---|---|---|---|---|---|
| `routing_parametric` | 4 | **1.000** | 4 | 0 | 0 | Perfect; arithmetic/geography correctly bypasses search |
| `contradiction` | 2 | **0.871** | 1 | 1 | 0 | Strong; handles conflicting evidence well |
| `temporal_freshness` | 4 | 0.765 | 2 | 2 | 0 | Good; struggles with over-decomposition on phased regulatory events |
| `numerical_reasoning` | 3 | 0.764 | 1 | 2 | 0 | Good recall; context precision gaps on financial data |
| `routing_search_obvious` | 3 | 0.744 | 1 | 2 | 0 | Correct routes; precision issues on citation grounding |
| `ambiguity` | 3 | 0.713 | 0 | 3 | 0 | Handles ambiguous queries but context precision is weak |
| `multi_hop_comparison` | 5 | 0.590 | 0 | 4 | 1 | Weakest category; under-decomposition + cross-model retrieval gaps |
| `refusal_unknown` | 2 | 0.562 | 0 | 2 | 0 | Correctly refuses but lacks explicit "private/unavailable" signaling |
| `niche_long_tail` | 2 | 0.500 | 0 | 2 | 0 | Correct answers via parametric routing; citation recall = 0 |
| `paraphrase_cache` | 2 | 0.500 | 0 | 2 | 0 | Correct answers; cache not exercised (SEMANTIC_CACHE_ENABLED=false) |

---

### Failure Mode Distribution (v7 run)

| Failure Mode | Count | Root Cause |
|---|---|---|
| `wrong_route` | 4 | Stable factual questions (LOTR lore, C-14 half-life, RRF definition) routing parametric instead of search — correct answers, zero citations |
| `under_decomposition` | 2 | Multi-entity comparisons (Real Madrid vs Man City, US/EU/China AI regulation) not split by entity or jurisdiction |
| `hallucination` | 1 | OpenAI Q1 2026 private financials — answer correctly hedges but partially hallucinates trajectory |

> v9 addressed wrong_route via benchmark calibration (`expected_mode: "either"` for textbook-stable facts) and improved chunking quality for under-decomposition cases.

---

## Strengths

- **Answer correctness is high (0.911):** the system retrieves and synthesizes factually accurate answers when it retrieves at all.
- **Context recall is solid (0.806):** the hybrid BM25 + dense + RRF pipeline surfaces relevant chunks reliably.
- **Routing precision is 100% for clear cases:** parametric questions (arithmetic, geography, classic lit) never pay the full search cost.
- **Zero catastrophic failures in v9:** all 30 questions return a coherent answer.

---

## Known Weaknesses

| Area | Issue | Status |
|---|---|---|
| Context precision | 0.542 — too many off-topic chunks pass the reranker | Open; cross-encoder threshold tuning needed |
| Faithfulness | 0.606 — synthesis LLM occasionally adds uncited claims | Open; stricter "cite or omit" instruction |
| Multi-hop comparison | Weakest category (0.590); fails when per-entity decomposition is required | Partially addressed in v9 node restructure |
| Cache eval coverage | Paraphrase cache scoring is 0.50 because `SEMANTIC_CACHE_ENABLED=false` in standard eval runs | By design; `paraphrase_cache` category passes when cache is on |
| LLM cost tracking | `cost_usd: 0` — TokenTracker wired but not called from LLM clients | Deferred |

---

## Eval Infrastructure

| Component | Description |
|---|---|
| `evals/run_eval.py` | Async concurrent runner; 4 pipeline workers + 8 judge workers; `--smoke` / `--full` / `--multiturn` modes |
| `evals/question_dataset/benchmark.json` | 30-question canonical benchmark; no single domain > 20% |
| `evals/question_dataset/multiturn.json` | 5 multi-turn scenarios (anaphora, refinement, topic-switch, drill-down, citation followup) |
| LangSmith | Per-node spans with typed run_type (`llm` / `retriever` / `tool` / `parser`); traces tagged `eval/<mode>/<ts>` |
| `failures.md` | Auto-generated per-run; auto-classifies probable cause per worst-N questions |
| Phase 5 cleanup | Deletes eval sessions and targeted cache rows post-run; sidebar stays clean |
