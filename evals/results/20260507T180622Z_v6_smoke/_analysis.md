# Web Search RAG Eval — V6_SMOKE
**Timestamp**: 20260507T180622Z  
**Questions**: question_v6_smoke.txt (5 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.000** |
| Pass | 0 (0%) |
| Partial | 0 |
| Fail | 5 |
| Avg M1 (factual) | 0.000 |
| Avg M3 (retrieval recall) | 0.000 |
| Avg latency | 2.0s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | single_simple | fail | 0.00 | 0.00 | 0.00 | 3.5s |
| 2 | cross_company_simple | fail | 0.00 | 0.00 | 0.00 | 1.7s |
| 3 | strict_refusal | fail | 0.00 | 0.00 | 0.00 | 1.6s |
| 4 | hybrid_web | fail | 0.00 | 0.00 | 0.00 | 1.9s |
| 5 | multi_part | fail | 0.00 | 0.00 | 0.00 | 1.5s |

## Decomposition

- All questions used single sub-query (no decomposition triggered)

*Generated 20260507T180622Z · Web Search RAG Eval Harness*