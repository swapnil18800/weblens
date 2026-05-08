# Web Search RAG Eval — V6
**Timestamp**: 20260507T181845Z  
**Questions**: question_v6.txt (15 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.393** |
| Pass | 1 (6%) |
| Partial | 6 |
| Fail | 8 |
| Avg M1 (factual) | 0.510 |
| Avg M3 (retrieval recall) | 0.687 |
| Avg latency | 40.4s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | year_scoped | fail | 0.20 | 0.75 | 0.75 | 31.2s |
| 2 | year_scoped | partial | 0.50 | 0.50 | 0.75 | 23.7s |
| 3 | cross_company_quant | partial | 0.65 | 0.60 | 0.60 | 75.3s |
| 4 | cross_company_quant | fail | 0.20 | 0.80 | 0.80 | 22.3s |
| 5 | multi_year_trend | partial | 0.60 | 0.60 | 0.60 | 55.8s |
| 6 | multi_year_trend | partial | 0.65 | 0.60 | 0.80 | 49.9s |
| 7 | transcript_grounding | fail | 0.00 | 0.00 | 0.80 | 38.6s |
| 8 | transcript_grounding | fail | 0.25 | 0.40 | 0.60 | 25.4s |
| 9 | strict_rag_hard | pass | 0.85 | 0.80 | 0.80 | 22.2s |
| 10 | strict_rag_hard | fail | 0.20 | 0.40 | 1.00 | 15.0s |
| 11 | hybrid_dual | partial | 0.60 | 0.60 | 0.80 | 68.6s |
| 12 | hybrid_dual | fail | 0.20 | 0.20 | 0.40 | 69.6s |
| 13 | multi_hop_ratio | partial | 0.60 | 0.60 | 0.80 | 54.7s |
| 14 | gap_fill_trigger | fail | 0.20 | 0.40 | 0.40 | 33.3s |
| 15 | private_company_gap | fail | 0.20 | 0.40 | 0.40 | 21.0s |

## Decomposition

- Q3: decomposed into 3 sub-queries: ['AMD Data Center segment revenue FY2024 annual report', 'Intel Data Center and AI (DCAI) segment revenue FY2024 annual report', 'NVIDIA Data Center segment revenue FY2024 annual report']
- Q5: decomposed into 3 sub-queries: ['Meta Reality Labs operating loss FY2022 annual figures', 'Meta Reality Labs operating loss FY2023 annual figures', 'Meta Reality Labs operating loss FY2024 annual figures']
- Q6: decomposed into 2 sub-queries: ['Microsoft Intelligent Cloud segment revenue FY2022 FY2023 FY2024 annual', 'Microsoft Intelligent Cloud segment year-over-year growth rates FY2023 FY2024']
- Q7: decomposed into 2 sub-queries: ['What did Microsoft management say about Azure growth deceleration in FY2024 Q3 earnings call?', 'What did Microsoft management say about Azure growth deceleration in FY2024 Q4 earnings call?']
- Q11: decomposed into 2 sub-queries: ["What did NVIDIA's most recent 10-K say about AI accelerator competition?", 'What 2025-2026 news exists about export controls affecting NVIDIA?']
- Q12: decomposed into 2 sub-queries: ['Microsoft FY2024 10-K annual report AI strategy disclosures and competitive risks', 'Microsoft Copilot enterprise adoption trends and business impact 2025 to 2026']
- Q13: decomposed into 2 sub-queries: ['Apple R&D expense and revenue FY2023 FY2024 10-K', 'Meta R&D expense and revenue FY2023 FY2024 10-K']

*Generated 20260507T181845Z · Web Search RAG Eval Harness*