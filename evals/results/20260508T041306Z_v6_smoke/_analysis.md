# Web Search RAG Eval — V6_SMOKE
**Timestamp**: 20260508T041306Z  
**Questions**: question_v6_smoke.txt (5 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.580** |
| Pass | 1 (20%) |
| Partial | 3 |
| Fail | 1 |
| Avg M1 (factual) | 0.583 |
| Avg M3 (retrieval recall) | 0.573 |
| Avg latency | 52.8s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | single_simple | pass | 0.95 | 0.67 | 0.67 | 14.6s |
| 2 | cross_company_simple | fail | 0.15 | 0.75 | 0.50 | 31.2s |
| 3 | strict_refusal | partial | 0.60 | 0.40 | 0.60 | 91.5s |
| 4 | hybrid_web | partial | 0.60 | 0.50 | 0.50 | 70.9s |
| 5 | multi_part | partial | 0.60 | 0.60 | 0.60 | 55.9s |

## Decomposition

- Q2: decomposed into 2 sub-queries: ['Apple operating margin FY2024 from annual report (10-K) quarterly breakdown', 'Microsoft operating margin FY2024 from annual report (10-K) quarterly breakdown']
- Q3: decomposed into 3 sub-queries: ["What was Apple's total R&D spending in FY2024?", 'What specific patent categories did Apple file most in during FY2024?', 'What invention types (e.g., utility, design, provisional) did Apple pursue in FY2024 patents?']
- Q4: decomposed into 2 sub-queries: ['NVIDIA most recent quarterly revenue (fiscal year 2025 Q4 or latest reported quarter)', 'NVIDIA 10-K fiscal year 2024 or 2025 data center strategy description']
- Q5: decomposed into 2 sub-queries: ['NVIDIA FY2024 total revenue', 'NVIDIA FY2024 10-K primary risk factors disclosed']

*Generated 20260508T041306Z · Web Search RAG Eval Harness*