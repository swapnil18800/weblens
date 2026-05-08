# Web Search RAG Eval — FULL
**Timestamp**: 20260507T163245Z  
**Questions**: question_v1.txt (10 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.785** |
| Pass | 4 (40%) |
| Partial | 6 |
| Fail | 0 |
| Avg M1 (factual) | 0.827 |
| Avg M3 (retrieval recall) | 0.823 |
| Avg latency | 19.9s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | simple_factual | partial | 0.75 | 0.80 | 1.00 | 16.2s |
| 2 | retrieval_comparison | pass | 0.95 | 1.00 | 1.00 | 22.1s |
| 3 | rag_architecture | partial | 0.55 | 0.40 | 0.20 | 19.6s |
| 4 | dense_vs_sparse | partial | 0.75 | 0.80 | 0.80 | 24.1s |
| 5 | cross_encoder | pass | 0.95 | 1.00 | 0.80 | 25.4s |
| 6 | pgvector | pass | 0.95 | 1.00 | 1.00 | 18.3s |
| 7 | chunking_strategies | partial | 0.65 | 0.80 | 0.80 | 20.9s |
| 8 | sentence_transformers | partial | 0.65 | 0.80 | 0.80 | 18.0s |
| 9 | hybrid_search | pass | 1.00 | 1.00 | 1.00 | 15.9s |
| 10 | ivfflat_hnsw | partial | 0.65 | 0.67 | 0.83 | 18.8s |

## Decomposition

- Q1: decomposed into 2 sub-queries: ['What is Reciprocal Rank Fusion (RRF)?', 'How does RRF combine ranked lists from multiple retrieval systems?']
- Q2: decomposed into 3 sub-queries: ['What are the key algorithmic differences between BM25 and TF-IDF for text retrieval?', 'When should you prefer BM25 over TF-IDF for text retrieval?', 'When should you prefer TF-IDF over BM25 for text retrieval?']
- Q3: decomposed into 2 sub-queries: ['What are the key components of a Retrieval Augmented Generation (RAG) system?', 'How do the components of a Retrieval Augmented Generation (RAG) system work together?']
- Q4: decomposed into 3 sub-queries: ['How does dense retrieval represent information in information retrieval?', 'How does sparse retrieval represent information in information retrieval?', 'In which scenarios does dense retrieval excel compared to sparse retrieval?']
- Q5: decomposed into 3 sub-queries: ['What is cross-encoder reranking?', 'What is a bi-encoder in information retrieval?', 'How does cross-encoder reranking improve retrieval quality compared to bi-encoders?']
- Q6: decomposed into 2 sub-queries: ['What is pgvector?', 'How is pgvector used to implement vector similarity search in PostgreSQL?']
- Q7: decomposed into 2 sub-queries: ['What are the main chunking strategies for RAG systems?', 'What are the trade-offs between different chunking strategies in RAG systems?']
- Q9: decomposed into 2 sub-queries: ['What is hybrid search in information retrieval?', 'Why does combining BM25 with vector search outperform either alone?']
- Q10: decomposed into 2 sub-queries: ['What are the accuracy, speed, and memory trade-offs of IVFFlat index for approximate nearest neighbor search?', 'What are the accuracy, speed, and memory trade-offs of HNSW index for approximate nearest neighbor search?']

*Generated 20260507T163245Z · Web Search RAG Eval Harness*