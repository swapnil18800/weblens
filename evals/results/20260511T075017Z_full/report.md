# WebLens Eval Report — FULL
**Timestamp**: 20260511T075017Z  
**Bench version**: v7-bench-1

## Score Summary

| Metric | Value |
|---|---|
| **Aggregate (mean of 5 core)** | **0.732** |
| Faithfulness | 0.593 |
| Context Recall | 0.817 |
| Context Precision | 0.551 |
| Answer Correctness | 0.956 |
| Routing & Decomposition | 0.742 |
| Answer Relevancy (diagnostic) | 0.000 |

**Verdicts**: ✅ 12 pass · ⚠️ 18 partial · ❌ 0 fail (of 30)  
**Latency**: avg 49.66s · p95 135.41s  
**Judge cost**: $0.0000 total

## Mode Distribution (actual routing)

| Mode | Count |
|---|---|
| parametric | 9 |
| search | 21 |

## Per-Category Breakdown

| Category | N | Avg | Pass | Partial | Fail |
|---|---|---|---|---|---|
| ambiguity | 3 | 0.742 | 1 | 2 | 0 |
| contradiction | 2 | 0.680 | 1 | 1 | 0 |
| multi_hop_comparison | 5 | 0.728 | 3 | 2 | 0 |
| niche_long_tail | 2 | 0.500 | 0 | 2 | 0 |
| numerical_reasoning | 3 | 0.756 | 1 | 2 | 0 |
| paraphrase_cache | 2 | 0.738 | 1 | 1 | 0 |
| refusal_unknown | 2 | 0.500 | 0 | 2 | 0 |
| routing_parametric | 4 | 1.000 | 4 | 0 | 0 |
| routing_search_obvious | 3 | 0.617 | 0 | 3 | 0 |
| temporal_freshness | 4 | 0.781 | 1 | 3 | 0 |

## Per-Question Results

| # | ID | Category | Verdict | Agg | Faith | C-Rec | C-Prec | Correct | Route | Lat |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | p1 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 4.3s |
| 2 | p2 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 5.4s |
| 3 | p3 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 5.3s |
| 4 | p4 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 7.7s |
| 5 | rs1 | routing_search_obvious | partial | 0.75 | 0.50 | 1.00 | 0.25 | 1.00 | 1.00 | 15.5s |
| 6 | rs2 | routing_search_obvious | partial | 0.40 | 0.50 | 0.00 | 1.00 | 0.50 | 0.00 | 6.1s |
| 7 | rs3 | routing_search_obvious | partial | 0.70 | 0.00 | 1.00 | 0.50 | 1.00 | 1.00 | 22.9s |
| 8 | mh1 | multi_hop_comparison | partial | 0.45 | 0.00 | 1.00 | 0.00 | 1.00 | 0.25 | 67.8s |
| 9 | mh2 | multi_hop_comparison | pass | 0.81 | 0.67 | 1.00 | 0.38 | 1.00 | 1.00 | 64.6s |
| 10 | mh3 | multi_hop_comparison | pass | 0.82 | 0.83 | 1.00 | 0.25 | 1.00 | 1.00 | 54.2s |
| 11 | mh4 | multi_hop_comparison | pass | 0.87 | 0.83 | 1.00 | 0.50 | 1.00 | 1.00 | 70.7s |
| 12 | mh5 | multi_hop_comparison | partial | 0.70 | 0.83 | 1.00 | 0.50 | 0.67 | 0.50 | 82.9s |
| 13 | tf1 | temporal_freshness | pass | 0.92 | 0.83 | 1.00 | 0.75 | 1.00 | 1.00 | 24.7s |
| 14 | tf2 | temporal_freshness | partial | 0.70 | 0.40 | 1.00 | 0.62 | 1.00 | 0.50 | 186.1s |
| 15 | tf3 | temporal_freshness | partial | 0.74 | 0.83 | 1.00 | 0.38 | 1.00 | 0.50 | 60.4s |
| 16 | tf4 | temporal_freshness | partial | 0.76 | 0.80 | 1.00 | 0.50 | 1.00 | 0.50 | 52.0s |
| 17 | nr1 | numerical_reasoning | partial | 0.60 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 60.4s |
| 18 | nr2 | numerical_reasoning | partial | 0.79 | 0.83 | 1.00 | 0.12 | 1.00 | 1.00 | 53.0s |
| 19 | nr3 | numerical_reasoning | pass | 0.88 | 1.00 | 1.00 | 0.38 | 1.00 | 1.00 | 47.8s |
| 20 | amb1 | ambiguity | pass | 0.82 | 0.71 | 1.00 | 0.38 | 1.00 | 1.00 | 135.4s |
| 21 | amb2 | ambiguity | partial | 0.70 | 0.00 | 1.00 | 0.50 | 1.00 | 1.00 | 39.2s |
| 22 | amb3 | ambiguity | partial | 0.71 | 0.40 | 1.00 | 0.14 | 1.00 | 1.00 | 22.8s |
| 23 | ctr1 | contradiction | pass | 0.86 | 0.80 | 1.00 | 0.50 | 1.00 | 1.00 | 66.2s |
| 24 | ctr2 | contradiction | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 6.3s |
| 25 | ref1 | refusal_unknown | partial | 0.40 | 0.00 | 0.50 | 0.00 | 0.50 | 1.00 | 178.8s |
| 26 | ref2 | refusal_unknown | partial | 0.60 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 97.8s |
| 27 | niche1 | niche_long_tail | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 6.8s |
| 28 | niche2 | niche_long_tail | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 9.4s |
| 29 | pc1 | paraphrase_cache | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 9.0s |
| 30 | pc2 | paraphrase_cache | pass | 0.97 | 1.00 | 1.00 | 0.88 | 1.00 | 1.00 | 26.4s |

## Failure-mode distribution

| Mode | Count |
|---|---|
| wrong_route | 5 |
| under_decomposition | 1 |
| hallucination | 1 |

*Generated 20260511T075017Z · WebLens Eval v7*