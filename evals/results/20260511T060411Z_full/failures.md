# Failure Analysis — FULL
*20260511T060411Z*

## Failure-mode distribution

- **wrong_route**: 4
- **under_decomposition**: 2
- **hallucination**: 1

## Worst-scoring questions

### 1. `mh2` — multi_hop_comparison — verdict=fail (agg=0.30)

**Question**: Compare Real Madrid and Manchester City Champions League performance over the last 3 seasons.

**Probable cause**: `under_decomposition`

**Expected**: Per-club, per-season decomposition.

**Metrics**:

- Faithfulness: 0.00 — empty answer
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 0.00 (missed: ['Champions League', 'Real Madrid', 'Manchester City'])
- Routing: 0.50 (expected mode=search, actual=search, expected_count=multi:2-3, actual=1)

**Answer (first 400 chars)**: 

**Citations**: 0  · **Sub-queries**: ['Compare Real Madrid and Manchester City Champions League performance over the last 3 seasons.']

---

### 2. `niche1` — niche_long_tail — verdict=partial (agg=0.50)

**Question**: Who is Faramir's older brother in J.R.R. Tolkien's The Lord of the Rings?

**Probable cause**: `wrong_route`

**Expected**: Specific lore — answer Boromir; one chunk should suffice.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Boromir is Faramir's older brother. They are the sons of Denethor, the Steward of Gondor. Boromir appears prominently in *The Fellowship of the Ring* and dies protecting Merry and Pippin.

**Citations**: 0  · **Sub-queries**: ["Who is Faramir's older brother in J.R.R. Tolkien's The Lord of the Rings?"]

---

### 3. `niche2` — niche_long_tail — verdict=partial (agg=0.50)

**Question**: What is the half-life of carbon-14, and how is it used in radiometric dating?

**Probable cause**: `wrong_route`

**Expected**: Specific factual question with a precise number.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: The half-life of carbon-14 is about 5,730 years. In radiometric dating, the steady decay of carbon-14 in organic remains is used: while alive, organisms absorb carbon-14 from the atmosphere at a constant rate; after death, the absorbed carbon-14 decays without replenishment. By measuring the remaining carbon-14 and comparing it to the initial atmospheric level, scientists can calculate the time el

**Citations**: 0  · **Sub-queries**: ['What is the half-life of carbon-14, and how is it used in radiometric dating?']

---

### 4. `pc1` — paraphrase_cache — verdict=partial (agg=0.50)

**Question**: What is Reciprocal Rank Fusion in retrieval?

**Probable cause**: `wrong_route`

**Expected**: Standard RAG concept — first query primes the cache.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Reciprocal Rank Fusion (RRF) is a method for combining multiple ranked result lists into a single ranking. Each document gets a score by summing 1/(k + rank) across all lists, where k is a constant (often 60). RRF is simple, effective, and does not require training or relevance scores.

**Citations**: 0  · **Sub-queries**: ['What is Reciprocal Rank Fusion in retrieval?']

---

### 5. `pc2` — paraphrase_cache — verdict=partial (agg=0.50)

**Question**: How does RRF work when combining multiple search results?

**Probable cause**: `wrong_route`

**Expected**: Paraphrase of pc1 — should hit cache when SEMANTIC_CACHE_ENABLED=true.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Reciprocal Rank Fusion (RRF) combines ranked lists from multiple search systems by assigning a score to each document based on the reciprocal of its rank: score(d) = Σ 1 / (k + rank_i(d)), where k is a constant (typically 60). Documents are then sorted by descending total score. RRF is a simple, effective fusion method that requires no training and works with heterogeneous rankers.

**Citations**: 0  · **Sub-queries**: ['How does RRF work when combining multiple search results?']

---

### 6. `ref1` — refusal_unknown — verdict=partial (agg=0.53)

**Question**: What was OpenAI's exact net income in Q1 2026?

**Probable cause**: `hallucination`

**Expected**: OpenAI is privately held — exact net income is not public. Should say so.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.12 — Only chunk 5 states OpenAI has not disclosed actual Q1 2026 net income, directly addressing the question.
- Answer Correctness: 0.50 (missed: ['private'])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: **No Q1 2026 net income data available in sources.** OpenAI has not yet disclosed actual Q1 2026 net income figures in any of the provided materials [1][2]. The company remains unprofitable despite rapid revenue growth — it **does not yet generate a profit** [2].

**What is known about OpenAI’s Q1 2026 financial position:**

- **Revenue trajectory**: OpenAI projects **$29.4 billion total revenue f

**Citations**: 2  · **Sub-queries**: ['OpenAI net income Q1 2026 financial results']

---

### 7. `mh5` — multi_hop_comparison — verdict=partial (agg=0.53)

**Question**: How do the US, EU, and China approach AI regulation in 2025-2026, and where do they disagree most?

**Probable cause**: `under_decomposition`

**Expected**: Decompose by jurisdiction; identify points of divergence.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.75 — Chunks cover US AI regulation in 2025-2026; missing EU and China for full comparison.
- Answer Correctness: 0.67 (missed: ['United States'])
- Routing: 0.25 (expected mode=search, actual=search, expected_count=multi:2-3, actual=5)

**Answer (first 400 chars)**: # How Do the US, EU, and China Approach AI Regulation in 2025–2026, and Where Do They Disagree Most?

By 2025–2026, the US, EU, and China have each institutionalized divergent AI regulatory models—reflecting fundamentally different philosophies on risk, rights, and state control. Their sharpest disagreements center on **regulatory scope, enforcement approach, and the balance between innovation and

**Citations**: 17  · **Sub-queries**: ['US AI regulation policy 2025-2026 executive actions and federal framework', 'EU AI Act implementation 2025-2026 and regulatory approach', 'China AI regulation policy 2025-2026 governance and data rules', 'Key disagreements between US EU and China AI regulation', 'Recent US vs EU vs China AI policy differences 2025 2026']

---

### 8. `rs2` — routing_search_obvious — verdict=partial (agg=0.60)

**Question**: Who won the FIFA World Cup in 2022?

**Probable cause**: `low_quality`

**Expected**: Specific recent result, must cite source even if LLM knows.

**Metrics**:

- Faithfulness: 0.80 — Chunks support winner, final, host, and dates; not the favorites claim.
- Context Recall: 0.50
- Context Precision: 0.20 — Only chunk 1 mentions the 2022 World Cup outcome, but does not explicitly state the winner.
- Answer Correctness: 0.50 (missed: ['Messi'])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: The winner of the **2022 FIFA World Cup** was **Argentina**. Argentina defeated France in the final match, securing its third World Cup victory [1]. The tournament was held in Qatar from November 20 to December 18, 2022, and was contested by 32 national teams [1]. This was the first World Cup hosted in the Middle East, with Qatar awarded the hosting rights in 2010 [1]. Argentina entered the tourna

**Citations**: 1  · **Sub-queries**: ['FIFA World Cup 2022 winner']

---

### 9. `mh1` — multi_hop_comparison — verdict=partial (agg=0.60)

**Question**: Compare GPT-4o, Claude Opus 4.7, and Gemini 2.5 Pro on long-context handling and agentic tool use.

**Probable cause**: `low_quality`

**Expected**: Should decompose into per-model or per-dimension sub-queries.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.00 — All chunks only discuss GPT-4o, not Claude Opus 4.7 or Gemini 2.5 Pro, and lack comparison.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=multi:2-3, actual=3)

**Answer (first 400 chars)**: GPT-4o, Claude Opus 4.7, and Gemini 2.5 Pro each offer distinct strengths in long-context processing and agentic tool use, with Gemini leading in raw context capacity and native tool integration, Opus 4.7 excelling in production-grade agentic coding, and GPT-4o prioritizing multimodal real-time interaction.

## Long-Context Handling

The models differ significantly in context window size and pract

**Citations**: 9  · **Sub-queries**: ['GPT-4o long-context handling and agentic tool use capabilities', 'Claude Opus 4.7 long-context handling and agentic tool use capabilities', 'Gemini 2.5 Pro long-context handling and agentic tool use capabilities']

---

### 10. `tf4` — temporal_freshness — verdict=partial (agg=0.60)

**Question**: What's the latest status of the EU AI Act's high-risk AI provisions implementation?

**Probable cause**: `low_quality`

**Expected**: Should reflect 2025-2026 phased rollout status.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.50 — Chunks 1-4 discuss high-risk AI deadlines and implementation status; others are off-topic.
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.50 (expected mode=search, actual=search, expected_count=single, actual=2)

**Answer (first 400 chars)**: # EU AI Act High-Risk Provisions: Implementation Status as of May 2026

The EU AI Act's high-risk AI provisions are **not yet fully in force**, and a newly agreed provisional delay in May 2026 has reshaped the compliance timeline. While the original schedule set key deadlines for August 2026, legislative negotiations and standards development delays have created ongoing uncertainty for regulated e

**Citations**: 7  · **Sub-queries**: ['Current implementation status of EU AI Act high-risk AI provisions as of May 2026', 'EU AI Act high-risk classification and compliance timeline updates']

---
