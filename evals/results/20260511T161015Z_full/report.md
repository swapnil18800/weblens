# WebLens Eval Report — FULL
**Timestamp**: 20260511T161015Z  
**Bench version**: v7-bench-1

## Score Summary

| Metric | Value |
|---|---|
| **Aggregate (mean of 5 core)** | **0.789** |
| Faithfulness | 0.649 |
| Context Recall | 0.867 |
| Context Precision | 0.654 |
| Answer Correctness | 0.950 |
| Routing & Decomposition | 0.825 |
| Answer Relevancy (diagnostic) | 0.594 |

**Verdicts**: ✅ 15 pass · ⚠️ 15 partial · ❌ 0 fail (of 30)  
**Latency**: avg 38.1s · p95 73.03s  
**Judge cost**: $0.0000 total

## Mode Distribution (actual routing)

| Mode | Count |
|---|---|
| parametric | 9 |
| search | 21 |

## Per-Category Breakdown

| Category | N | Avg | Pass | Partial | Fail |
|---|---|---|---|---|---|
| ambiguity | 3 | 0.858 | 2 | 1 | 0 |
| contradiction | 2 | 0.771 | 1 | 1 | 0 |
| multi_hop_comparison | 5 | 0.770 | 3 | 2 | 0 |
| niche_long_tail | 2 | 1.000 | 2 | 0 | 0 |
| numerical_reasoning | 3 | 0.755 | 1 | 2 | 0 |
| paraphrase_cache | 2 | 0.750 | 1 | 1 | 0 |
| refusal_unknown | 2 | 0.550 | 0 | 2 | 0 |
| routing_parametric | 4 | 1.000 | 4 | 0 | 0 |
| routing_search_obvious | 3 | 0.652 | 0 | 3 | 0 |
| temporal_freshness | 4 | 0.721 | 1 | 3 | 0 |

## Per-Question Results

| # | ID | Category | Verdict | Agg | Faith | C-Rec | C-Prec | Correct | Route | Lat |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | p1 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 20.0s |
| 2 | p2 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 6.1s |
| 3 | p3 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 7.4s |
| 4 | p4 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 10.9s |
| 5 | rs1 | routing_search_obvious | partial | 0.77 | 0.60 | 1.00 | 0.25 | 1.00 | 1.00 | 29.4s |
| 6 | rs2 | routing_search_obvious | partial | 0.40 | 0.50 | 0.00 | 1.00 | 0.50 | 0.00 | 10.1s |
| 7 | rs3 | routing_search_obvious | partial | 0.79 | 0.80 | 1.00 | 0.12 | 1.00 | 1.00 | 24.3s |
| 8 | mh1 | multi_hop_comparison | partial | 0.62 | 0.00 | 1.00 | 0.12 | 1.00 | 1.00 | 53.9s |
| 9 | mh2 | multi_hop_comparison | partial | 0.60 | 0.00 | 1.00 | 0.75 | 1.00 | 0.25 | 96.6s |
| 10 | mh3 | multi_hop_comparison | pass | 0.82 | 0.60 | 1.00 | 0.50 | 1.00 | 1.00 | 73.0s |
| 11 | mh4 | multi_hop_comparison | pass | 0.96 | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 69.6s |
| 12 | mh5 | multi_hop_comparison | pass | 0.84 | 0.71 | 1.00 | 1.00 | 1.00 | 0.50 | 78.7s |
| 13 | tf1 | temporal_freshness | partial | 0.76 | 0.80 | 1.00 | 0.50 | 1.00 | 0.50 | 57.7s |
| 14 | tf2 | temporal_freshness | partial | 0.78 | 0.00 | 1.00 | 0.88 | 1.00 | 1.00 | 48.1s |
| 15 | tf3 | temporal_freshness | partial | 0.40 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 5.6s |
| 16 | tf4 | temporal_freshness | pass | 0.95 | 1.00 | 1.00 | 0.75 | 1.00 | 1.00 | 46.6s |
| 17 | nr1 | numerical_reasoning | partial | 0.60 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 38.3s |
| 18 | nr2 | numerical_reasoning | pass | 0.88 | 0.67 | 1.00 | 0.75 | 1.00 | 1.00 | 63.7s |
| 19 | nr3 | numerical_reasoning | partial | 0.78 | 0.67 | 1.00 | 0.25 | 1.00 | 1.00 | 52.7s |
| 20 | amb1 | ambiguity | pass | 0.95 | 1.00 | 1.00 | 0.75 | 1.00 | 1.00 | 42.0s |
| 21 | amb2 | ambiguity | partial | 0.75 | 1.00 | 1.00 | 0.25 | 1.00 | 0.50 | 54.3s |
| 22 | amb3 | ambiguity | pass | 0.88 | 1.00 | 1.00 | 0.38 | 1.00 | 1.00 | 29.0s |
| 23 | ctr1 | contradiction | partial | 0.74 | 0.83 | 0.50 | 0.88 | 1.00 | 0.50 | 35.9s |
| 24 | ctr2 | contradiction | pass | 0.80 | 1.00 | 1.00 | 0.50 | 1.00 | 0.50 | 55.7s |
| 25 | ref1 | refusal_unknown | partial | 0.50 | 0.00 | 0.50 | 0.00 | 1.00 | 1.00 | 39.4s |
| 26 | ref2 | refusal_unknown | partial | 0.60 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 53.9s |
| 27 | niche1 | niche_long_tail | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 14.2s |
| 28 | niche2 | niche_long_tail | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 9.7s |
| 29 | pc1 | paraphrase_cache | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 8.0s |
| 30 | pc2 | paraphrase_cache | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 8.1s |

## Failure-mode distribution

| Mode | Count |
|---|---|
| wrong_route | 2 |
| retrieval_miss | 1 |
| hallucination | 1 |

*Generated 20260511T161015Z · WebLens Eval v7*