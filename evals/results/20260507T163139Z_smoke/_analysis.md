# Web Search RAG Eval — SMOKE
**Timestamp**: 20260507T163139Z  
**Questions**: question_v1_smoke.txt (2 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.810** |
| Pass | 1 (50%) |
| Partial | 1 |
| Fail | 0 |
| Avg M1 (factual) | 0.834 |
| Avg M3 (retrieval recall) | 0.834 |
| Avg latency | 24.4s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | simple_factual | partial | 0.67 | 0.67 | 0.67 | 17.9s |
| 2 | comparison | pass | 0.95 | 1.00 | 1.00 | 31.0s |

## Decomposition

- Q1: decomposed into 2 sub-queries: ['What is Reciprocal Rank Fusion (RRF)?', 'How does Reciprocal Rank Fusion combine ranked lists from multiple retrieval systems?']
- Q2: decomposed into 3 sub-queries: ['How does BM25 work for text retrieval? What are its key algorithmic components?', 'How does TF-IDF work for text retrieval? What are its key algorithmic components?', 'When should you prefer BM25 instead of TF-IDF for text retrieval?']

*Generated 20260507T163139Z · Web Search RAG Eval Harness*