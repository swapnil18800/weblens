# Web Search RAG Eval — V6_SMOKE
**Timestamp**: 20260507T175645Z  
**Questions**: question_v6_smoke.txt (5 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.700** |
| Pass | 1 (20%) |
| Partial | 4 |
| Fail | 0 |
| Avg M1 (factual) | 0.533 |
| Avg M3 (retrieval recall) | 0.000 |
| Avg latency | 24.8s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | single_simple | pass | 0.95 | 0.67 | 0.00 | 23.2s |
| 2 | cross_company_simple | partial | 0.65 | 0.50 | 0.00 | 23.2s |
| 3 | strict_refusal | partial | 0.60 | 0.40 | 0.00 | 25.5s |
| 4 | hybrid_web | partial | 0.65 | 0.50 | 0.00 | 25.1s |
| 5 | multi_part | partial | 0.65 | 0.60 | 0.00 | 27.2s |

## Decomposition

- Q2: decomposed into 2 sub-queries: ["What is Apple's operating margin in FY2024 according to its annual filing?", "What is Microsoft's operating margin in FY2024 according to its annual filing?"]
- Q4: decomposed into 2 sub-queries: ["What was NVIDIA's most recent quarterly revenue?", "What does NVIDIA's latest 10-K say about data center strategy?"]
- Q5: decomposed into 2 sub-queries: ["What was NVIDIA's FY2024 total revenue?", 'What are the primary risk factors NVIDIA discloses in its 10-K?']

*Generated 20260507T175645Z · Web Search RAG Eval Harness*