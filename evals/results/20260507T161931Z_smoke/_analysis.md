# Web Search RAG Eval — SMOKE
**Timestamp**: 20260507T161931Z  
**Questions**: question_v1_smoke.txt (2 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.810** |
| Pass | 1 (50%) |
| Partial | 1 |
| Fail | 0 |
| Avg M1 (factual) | 0.834 |
| Avg M3 (retrieval recall) | 0.916 |
| Avg latency | 27.0s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | simple_factual | partial | 0.67 | 0.67 | 0.83 | 28.5s |
| 2 | comparison | pass | 0.95 | 1.00 | 1.00 | 25.5s |

## Decomposition

- Q1: decomposed into 2 sub-queries: ['What is Reciprocal Rank Fusion (RRF)?', 'How does RRF combine ranked lists from multiple retrieval systems?']
- Q2: decomposed into 2 sub-queries: ['What are the key algorithmic differences and use cases for BM25 in text retrieval?', 'What are the key algorithmic differences and use cases for TF-IDF in text retrieval?']

*Generated 20260507T161931Z · Web Search RAG Eval Harness*