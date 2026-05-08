# Web Search RAG Eval — V6_SMOKE
**Timestamp**: 20260507T181518Z  
**Questions**: question_v6_smoke.txt (5 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.470** |
| Pass | 1 (20%) |
| Partial | 1 |
| Fail | 3 |
| Avg M1 (factual) | 0.467 |
| Avg M3 (retrieval recall) | 0.583 |
| Avg latency | 37.0s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | single_simple | pass | 0.90 | 0.33 | 0.67 | 11.4s |
| 2 | cross_company_simple | fail | 0.35 | 0.75 | 0.75 | 46.6s |
| 3 | strict_refusal | fail | 0.20 | 0.40 | 0.40 | 20.6s |
| 4 | hybrid_web | fail | 0.25 | 0.25 | 0.50 | 62.4s |
| 5 | multi_part | partial | 0.65 | 0.60 | 0.60 | 44.2s |

## Decomposition

- Q2: decomposed into 2 sub-queries: ['Apple operating margin FY2024 based on annual filing (10-K)', 'Microsoft operating margin FY2024 based on annual filing (10-K)']
- Q4: decomposed into 2 sub-queries: ["What was NVIDIA's most recent quarterly revenue?", "What does NVIDIA's latest 10-K say about their data center strategy?"]
- Q5: decomposed into 2 sub-queries: ['NVIDIA FY2024 total revenue', 'NVIDIA primary risk factors disclosed in 10-K']

*Generated 20260507T181518Z · Web Search RAG Eval Harness*