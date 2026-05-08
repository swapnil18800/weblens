-- web-search-rag schema
-- Run once: python db/setup.py
-- Requires pgvector extension (already enabled on this Supabase instance)

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Page-level cache ─────────────────────────────────────────────────────────
-- Avoids re-fetching the same URL within the TTL window.
-- On cache hit: skip extraction, go straight to chunking.
CREATE TABLE IF NOT EXISTS page_cache (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    markdown    TEXT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours'
);

-- ── Chunk storage with vector embeddings ─────────────────────────────────────
-- One row per chunk. Reused across queries that hit the same URLs.
-- embedding: all-MiniLM-L6-v2 (384-dim, normalized)
CREATE TABLE IF NOT EXISTS web_chunks (
    id           BIGSERIAL PRIMARY KEY,
    url          TEXT NOT NULL,
    title        TEXT,
    chunk_index  INTEGER NOT NULL,
    chunk_text   TEXT NOT NULL,
    heading      TEXT,                -- nearest H1/H2/H3 above this chunk
    embedding    vector(384),         -- null until embedded
    metadata     JSONB DEFAULT '{}',  -- char_count, token_estimate, etc.
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (url, chunk_index)
);

-- IVFFlat index for approximate nearest-neighbour search
-- Tune `lists` to sqrt(row_count) for best recall/speed balance
CREATE INDEX IF NOT EXISTS web_chunks_embedding_idx
    ON web_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS web_chunks_url_idx ON web_chunks (url);
CREATE INDEX IF NOT EXISTS page_cache_expires_idx ON page_cache (expires_at);

-- ── Session persistence ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_sessions (
    session_id  TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_session_messages (
    id                BIGSERIAL PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES rag_sessions(session_id) ON DELETE CASCADE,
    question          TEXT NOT NULL,
    answer            TEXT DEFAULT '',
    citations         JSONB DEFAULT '[]',
    urls              JSONB DEFAULT '[]',
    chunks            JSONB DEFAULT '[]',
    latency_breakdown JSONB DEFAULT '{}',
    total_latency_ms  INTEGER DEFAULT 0,
    sub_queries       JSONB DEFAULT '[]',
    traces            JSONB DEFAULT '[]',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rag_session_messages_sid_idx
    ON rag_session_messages (session_id, created_at);
