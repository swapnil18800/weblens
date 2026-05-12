# WebLens Evaluation

The evaluation framework lives in `evals/run_eval.py` and the benchmark data lives in `evals/question_dataset/`. It was rewritten in v7 to be lean (5 core metrics, ~30 elite questions), async-concurrent, and produce a usable failure-mode report — not an academic benchmark.

## Philosophy

- **Five high-signal metrics, not forty noisy ones.** Each metric was chosen because it isolates a distinct failure mode the system can have. Layering more metrics on top adds noise without adding signal.
- **Thirty elite questions, not five hundred mediocre ones.** Questions span tech, sports, science, geopolitics, culture, finance, society, health, and foundational topics. **No single domain exceeds ~20% of the benchmark** — overfit to one industry would produce a misleading score.
- **Real failure modes over abstract metrics.** Every run produces a `failures.md` that classifies each failure (`retrieval_miss`, `hallucination`, `wrong_route`, `over_decomposition`, `under_decomposition`, `citation_theater`, `noisy_retrieval`, etc.) — so you immediately know what to fix.
- **Don't penalize the route choice.** Parametric questions have no retrieved chunks; the retrieval-side metrics are N/A and return 1.0 for them. Otherwise the routing decision (skip web search) would be punished by metrics that don't apply.

## The five core metrics

Each is averaged into the **aggregate** score (mean of all five).

| Metric | Type | Failure mode it catches | How it's computed |
|---|---|---|---|
| **Faithfulness** | LLM judge | Hallucination, fabrication | LLM decomposes the answer into ≤ 8 atomic claims, checks each against the retrieved chunks. Score = supported / total. Parametric → N/A (1.0). |
| **Context Recall** | Heuristic | Retrieval miss (the right info wasn't in the candidate pool) | For each `key_fact` in ground truth, regex / fuzzy match against the concatenation of retrieved chunks. Score = hits / total. Parametric → N/A (1.0). |
| **Context Precision** | LLM judge | Noisy retrieval (chunks irrelevant to the query) | For each retrieved chunk, LLM judges whether it's relevant. Score = mean(0/1). Parametric → N/A (1.0). |
| **Answer Correctness** | Heuristic + LLM-assist | Generator dropped or distorted facts | First pass: regex match key_facts against the answer. Second pass: for any missed facts, LLM checks whether the answer asserts them paraphrased. |
| **Routing & Decomposition** | Structural | Wrong route (parametric vs search), over- or under-decomposition | Compares actual `mode` and `len(sub_queries)` against per-question expectations. Wrong mode → 0. Right mode but count off by ±1 → 0.5. |

## Two diagnostic metrics

Reported per-question and in summary, but **not averaged** into the aggregate score.

| Metric | Why diagnostic |
|---|---|
| **Answer Relevancy** | Embedding cosine sim of question and answer. Catches off-topic answers, but correlates with answer length, so aggregating it would punish concise answers. |
| **Latency** | Quality only relative to baseline. Aggregating wall-clock seconds with [0, 1] correctness scores is meaningless. |

## Benchmark structure

`evals/question_dataset/benchmark.json` — 30 single-turn questions:

| Category | N | What it tests |
|---|---|---|
| `routing_parametric` | 4 | Should NOT decompose; should NOT search. Tests analyze step's confidence on textbook-stable knowledge. |
| `routing_search_obvious` | 3 | Looks parametric-shaped but must route to search (population, recent results). |
| `multi_hop_comparison` | 5 | Must decompose; cross-entity. Spread across AI/sports/finance/science/geopolitics. |
| `temporal_freshness` | 4 | Must reflect May 2026 reality. AI model release, geopolitics, space, regulation. |
| `numerical_reasoning` | 3 | Requires retrieval AND arithmetic (YoY %, ratios, deltas). |
| `ambiguity` | 3 | Underspecified — should ask or scope. |
| `contradiction` | 2 | Sources / evidence disagree — should surface the disagreement. |
| `refusal_unknown` | 2 | No reliable source — should admit gaps cleanly. |
| `niche_long_tail` | 2 | Sparse-source factual lookup. |
| `paraphrase_cache` | 2 | Cache hit on the second (only meaningful with `SEMANTIC_CACHE_ENABLED=true`). |

`evals/question_dataset/multiturn.json` — 5 multi-turn scenarios (~12 turns total):

1. **Anaphora cross-entity** — "NVIDIA FY24 datacenter?" → "and AMD?" → "which grew faster?"
2. **Refinement** — "Latest Anthropic model?" → "its context window?"
3. **Topic-switch leakage test** — confirms turn 2 doesn't blend in turn 1's context after an explicit topic switch.
4. **Drill-down concept** — RAG vs fine-tuning → when is RAG cheaper to maintain?
5. **Citation followup** — summarize EU AI Act → what was the source?

## How to run

```bash
# 6 smoke questions (one per major category), tracing on by default
python evals/run_eval.py --smoke

# 30 single-turn questions, tracing off by default (cheaper)
python evals/run_eval.py --full

# 5 multi-turn scenarios — turns within a scenario run serially
python evals/run_eval.py --multiturn

# Full + multi-turn
python evals/run_eval.py --all

# Override defaults:
python evals/run_eval.py --full --trace on
python evals/run_eval.py --full --judge openai      # default: deepseek (cheaper)
python evals/run_eval.py --full --concurrency 2     # back off if rate-limited
python evals/run_eval.py --full --url http://localhost:8000
```

The server must be running (`uvicorn app:app --port 8000`) — the eval harness calls it via HTTP.

### Tracing defaults

| Mode | Default `--trace` |
|---|---|
| `--smoke` | **on** — full per-node visibility while iterating |
| `--multiturn` | **on** |
| `--full` | **off** — saves cost on a 30-question run |
| `--all` | **off** |

`--trace on` sends an `X-Langsmith-Trace: true` header with each pipeline request. The server wraps that request's LangGraph run in `tracing_context(enabled=True)`, so only eval-triggered requests generate traces — normal user traffic is never traced. Traces appear in the `weblens` project on smith.langchain.com.

**Tracing is off by default** (`LANGSMITH_TRACING=false` in `.env`). To turn it on for all traffic (not just eval), set `LANGSMITH_TRACING=true` in `.env` and restart the server — the server calls `load_dotenv()` at startup and the LangSmith SDK will pick it up globally.

## Output

Every run writes to `evals/results/<UTC_TS>_<mode>/`:

```
20260511T060149Z_smoke/
├── per_question/
│   ├── 01_routing_parametric_What_is_12_squared.json
│   ├── 02_routing_search_obvious_What_is_the_current_population_of_Brazil.json
│   └── …
├── summary.json
├── report.md            # readable score tables (per-metric, per-category, per-question)
├── failures.md          # worst 5–10 questions + auto-classified failure modes
└── eval.log             # stdout tee
```

### Reading `report.md`

The header tables tell you:

- **Aggregate** — the headline number. Mean of the five core metrics.
- **Per-metric breakdown** — where the system is strong / weak.
- **Pass / Partial / Fail counts** — verdict derived from aggregate (`≥ 0.8` / `0.4–0.8` / `< 0.4`).
- **Mode distribution** — how many queries took parametric vs search vs cache. Big mismatch with expected mode distribution = analyze step is mis-routing.
- **Per-category breakdown** — which categories are dragging the score.
- **Per-question table** — every metric for every question, with latency.

### Reading `failures.md`

The failure-mode distribution at the top is the most actionable summary:

```
- retrieval_miss: 4
- hallucination: 2
- over_decomposition: 1
```

…tells you immediately what to fix next. Then each of the worst 5–10 questions gets a focused breakdown:

- Which metric(s) dropped + their values
- The judge's reasoning (Faithfulness / Precision)
- Retrieved URLs + which key_facts hit/missed
- A **probable cause** label

## Interpreting metric patterns

| Pattern | Interpretation |
|---|---|
| High Context Recall, low Answer Correctness | Retrieval found the info; the **generator dropped** it. Prompt issue. |
| Low Context Recall, low Answer Correctness | Retrieval **never had** the info. Tavily missed; query phrasing might need work. |
| High Context Recall, low Faithfulness | The chunks were good but the **generator hallucinated**. Strict-prompt issue. |
| High Faithfulness, low Answer Correctness | The answer is internally consistent with the chunks, but the **chunks themselves were wrong** for the question. (Could be temporal staleness in the source pages.) |
| Routing = 0 (wrong route) on a parametric category | Analyze step is over-routing to search. Loosen the parametric few-shots. |
| Routing = 0 (wrong route) on a search category | Analyze step is over-routing to parametric. Tighten the bias-to-search language. |
| Routing = 0.5 with `over_decomposition` | Comparison or single-fact queries are being fanned out unnecessarily. Decomposition prompt issue. |

## Extending the benchmark

To add a question, append to `evals/question_dataset/benchmark.json`:

```json
{
  "id": "tf5",
  "category": "temporal_freshness",
  "domain": "biotech",
  "question": "What were the major FDA approvals in Q1 2026?",
  "expected_mode": "search",
  "expected_sub_query_count": "single",
  "expected_behavior": "Should surface recent approvals with citations.",
  "key_facts": ["FDA", "2026"],
  "ground_truth": "(brief prose for human reviewer)",
  "tags": ["temporal", "biotech"]
}
```

Then **immediately re-run `--smoke`** to confirm the question executes and the metrics produce sensible numbers. If `key_facts` are too strict, Answer Correctness will drop misleadingly; if too lax, the metric won't catch real misses.

Ground truth for temporal/numerical questions should be sourced from authoritative public references (SEC filings, government data, established news) at authoring time and re-verified periodically as facts age.

## Cost

- **Smoke run** (6 questions, judge enabled): ~3 LLM judge calls per question × 6 = 18 calls. On DeepSeek that's roughly $0.005 per run.
- **Full run** (30 questions): ~90 judge calls ≈ $0.025 per run.
- **Multi-turn** (~12 turns): ~36 judge calls ≈ $0.01 per run.

Pipeline LLM cost (analyze + generate + synthesize) is separate and depends on the model — see the `latency_breakdown.token_cost` field in each per-question JSON.
