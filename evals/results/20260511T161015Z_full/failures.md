# Failure Analysis — FULL
*20260511T161015Z*

## Failure-mode distribution

- **wrong_route**: 2
- **retrieval_miss**: 1
- **hallucination**: 1

## Worst-scoring questions

### 1. `rs2` — routing_search_obvious — verdict=partial (agg=0.40)

**Question**: Who won the FIFA World Cup in 2022?

**Probable cause**: `wrong_route`

**Expected**: Specific recent result, must cite source even if LLM knows.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 0.50 (missed: ['Messi'])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Argentina won the FIFA World Cup in 2022, defeating France 4–2 on penalties after a 3–3 draw. It was Argentina's third World Cup title.

**Citations**: 0  · **Sub-queries**: ['Who won the FIFA World Cup in 2022?']

---

### 2. `tf3` — temporal_freshness — verdict=partial (agg=0.40)

**Question**: What were the major findings of NASA's most recent Mars rover or lander mission?

**Probable cause**: `retrieval_miss`

**Expected**: Should surface 2025-2026 mission findings (Perseverance, sample-return updates).

**Metrics**:

- Faithfulness: 0.00 — empty answer
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 0.00 (missed: ['Perseverance', 'Mars'])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: 

**Citations**: 0  · **Sub-queries**: ["What were the major findings of NASA's most recent Mars rover or lander mission?"]

---

### 3. `ref1` — refusal_unknown — verdict=partial (agg=0.50)

**Question**: What was OpenAI's exact net income in Q1 2026?

**Probable cause**: `hallucination`

**Expected**: OpenAI is privately held — exact net income is not public. Should say so.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 0.50
- Context Precision: 0.00 — No chunk contains OpenAI's Q1 2026 net income; all discuss other financial or operational details.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: **OpenAI’s Q1 2026 net income figure is not reported in any of the provided sources.** All cited sources discuss OpenAI’s revenue, funding rounds, and profitability outlook, but none disclose a specific net income number for Q1 2026.

Key relevant data from sources:
- **No Q1 2026 net income:** The sources focus on OpenAI’s annualized revenue ($25B as of Feb 2026 [2]), valuation ($852B post-money 

**Citations**: 3  · **Sub-queries**: ['OpenAI Q1 2026 net income exact figure']

---

### 4. `pc2` — paraphrase_cache — verdict=partial (agg=0.50)

**Question**: How does RRF work when combining multiple search results?

**Probable cause**: `wrong_route`

**Expected**: Paraphrase of pc1 — should hit cache when SEMANTIC_CACHE_ENABLED=true.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Reciprocal Rank Fusion (RRF) combines ranked lists from multiple search systems into a single result set. Each document receives a score equal to the sum of 1/(k + rank(d, i)) across all systems, where k is a constant (typically 60) and rank(d, i) is the position of document d in system i's results. Documents appearing in multiple lists with high ranks receive higher fused scores, effectively leve

**Citations**: 0  · **Sub-queries**: ['How does RRF work when combining multiple search results?']

---

### 5. `mh2` — multi_hop_comparison — verdict=partial (agg=0.60)

**Question**: Compare Real Madrid and Manchester City Champions League performance over the last 3 seasons.

**Probable cause**: `low_quality`

**Expected**: Per-club, per-season decomposition.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.75 — Chunks show match results and stats for both teams over recent seasons, enabling comparison.
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.25 (expected mode=search, actual=search, expected_count=multi:2-3, actual=6)

**Answer (first 400 chars)**: # Real Madrid vs Manchester City: Champions League Performance Over the Last 3 Seasons

Over the past three seasons (2023–24 to 2025–26), Real Madrid and Manchester City have followed sharply divergent trajectories in the UEFA Champions League. Real Madrid won the tournament in 2023–24, while Manchester City's deepest run was the quarter-finals that same season, with both clubs experiencing earlie

**Citations**: 13  · **Sub-queries**: ['Real Madrid Champions League results 2023-24 season', 'Real Madrid Champions League results 2024-25 season', 'Real Madrid Champions League results 2025-26 season', 'Manchester City Champions League results 2023-24 season', 'Manchester City Champions League results 2024-25 season', 'Manchester City Champions League results 2025-26 season']

---

### 6. `nr1` — numerical_reasoning — verdict=partial (agg=0.60)

**Question**: By what percentage did Apple's R&D spending change from FY2022 to FY2024?

**Probable cause**: `low_quality`

**Expected**: Should retrieve both years' R&D + compute the delta.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.00 — No chunk provides FY2022 or FY2024 R&D spending data needed for the percentage change.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=multi:2-3, actual=2)

**Answer (first 400 chars)**: Based on the provided sources, a precise percentage change in Apple’s total R&D spending from fiscal year 2022 to fiscal year 2024 **cannot be calculated** because neither a complete FY2022 nor a complete FY2024 figure is reported.

The available data shows that Apple’s quarterly R&D spending was in the **$6 billion range in 2022** [1], while in fiscal year 2024, Apple spent **$23.6 billion in the

**Citations**: 4  · **Sub-queries**: ['Apple R&D spending fiscal year 2022', 'Apple R&D spending fiscal year 2024']

---

### 7. `ref2` — refusal_unknown — verdict=partial (agg=0.60)

**Question**: What did the mayor of Tilamuk, Indonesia announce on Tuesday?

**Probable cause**: `low_quality`

**Expected**: Likely no English-language source — should admit not found cleanly.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.00 — No chunk mentions Tilamuk, Indonesia, or any mayor's announcement on Tuesday.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: No information found in the provided sources about a "Mayor of Tilamuk Indonesia" making any announcement on Tuesday, 2026-05-11.

- The sources only refer to **Tillamook, Oregon**, USA — not "Tilamuk, Indonesia" [1][2][3].
- The Tillamook City Council meets on the first and third Monday of each month; the mayor presides but votes only in tie situations [3].
- The only date mentioned near May 2026

**Citations**: 3  · **Sub-queries**: ['Mayor of Tilamuk Indonesia announcement Tuesday 2026-05-11']

---

### 8. `mh1` — multi_hop_comparison — verdict=partial (agg=0.62)

**Question**: Compare GPT-4o, Claude Opus 4.7, and Gemini 2.5 Pro on long-context handling and agentic tool use.

**Probable cause**: `low_quality`

**Expected**: Should decompose into per-model or per-dimension sub-queries.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.12 — Only chunk 5 mentions Claude Opus 4.7 and agentic tool use; others lack comparison of specified models.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=multi:2-3, actual=3)

**Answer (first 400 chars)**: # Comparing GPT-4o, Claude Opus 4.7, and Gemini 2.5 Pro on Long-Context Handling and Agentic Tool Use

These three models represent different tiers of capability in 2025, with Claude Opus 4.7 leading in agentic tool use and Gemini 2.5 Pro excelling in long-context handling, while GPT-4o serves primarily as a baseline for newer models.

## Long-Context Handling

| Model | Context Window | Key Bench

**Citations**: 8  · **Sub-queries**: ['GPT-4o long-context handling benchmark performance agentic tool use 2025', 'Claude Opus 4.7 long-context handling benchmark performance agentic tool use 2025', 'Gemini 2.5 Pro long-context handling benchmark performance agentic tool use 2025']

---

### 9. `ctr1` — contradiction — verdict=partial (agg=0.74)

**Question**: Is intermittent fasting effective for long-term weight loss?

**Probable cause**: `low_quality`

**Expected**: Should surface that evidence is mixed — some meta-analyses show modest benefit, others show equivalence to standard calorie restriction.

**Metrics**:

- Faithfulness: 0.83 — Most claims match chunks; only umbrella review mention lacks support.
- Context Recall: 0.50
- Context Precision: 0.88 — Most chunks directly discuss IF's effectiveness for weight loss; chunk 8 is a table of study info, not directly answerin
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.50 (expected mode=search, actual=search, expected_count=multi:2-3, actual=1)

**Answer (first 400 chars)**: **Inconsistent evidence for long-term superiority of intermittent fasting (IF) over controls**

**Overall efficacy vs. no intervention/regular diet**
- The 2026 Cochrane review (22 studies, ~2,000 participants) found that IF "may result in little to no difference in weight loss" compared to regular dietary advice, and likely makes little difference compared to no intervention [1][4].
- A 2023 meta

**Citations**: 5  · **Sub-queries**: ['Intermittent fasting effectiveness for long-term weight loss meta-analysis']

---

### 10. `amb2` — ambiguity — verdict=partial (agg=0.75)

**Question**: How did Q3 results look?

**Probable cause**: `low_quality`

**Expected**: Underspecified — which company / which Q3. Should ask or note ambiguity.

**Metrics**:

- Faithfulness: 1.00 — All claims are directly supported by the provided source chunks.
- Context Recall: 1.00
- Context Precision: 0.25 — Chunks 1 and 8 directly report Q3 financial results; others are general earnings context or unrelated.
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.50 (expected mode=search, actual=search, expected_count=single, actual=2)

**Answer (first 400 chars)**: # Q3 Results: Strong Earnings Growth Driven by Technology Sector

The Q3 2025 earnings season showed robust performance, with the S&P 500 on pace for **14% earnings growth**—the fourth consecutive quarter of double-digit expansion, well above the 7% estimate from September 30 [3]. While most data covers Q3 2025, some company-specific results (e.g., Viridien) provide concrete figures, and one sourc

**Citations**: 5  · **Sub-queries**: ['Most recent quarterly earnings results for Q3 2025 or Q3 2026', 'Q3 2025 earnings highlights and performance']

---
