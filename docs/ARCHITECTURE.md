# WebLens Architecture

## System Overview

WebLens is a full-stack web-search RAG system designed for accuracy through complete page extraction and intelligent retrieval ranking. The architecture emphasizes directness—each pipeline stage is a standalone module with minimal abstraction.

## High-Level Flow

```mermaid
graph LR
    A["🖥️ Frontend"] -->|SSE| B["🔄 FastAPI<br/>Backend"]
    B -->|Stream| A
    B -->|Async| C["🔍 Pipeline<br/>8 Stages"]
    C -->|Query| D["Tavily<br/>API"]
    C -->|Extract| E["Jina Reader<br/>+ trafilatura"]
    C -->|Embed & Rank| F["🗄️ Supabase<br/>pgvector"]
    C -->|LLM| G["DeepSeek V3<br/>+ OpenAI"]
```

## Pipeline Architecture

```mermaid
graph TD
    A["📤 User Query"] --> B["⚙️ Stage 1:<br/>Query Decomposition"]
    B -->|Is simple?| C["✓ Fast Path<br/>One query"]
    B -->|Is complex?| D["LLM Decompose<br/>Multiple sub-queries"]
    C --> E["Stage 2: URL Discovery<br/>Tavily API"]
    D --> E
    E -->|URLs| F["Stage 3:<br/>Full-Page Extraction<br/>Jina Reader"]
    F -->|Fallback| G["trafilatura"]
    F -->|Pages| H["Stage 4:<br/>Intelligent Chunking<br/>Heading-aware"]
    H -->|Chunks| I["Stage 5:<br/>Embedding Generation<br/>all-MiniLM-L6-v2"]
    I -->|Embeddings| J["Database<br/>pgvector"]
    J -->|Chunks + Embeddings| K["Stage 6:<br/>Hybrid Retrieval<br/>BM25 + Dense + RRF"]
    K -->|Top-20 Candidates| L["Stage 7:<br/>Cross-Encoder<br/>Reranking"]
    L -->|Top-5 Ranked| M["Stage 8:<br/>LLM Generation<br/>Streaming"]
    M -->|Tokens| N["Citation Building"]
    N --> O["✅ Final Answer<br/>With [N] citations"]
    M -->|Persist| P["💾 Session Store"]
```

## Stage Details

### Stage 1: Query Decomposition
**Module:** `pipeline/decompose.py`

Determines whether to run the query as-is (fast path) or decompose it into sub-queries:

```mermaid
graph LR
    A["Input: query"] --> B{"Query length < 60<br/>AND<br/>Simple keywords?"}
    B -->|Yes| C["Fast Path<br/>Skip LLM"]
    B -->|No| D["Call LLM<br/>Generate sub-queries"]
    C --> E["Output: 1 query"]
    D --> F["Output: N queries"]
```

**Decision Logic:**
- If `len(query) < 60` AND LLM returns same query → fast path (0ms extra)
- Otherwise → run full decomposition via LLM (~200ms)

**Output Format:**
```python
{
  "sub_queries": ["Q1", "Q2", ...],
  "original_query": "original",
  "mode": "fast_path" | "llm",
  "latency_ms": int
}
```

---

### Stage 2: URL Discovery
**Module:** `pipeline/search.py`

Uses Tavily API to find relevant URLs. Runs in parallel for each sub-query.

```mermaid
graph TB
    A["Sub-queries"] -->|Parallel| B["Query 1"]
    A -->|Parallel| C["Query 2"]
    A -->|Parallel| D["Query 3"]
    B -->|Tavily API| E["Results 1: URLs + snippets"]
    C -->|Tavily API| F["Results 2: URLs + snippets"]
    D -->|Tavily API| G["Results 3: URLs + snippets"]
    E --> H["Deduplicate<br/>Keep insertion order"]
    F --> H
    G --> H
    H --> I["Final URLs"]
```

**Key Design:**
- Deduplicates URLs across sub-queries
- Preserves snippet metadata (not used for extraction, only metadata)
- **Critical:** Jina Reader extracts full markdown, NOT Tavily snippets
- Timeout: 30s per query (configurable)

**Output Format:**
```python
[
  {
    "url": "https://...",
    "title": "Page title",
    "snippet": "Summary (metadata only)"
  },
  ...
]
```

---

### Stage 3: Full-Page Extraction
**Module:** `pipeline/extract.py`

Extracts complete page markdown using Jina Reader with trafilatura fallback.

```mermaid
graph TB
    A["URLs from Stage 2"] -->|Parallel| B["Jina Reader<br/>r.jina.ai/{url}"]
    B -->|Success| C["✓ Markdown<br/>Full page"]
    B -->|Fail 403/timeout| D["trafilatura<br/>Fallback"]
    D -->|Success| E["✓ HTML → Markdown"]
    D -->|Fail| F["✗ Skip page"]
    C --> G["Page objects<br/>url, title, markdown"]
    E --> G
    G -->|Cache| H["Supabase<br/>page_cache<br/>24h TTL"]
```

**Cache Strategy:**
- Check `page_cache` for recent URLs
- Only fetch if missing or expired (>24h)
- Store with 24-hour TTL to balance freshness and cost

**Output Format:**
```python
class Page:
  url: str
  title: str
  markdown: str  # Full page content
  fetched_at: datetime
```

---

### Stage 4: Intelligent Chunking
**Module:** `pipeline/chunk.py`

Splits markdown into chunks while preserving heading hierarchy and context.

```mermaid
graph TB
    A["Pages with markdown"] --> B["Heading hierarchy parser<br/># / ## / ### structure"]
    B --> C["Split by headings<br/>Maintain context"]
    C --> D["Text chunks<br/>max_chars=1500"]
    D --> E["Overlap<br/>150 chars"]
    E --> F["Chunks with metadata<br/>heading, url, title"]
    F --> G["Chunk objects"]
```

**Configuration:**
- `MAX_CHARS = 1500` — Max chunk size
- `OVERLAP = 150` — Overlap between chunks
- Preserves heading context for every chunk

**Output Format:**
```python
class Chunk:
  url: str
  title: str
  chunk_index: int
  chunk_text: str
  heading: str  # Parent heading
```

---

### Stage 5: Embedding Generation
**Module:** `pipeline/embed.py`

Converts chunks to dense embeddings using `all-MiniLM-L6-v2`.

```mermaid
graph TB
    A["Chunks"] -->|Batch| B["Sentence Transformer<br/>all-MiniLM-L6-v2<br/>384 dimensions"]
    B -->|Normalize| C["L2 Normalized<br/>Vectors"]
    C -->|Store| D["Supabase pgvector<br/>web_chunks table"]
    C -->|Cache| E["In-memory index<br/>Per-query retrieval"]
```

**Key Properties:**
- Model: `all-MiniLM-L6-v2` (fast, 384-dim)
- Normalized: L2 norm for cosine similarity
- Device: GPU if available, else CPU
- Batch size: 32 (configurable for OOM)

**Persistence:**
- Store embeddings in pgvector
- No re-compute on cache hit
- Device info surfaced in SSE event

---

### Stage 6: Hybrid Retrieval
**Module:** `pipeline/retrieve.py`

Combines sparse (BM25) and dense (cosine) retrieval via Reciprocal Rank Fusion (RRF).

```mermaid
graph TB
    A["Sub-query + Chunks"] --> B["Branch 1: BM25"]
    A --> C["Branch 2: Dense<br/>Cosine Similarity"]
    B -->|Rank scores| D["Top-20 by BM25<br/>score"]
    C -->|Cosine scores| E["Top-20 by density<br/>score"]
    D --> F["RRF Fusion<br/>k=60"]
    E --> F
    F -->|Combined ranking| G["Top-20 candidates<br/>RRF score"]
    G --> H["Reranking Stage 7"]
```

**Algorithm: Reciprocal Rank Fusion (RRF)**

```
RRF_score(i) = sum(1 / (k + rank_i))
              over all ranker methods i
```

- `k = 60` (tuned empirically)
- Combines BM25 and cosine ranks fairly
- Produces top-20 candidates per sub-query

**Output Format:**
```python
class RankedChunk:
  chunk: Chunk
  score: float  # RRF score
  bm25_score: float
  dense_score: float
```

---

### Stage 7: Cross-Encoder Reranking
**Module:** `pipeline/retrieve.py` (end)

Uses cross-encoder to rerank top-20 → top-5 with query-chunk relevance scores.

```mermaid
graph TB
    A["Top-20 candidates<br/>+ query"] --> B["Cross-Encoder<br/>ms-marco-TinyBERT-L-2-v2"]
    B -->|Relevance scores<br/>0-1| C["Sort by score<br/>descending"]
    C -->|Top-5| D["Final ranking<br/>Ready for LLM"]
    D -->|Score summary| E["SSE: rerank_done<br/>min/max/top-k count"]
```

**Model:** `ms-marco-TinyBERT-L-2-v2`
- Fast (<100ms for 20 pairs)
- Trained on MS MARCO dataset
- Outputs single relevance score

**Output:** Top-5 chunks per sub-query

---

### Stage 8: LLM Generation
**Module:** `pipeline/generate.py`

Generates streaming answers using LLM with reranked chunks as context.

```mermaid
graph TB
    A["Query + Top-5 chunks<br/>from reranker"] --> B["Build prompt<br/>Context + Instructions"]
    B --> C["LLM Stream<br/>DeepSeek V3<br/>or OpenAI"]
    C -->|Tokens| D["Parse citations<br/>[1], [2], ..."]
    D -->|Token event| E["SSE: token<br/>Sent to frontend"]
    D -->|Answer text| F["Accumulate<br/>per sub-query"]
    F -->|All tokens| G["Answer<br/>for sub-query"]
```

**LLM Selection:**
- **Primary:** DeepSeek V3 (`deepseek-chat`)
- **Fallback:** OpenAI GPT-4o

**Prompt Format:**
```
You are a helpful assistant. Answer the following question using ONLY the provided context.
If the context doesn't contain the answer, say "I don't have enough information."

Context:
[Top-5 chunks formatted with [N] citation markers]

Question: {query}

Answer:
```

**Citation Format:**
- Answer includes `[1]`, `[2]`, etc.
- Citation mapping done in post-processing

---

### Stage 8b: Multi-Query Synthesis
**Module:** `pipeline/generate.py`

If multiple sub-queries were used, synthesize into single answer:

```mermaid
graph TB
    A["Multiple sub-answers"] -->|Decomposed| B["Were sub-queries used?"]
    B -->|Single query| C["Use answer as-is"]
    B -->|Multiple queries| D["Synthesis LLM<br/>Combine & deduplicate"]
    D -->|Token stream| E["Final synthesized<br/>answer"]
```

**Synthesis Prompt:**
```
Combine these sub-answers into a coherent response.
Merge duplicate information and maintain citations.

Sub-answers:
[Each with [N] citations]

Combined answer:
```

---

## Database Schema

```mermaid
erDiagram
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : contains
    CHAT_MESSAGES ||--o{ PAGE_CACHE : references
    PAGE_CACHE ||--o{ WEB_CHUNKS : contains
    
    CHAT_SESSIONS {
        uuid id PK
        text title
        timestamp created_at
        timestamp updated_at
    }
    
    CHAT_MESSAGES {
        bigserial id PK
        uuid session_id FK
        text question
        text answer
        jsonb citations
        jsonb urls
        jsonb chunks
        jsonb traces
        jsonb latency_breakdown
        int total_latency_ms
        timestamp created_at
    }
    
    PAGE_CACHE {
        text url PK
        text title
        text markdown
        timestamp fetched_at
        timestamp expires_at
    }
    
    WEB_CHUNKS {
        bigserial id PK
        text url FK
        text title
        int chunk_index
        text chunk_text
        text heading
        vector embedding
        jsonb metadata
        timestamp created_at
        unique "url, chunk_index"
    }
```

---

## Streaming Protocol

The backend streams 9+ event types via SSE. Frontend accumulates state:

```mermaid
sequenceDiagram
    participant Frontend
    participant Backend
    participant Pipeline
    
    Frontend->>Backend: POST /api/search {query, session_id}
    Backend->>Pipeline: Start pipeline
    
    Pipeline->>Backend: decompose_done
    Backend->>Frontend: SSE event
    Frontend->>Frontend: Show query decomposition
    
    Pipeline->>Backend: search_done
    Backend->>Frontend: SSE event
    Frontend->>Frontend: Show URLs
    
    Pipeline->>Backend: extract_done
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: chunk_done
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: embed_done
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: retrieve_done
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: rerank_done
    Backend->>Frontend: SSE event
    Frontend->>Frontend: Show confidence scores
    
    Pipeline->>Backend: sub_answer_start
    Backend->>Frontend: SSE event
    Frontend->>Frontend: Show sub-query header
    
    Pipeline->>Backend: sub_answer_token (×N)
    Backend->>Frontend: SSE event (×N)
    Frontend->>Frontend: Stream tokens to user
    
    Pipeline->>Backend: sub_answer_done
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: synthesis_start (optional)
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: token (synthesis tokens)
    Backend->>Frontend: SSE event
    
    Pipeline->>Backend: done {session_id, citations, latency}
    Backend->>Frontend: SSE event
    Frontend->>Frontend: Show final answer, citations
```

---

## Error Handling

```mermaid
graph TB
    A["Pipeline Stage"] --> B{"Success?"}
    B -->|Yes| C["Next stage"]
    B -->|No| D{"Fatal?"}
    D -->|Yes| E["Emit error<br/>Save stub"]
    D -->|No| F["Log warning<br/>Continue"]
    E --> G["Frontend shows<br/>error message"]
    F --> C
```

**Fatal Errors:**
- No URLs found
- No pages extracted
- No chunks generated

**Non-Fatal (logged):**
- Single URL extraction fails
- Jina Reader timeout → trafilatura fallback

---

## Performance Characteristics

```
Query Decomposition:    0-300ms   (0ms if fast_path)
URL Discovery:          500-1500ms  (parallel)
Page Extraction:        1000-3000ms (parallel, cached)
Chunking:               50-200ms    (linear in content)
Embedding:              100-500ms   (batched, GPU if available)
Retrieval:              200-500ms   (RRF + rerank)
Generation:             2000-5000ms (depends on LLM)
─────────────────────────────────────────────────────
Total (typical):        4-6 seconds
```

Bottleneck: LLM generation (streaming improves perceived latency).

---

## Extensibility

### Adding a Custom Retriever
```python
# pipeline/retrieve.py
async def custom_retrieve(query: str, chunks: list, top_k: int) -> list:
    """Your retriever here."""
    ranked = [RankedChunk(chunk=c, score=s) for c, s in ...]
    return ranked[:top_k]
```

Then update `Stage 6` to call it.

### Swapping the LLM
```python
# pipeline/generate.py
async def generate_stream(query: str, ranked_chunks: list):
    """Swap to your LLM."""
    async for token in your_llm.stream(prompt):
        yield token
```

### Custom Chunking Strategy
```python
# pipeline/chunk.py
def chunk_pages(pages: list) -> list:
    """Your chunking logic here."""
    return chunks
```

All modules are designed to be replaced independently.

---

## Deployment Considerations

- **Environment Variables:** 7 required (see [DEPLOYMENT.md](./DEPLOYMENT.md))
- **Database:** Requires pgvector extension
- **LLM Cost:** ~$0.01–0.05 per query (DeepSeek cheaper than OpenAI)
- **Embedding Cost:** ~$0.000003 per 1K chunks (one-time)
- **Caching:** 24h page cache reduces extraction costs

---

## Diagrams Legend

- 🖥️ Frontend
- 🔄 Processing
- 🔍 Search
- 📄 Content
- 📊 Data/ML
- 💬 Generation
- 🗄️ Database
- ✅ Output
- ⚙️ Configuration
