# Web Search RAG Eval — FULL
**Timestamp**: 20260507T163920Z  
**Questions**: question_v1.txt (10 questions)

## Score Summary

| Metric | Value |
|--------|-------|
| Overall avg M7 score | **0.825** |
| Pass | 5 (50%) |
| Partial | 5 |
| Fail | 0 |
| Avg M1 (factual) | 0.903 |
| Avg M3 (retrieval recall) | 0.843 |
| Avg latency | 20.4s/Q |

## Per-Question Results

| # | Category | Verdict | M7 | M1 | M3 | Latency |
|---|----------|---------|-----|-----|-----|---------|
| 1 | simple_factual | pass | 1.00 | 1.00 | 0.80 | 17.3s |
| 2 | retrieval_comparison | pass | 0.95 | 1.00 | 1.00 | 28.7s |
| 3 | rag_architecture | partial | 0.65 | 0.80 | 0.60 | 22.5s |
| 4 | dense_vs_sparse | partial | 0.75 | 0.80 | 0.80 | 22.0s |
| 5 | cross_encoder | pass | 0.95 | 1.00 | 0.80 | 17.6s |
| 6 | pgvector | pass | 0.95 | 1.00 | 1.00 | 19.4s |
| 7 | chunking_strategies | partial | 0.65 | 0.80 | 0.80 | 19.3s |
| 8 | sentence_transformers | partial | 0.65 | 0.80 | 0.80 | 19.7s |
| 9 | hybrid_search | pass | 0.95 | 1.00 | 1.00 | 15.5s |
| 10 | ivfflat_hnsw | partial | 0.75 | 0.83 | 0.83 | 21.8s |

## Decomposition

- Q1: decomposed into 2 sub-queries: ['What is Reciprocal Rank Fusion (RRF)?', 'How does Reciprocal Rank Fusion combine ranked lists from multiple retrieval systems?']
- Q2: decomposed into 2 sub-queries: ['How does BM25 work for text retrieval and what are its key formulas?', 'How does TF-IDF work for text retrieval and what are its key formulas?']
- Q3: decomposed into 2 sub-queries: ['What are the key components of a Retrieval Augmented Generation (RAG) system?', 'How do the components in a Retrieval Augmented Generation (RAG) system work together?']
- Q4: decomposed into 3 sub-queries: ['How does dense retrieval represent documents and queries for information retrieval?', 'How does sparse retrieval represent documents and queries for information retrieval?', 'What scenarios or tasks does dense retrieval excel at?']
- Q5: decomposed into 2 sub-queries: ['What is cross-encoder reranking?', 'How does cross-encoder reranking improve retrieval quality compared to bi-encoders?']
- Q6: decomposed into 2 sub-queries: ['What is pgvector?', 'How is pgvector used to implement vector similarity search in PostgreSQL?']
- Q7: decomposed into 2 sub-queries: ['What are the main chunking strategies for RAG systems?', 'What are the trade-offs between different chunking strategies for RAG systems?']
- Q9: decomposed into 2 sub-queries: ['What is hybrid search in information retrieval?', 'Why does combining BM25 with vector search outperform either alone?']
- Q10: decomposed into 2 sub-queries: ['What are the accuracy, speed, and memory trade-offs of IVFFlat index for approximate nearest neighbor search?', 'What are the accuracy, speed, and memory trade-offs of HNSW index for approximate nearest neighbor search?']

*Generated 20260507T163920Z · Web Search RAG Eval Harness*