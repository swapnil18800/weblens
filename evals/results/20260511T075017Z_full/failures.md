# Failure Analysis — FULL
*20260511T075017Z*

## Failure-mode distribution

- **wrong_route**: 5
- **under_decomposition**: 1
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

**Answer (first 400 chars)**: Argentina won the FIFA World Cup in 2022, defeating France in the final on penalty kicks after a 3–3 draw.

**Citations**: 0  · **Sub-queries**: ['Who won the FIFA World Cup in 2022?']

---

### 2. `ref1` — refusal_unknown — verdict=partial (agg=0.40)

**Question**: What was OpenAI's exact net income in Q1 2026?

**Probable cause**: `hallucination`

**Expected**: OpenAI is privately held — exact net income is not public. Should say so.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 0.50
- Context Precision: 0.00 — No chunk provides OpenAI's exact net income for Q1 2026.
- Answer Correctness: 0.50 (missed: ['private'])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: **OpenAI has not publicly disclosed its Q1 2026 net income.** The available sources provide revenue estimates and projections, but no net income (profit) figure for Q1 2026 is reported.

Key financial indicators from the sources:
- **Revenue run-rate**: Sacra estimates OpenAI hit $25B in *annualized* revenue by February 2026, up from $20B at end of 2025 [2]. A separate source projects Q1 2026 reve

**Citations**: 3  · **Sub-queries**: ['OpenAI net income Q1 2026']

---

### 3. `mh1` — multi_hop_comparison — verdict=partial (agg=0.45)

**Question**: Compare GPT-4o, Claude Opus 4.7, and Gemini 2.5 Pro on long-context handling and agentic tool use.

**Probable cause**: `under_decomposition`

**Expected**: Should decompose into per-model or per-dimension sub-queries.

**Metrics**:

- Faithfulness: 0.00 — Answer discusses GPT-4o, Claude, Gemini; chunks only cover GPT-4.1, not these models.
- Context Recall: 1.00
- Context Precision: 0.00 — All chunks discuss GPT-4.1 or benchmarks, not GPT-4o, Claude Opus 4.7, or Gemini 2.5 Pro.
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.25 (expected mode=search, actual=search, expected_count=multi:2-3, actual=6)

**Answer (first 400 chars)**: # Comparing GPT-4o, Claude Opus 4.7, and Gemini 2.5 Pro: Long-Context Handling and Agentic Tool Use

These three frontier models take markedly different approaches to long-context processing and agentic capabilities. Claude Opus 4.7 and Gemini 2.5 Pro offer million-token contexts with strong agentic features, while GPT-4o operates at a smaller context window but emphasizes multimodal speed.

## Lo

**Citations**: 14  · **Sub-queries**: ['GPT-4o long-context handling benchmark results', 'GPT-4o agentic tool use capabilities', 'Claude Opus 4.7 long-context handling performance', 'Claude Opus 4.7 agentic tool use capabilities', 'Gemini 2.5 Pro long-context handling evaluation', 'Gemini 2.5 Pro agentic tool use capabilities']

---

### 4. `ctr2` — contradiction — verdict=partial (agg=0.50)

**Question**: Did Christopher Columbus prove the Earth was round?

**Probable cause**: `wrong_route`

**Expected**: Common misconception — should surface that educated people knew the Earth was round centuries before Columbus.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: No. Educated Europeans in Columbus's time already knew Earth was spherical; that fact had been established by ancient Greeks, supported by figures like Eratosthenes. Columbus's voyages did not prove roundness — they explored a westward route to Asia. The myth that he faced a flat-Earth opposition was popularized by 19th-century writers.

**Citations**: 0  · **Sub-queries**: ['Did Christopher Columbus prove the Earth was round?']

---

### 5. `niche1` — niche_long_tail — verdict=partial (agg=0.50)

**Question**: Who is Faramir's older brother in J.R.R. Tolkien's The Lord of the Rings?

**Probable cause**: `wrong_route`

**Expected**: Specific lore — answer Boromir; one chunk should suffice.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Boromir.

**Citations**: 0  · **Sub-queries**: ["Who is Faramir's older brother in J.R.R. Tolkien's The Lord of the Rings?"]

---

### 6. `niche2` — niche_long_tail — verdict=partial (agg=0.50)

**Question**: What is the half-life of carbon-14, and how is it used in radiometric dating?

**Probable cause**: `wrong_route`

**Expected**: Specific factual question with a precise number.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: The half-life of carbon-14 is about 5,730 years. In radiometric dating, it is used to estimate the age of organic materials (up to ~50,000 years old) by measuring the remaining ratio of carbon-14 to stable carbon-12. Since living organisms constantly absorb carbon-14, the decay after death provides a clock for determining when the organism died.

**Citations**: 0  · **Sub-queries**: ['What is the half-life of carbon-14, and how is it used in radiometric dating?']

---

### 7. `pc1` — paraphrase_cache — verdict=partial (agg=0.50)

**Question**: What is Reciprocal Rank Fusion in retrieval?

**Probable cause**: `wrong_route`

**Expected**: Standard RAG concept — first query primes the cache.

**Metrics**:

- Faithfulness: 0.50 — no chunks
- Context Recall: 0.00
- Context Precision: 1.00 — no chunks
- Answer Correctness: 1.00 (missed: [])
- Routing: 0.00 (expected mode=search, actual=parametric, expected_count=single, actual=1)

**Answer (first 400 chars)**: Reciprocal Rank Fusion (RRF) is a method for combining multiple ranked lists into a single result set. Each document's score is calculated as the sum of reciprocal ranks (1 / (k + rank)) across all lists, where k is a constant (typically 60). It is simple, effective, and requires no training, making it popular in information retrieval tasks.

**Citations**: 0  · **Sub-queries**: ['What is Reciprocal Rank Fusion in retrieval?']

---

### 8. `nr1` — numerical_reasoning — verdict=partial (agg=0.60)

**Question**: By what percentage did Apple's R&D spending change from FY2022 to FY2024?

**Probable cause**: `low_quality`

**Expected**: Should retrieve both years' R&D + compute the delta.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.00 — No chunk provides R&D spending for FY2022 or FY2024 to calculate percentage change.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=multi:2-3, actual=2)

**Answer (first 400 chars)**: Based solely on the provided sources, the percentage change in Apple's R&D spending from FY2022 to FY2024 **cannot be calculated**. The sources do not report exact figures for either fiscal year.

## Missing Data

- **FY2022 Spending:** Not directly reported. Sources only mention that spending "steadily climbed from roughly the $6 billion range in 2022" [1], which is a vague quarterly reference, n

**Citations**: 3  · **Sub-queries**: ['Apple R&D spending for fiscal year 2022', 'Apple R&D spending for fiscal year 2024']

---

### 9. `ref2` — refusal_unknown — verdict=partial (agg=0.60)

**Question**: What did the mayor of Tilamuk, Indonesia announce on Tuesday?

**Probable cause**: `low_quality`

**Expected**: Likely no English-language source — should admit not found cleanly.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.00 — No chunk mentions Tilamuk, Indonesia, or any mayor's announcement on Tuesday.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: **No announcement of a Tilamuk Indonesia mayor announcement on either date has been found in the provided sources.**

The sources cover a range of events on **Tuesday, 5 May 2026** — including an Indonesia vs. China U17 football match [2], a magnitude 3.3 earthquake south of Java, Indonesia [4], and a Montreal news digest [1] — but none mention a mayoral announcement in Tilamuk.

For **Tuesday, 12

**Citations**: 5  · **Sub-queries**: ['Tilamuk Indonesia mayor announcement Tuesday 2026-05-05 or 2026-05-12']

---

### 10. `rs3` — routing_search_obvious — verdict=partial (agg=0.70)

**Question**: What's the latest Anthropic Claude model as of mid-2026?

**Probable cause**: `low_quality`

**Expected**: Recent product release — must search; LLM may not know cutoff.

**Metrics**:

- Faithfulness: 0.00 — refusal
- Context Recall: 1.00
- Context Precision: 0.50 — Chunks 1-3 and 8 mention Claude 4 or Opus 4.6, directly answering the latest model as of mid-2026.
- Answer Correctness: 1.00 (missed: [])
- Routing: 1.00 (expected mode=search, actual=search, expected_count=single, actual=1)

**Answer (first 400 chars)**: As of mid-2026, Anthropic’s latest Claude models are **Claude Opus 4.6** and **Claude Sonnet 4.6**, part of the Claude 4 family [2][3].

**Claude Opus 4.6** (Anthropic’s most capable model)
- Launched **February 5, 2026** [2]
- 1 million token context window [2][3]
- 128K max output tokens [2]
- 78.3% on MRCR v2 at 1M tokens [2]
- 14.5-hour task completion window [2]
- API pricing: **$5/1M input t

**Citations**: 2  · **Sub-queries**: ['Anthropic Claude latest model available mid-2026']

---
