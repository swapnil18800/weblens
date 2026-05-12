# WebLens Eval Report — FULL
**Timestamp**: 20260511T060411Z  
**Bench version**: v7-bench-1

## Score Summary

| Metric | Value |
|---|---|
| **Aggregate (mean of 5 core)** | **0.718** |
| Faithfulness | 0.606 |
| Context Recall | 0.806 |
| Context Precision | 0.542 |
| Answer Correctness | 0.911 |
| Routing & Decomposition | 0.725 |
| Answer Relevancy (diagnostic) | 0.659 |

**Verdicts**: ✅ 9 pass · ⚠️ 20 partial · ❌ 1 fail (of 30)  
**Latency**: avg 43.58s · p95 85.08s  
**Judge cost**: $0.0000 total

## Mode Distribution (actual routing)

| Mode | Count |
|---|---|
| parametric | 8 |
| search | 22 |

## Per-Category Breakdown

| Category | N | Avg | Pass | Partial | Fail |
|---|---|---|---|---|---|
| ambiguity | 3 | 0.713 | 0 | 3 | 0 |
| contradiction | 2 | 0.871 | 1 | 1 | 0 |
| multi_hop_comparison | 5 | 0.590 | 0 | 4 | 1 |
| niche_long_tail | 2 | 0.500 | 0 | 2 | 0 |
| numerical_reasoning | 3 | 0.764 | 1 | 2 | 0 |
| paraphrase_cache | 2 | 0.500 | 0 | 2 | 0 |
| refusal_unknown | 2 | 0.562 | 0 | 2 | 0 |
| routing_parametric | 4 | 1.000 | 4 | 0 | 0 |
| routing_search_obvious | 3 | 0.744 | 1 | 2 | 0 |
| temporal_freshness | 4 | 0.765 | 2 | 2 | 0 |

## Per-Question Results

| # | ID | Category | Verdict | Agg | Faith | C-Rec | C-Prec | Correct | Route | Lat |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | p1 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 6.5s |
| 2 | p2 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 13.8s |
| 3 | p3 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 4.7s |
| 4 | p4 | routing_parametric | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 12.5s |
| 5 | rs1 | routing_search_obvious | partial | 0.78 | 0.75 | 1.00 | 0.17 | 1.00 | 1.00 | 31.1s |
| 6 | rs2 | routing_search_obvious | partial | 0.60 | 0.80 | 0.50 | 0.20 | 0.50 | 1.00 | 33.3s |
| 7 | rs3 | routing_search_obvious | pass | 0.85 | 1.00 | 1.00 | 0.25 | 1.00 | 1.00 | 42.9s |
| 8 | mh1 | multi_hop_comparison | partial | 0.60 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 65.7s |
| 9 | mh2 | multi_hop_comparison | fail | 0.30 | 0.00 | 0.00 | 1.00 | 0.00 | 0.50 | 5.4s |
| 10 | mh3 | multi_hop_comparison | partial | 0.76 | 0.40 | 1.00 | 0.38 | 1.00 | 1.00 | 86.5s |
| 11 | mh4 | multi_hop_comparison | partial | 0.76 | 0.80 | 1.00 | 0.50 | 1.00 | 0.50 | 83.6s |
| 12 | mh5 | multi_hop_comparison | partial | 0.53 | 0.00 | 1.00 | 0.75 | 0.67 | 0.25 | 76.3s |
| 13 | tf1 | temporal_freshness | partial | 0.73 | 0.80 | 1.00 | 0.38 | 1.00 | 0.50 | 85.1s |
| 14 | tf2 | temporal_freshness | pass | 0.87 | 0.83 | 1.00 | 0.50 | 1.00 | 1.00 | 43.3s |
| 15 | tf3 | temporal_freshness | pass | 0.86 | 0.80 | 1.00 | 0.50 | 1.00 | 1.00 | 43.3s |
| 16 | tf4 | temporal_freshness | partial | 0.60 | 0.00 | 1.00 | 0.50 | 1.00 | 0.50 | 60.0s |
| 17 | nr1 | numerical_reasoning | partial | 0.77 | 0.83 | 1.00 | 0.00 | 1.00 | 1.00 | 56.2s |
| 18 | nr2 | numerical_reasoning | partial | 0.72 | 0.50 | 1.00 | 0.12 | 1.00 | 1.00 | 71.9s |
| 19 | nr3 | numerical_reasoning | pass | 0.80 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 60.4s |
| 20 | amb1 | ambiguity | partial | 0.79 | 0.83 | 1.00 | 0.62 | 1.00 | 0.50 | 59.0s |
| 21 | amb2 | ambiguity | partial | 0.72 | 0.83 | 1.00 | 0.25 | 1.00 | 0.50 | 63.9s |
| 22 | amb3 | ambiguity | partial | 0.63 | 0.00 | 1.00 | 0.14 | 1.00 | 1.00 | 34.1s |
| 23 | ctr1 | contradiction | pass | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 82.6s |
| 24 | ctr2 | contradiction | partial | 0.74 | 1.00 | 0.67 | 0.88 | 0.67 | 0.50 | 85.7s |
| 25 | ref1 | refusal_unknown | partial | 0.53 | 0.00 | 1.00 | 0.12 | 0.50 | 1.00 | 35.4s |
| 26 | ref2 | refusal_unknown | partial | 0.60 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 28.3s |
| 27 | niche1 | niche_long_tail | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 5.3s |
| 28 | niche2 | niche_long_tail | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 6.3s |
| 29 | pc1 | paraphrase_cache | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 10.0s |
| 30 | pc2 | paraphrase_cache | partial | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 | 0.00 | 14.2s |

## Failure-mode distribution

| Mode | Count |
|---|---|
| wrong_route | 4 |
| under_decomposition | 2 |
| hallucination | 1 |

*Generated 20260511T060411Z · WebLens Eval v7*