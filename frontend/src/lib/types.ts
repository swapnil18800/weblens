// Shared types used across the chat + eval pages

export interface UrlInfo {
  url: string;
  title: string;
  snippet?: string;
}

export interface PageInfo {
  url: string;
  title: string;
  char_count: number;
  from_cache?: boolean;
}

export interface PerPageChunk {
  url: string;
  chunk_count: number;
}

export interface ChunkDict {
  url: string;
  title: string;
  heading: string;
  chunk_text: string;
  score: number;
  rank: number;
}

export interface Citation {
  num: number;
  url: string;
  title: string;
  snippet: string;
}

export interface RerankExplain {
  total_chunks?: number;
  bm25_pool?: number;
  ce_pool?: number;
  dedup_dropped?: number;
  url_cap_dropped?: number;
  final_kept?: number;
  score_min?: number;
  score_max?: number;
}

export interface RerankSummary {
  index: number;
  candidates: number;
  top_k: number;
  max_score: number;
  min_score: number;
  explain?: RerankExplain;
}

export interface ExtractFailure {
  url: string;
  reason: "timeout" | "http_error" | "too_short" | "parse_failed";
}

/** A row in the per-sub-query "Read pages" expandable list. The status drives
 *  the chip color/label; char_count drives the chip's secondary text and sort. */
export type ExtractStatus = "extracted" | "cached" | "http_error" | "too_short" | "parse_error";

export interface ExtractPageEntry {
  url: string;
  title: string;
  status: ExtractStatus;
  char_count: number;
}

export interface PerSubqueryExtract {
  index: number;
  pages: ExtractPageEntry[];
  succeeded: number;
  attempted: number;
  failures: ExtractFailure[];
}

export interface PerSubqueryChunk {
  index: number;
  count: number;
  pages: number;
  stats: ChunkStats;
}

export interface PerSubqueryEmbed {
  index: number;
  candidate_count: number;
}

export interface ChunkStats {
  garbage_dropped: number;
  min_body_dropped: number;
  dedup_dropped: number;
  kept: number;
}

export type ErrorReason =
  | "tavily_timeout"
  | "tavily_http_error"
  | "no_api_key"
  | "no_urls"
  | "extract_failed"
  | "no_chunks"
  | "internal";

// Server-Sent Event payload shapes (mirrors backend SSE protocol)
export type SseEvent =
  | { event: "rewrite_done"; data: { original_query: string; rewritten_query: string; rewrote: boolean; latency_ms: number } }
  | { event: "decompose_done"; data: { sub_queries: string[]; original_query: string; rewritten_query?: string; rewrote?: boolean; mode: "fast_path" | "llm"; latency_ms: number } }
  | { event: "page_cache_info"; data: { hits: number; misses: number; from_cache_urls: string[]; fetched_urls: string[] } }
  | { event: "embedding_cleanup_done"; data: { freed_candidate_count: number; freed_chunks_count: number; latency_ms: number } }
  | { event: "search_done"; data: {
      urls: UrlInfo[];
      sub_queries: string[];
      latency_ms: number;
      per_subquery: { index: number; subquery: string; urls: UrlInfo[]; count: number; error_reason?: string | null }[];
      attempted?: number;
      returned?: number;
      dropped_duplicates?: number;
      error_reason?: string | null;
    } }
  | { event: "extract_done"; data: { pages: PageInfo[]; latency_ms: number; attempted?: number; succeeded?: number; failures?: ExtractFailure[]; per_subquery?: PerSubqueryExtract[] } }
  | { event: "chunk_done"; data: { count: number; pages: number; latency_ms: number; per_page: PerPageChunk[]; stats?: ChunkStats; per_subquery?: PerSubqueryChunk[] } }
  | { event: "embed_done"; data: { candidate_count: number; dim: number; latency_ms: number; device: string; per_subquery?: PerSubqueryEmbed[] } }
  | { event: "retrieve_done"; data: { total_chunks: number; sub_queries: number; latency_ms: number } }
  | { event: "rerank_done"; data: { per_subquery: RerankSummary[]; latency_ms: number } }
  | { event: "sub_answer_start"; data: { index: number; query: string; chunks: ChunkDict[]; citations: Citation[]; urls: UrlInfo[]; bm25_top: { url: string; score: number; title: string }[]; dense_top: { url: string; score: number; title: string }[] } }
  | { event: "sub_answer_token"; data: { index: number; text: string } }
  | { event: "sub_answer_done"; data: { index: number; latency_ms: number; cancelled?: boolean; error?: string } }
  | { event: "synthesis_start"; data: {} }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: { session_id: string; citations: Citation[]; total_latency_ms: number; latency_breakdown: Record<string, any>; followups?: string[] } }
  | { event: "error"; data: { message: string; reason?: ErrorReason; failures?: ExtractFailure[] } };

// ── Chat store shapes ────────────────────────────────────────────────────────

export type StepKind =
  | "rewrite"
  | "route"
  | "decompose"
  | "page_cache"
  | "search"
  | "extract"
  | "chunk"
  | "embed"
  | "bm25"
  | "dense"
  | "rrf"
  | "rerank"
  | "generate"
  | "cleanup";

export type StepStatus = "pending" | "running" | "done" | "failed";

export interface ReasoningStep {
  id: string;
  kind: StepKind;
  label: string;
  detail: string;
  payload?: any;
  latencyMs?: number;
  status: StepStatus;
}

export interface SubqueryState {
  index: number;
  query: string;
  steps: ReasoningStep[];
  tokens: string;
  done: boolean;
  cancelled?: boolean;
  errorMsg?: string;
  latencyMs?: number;
  startedAt?: number;
  completedAt?: number;
  chunks: ChunkDict[];
  urls: UrlInfo[];
  citations: Citation[];
  bm25Top?: { url: string; score: number; title: string }[];
  denseTop?: { url: string; score: number; title: string }[];
}

export interface PipelineGlobals {
  rewriteMs?: number;
  rewrote?: boolean;
  decomposeMs?: number;
  decomposeMode?: "fast_path" | "llm";
  searchMs?: number;
  extractMs?: number;
  pageCacheHits?: number;
  pageCacheMisses?: number;
  chunkMs?: number;
  embedMs?: number;
  embedDevice?: string;
  retrieveMs?: number;
  rerankMs?: number;
  cleanupMs?: number;
  cleanupFreedChunks?: number;
  pages?: PageInfo[];
  perPageChunks?: PerPageChunk[];
  totalChunks?: number;
}

export interface Turn {
  id: string;
  /** All retries / edits of the same prompt share a versionGroupId so the UI
   *  can render a "< 2/2 >" navigator and let the user toggle between versions. */
  versionGroupId: string;
  /** 0-based index inside the version group, in submission order. */
  versionIndex: number;
  question: string;
  status: "streaming" | "done" | "stopped" | "error";
  errorMsg?: string;
  subQueries: string[];
  subqueries: SubqueryState[];
  pipeline: PipelineGlobals;
  synthesisMd: string;
  synthesizing: boolean;
  citations: Citation[];
  // Original-num → display-num remap. Built on `done` so streamed [N] markers,
  // citation rows, and toolbar count all agree starting at [1]. Empty until
  // the turn finishes. Render layers must apply this — never mutate Citation.num.
  citationRemap?: Record<number, number>;
  /** Suggested follow-up questions surfaced after the answer completes. */
  followups?: string[];
  /** If the user's question was rewritten using prior turn context, the
   *  rewritten form. Shown as a small "→ rewritten as: …" chip in the trace. */
  rewrittenQuery?: string;
  totalLatencyMs?: number;
  createdAt: number;
  // Synthesis-phase tracking (for the trace)
  combiningStatus?: "running" | "done";
  finalStatus?: "running" | "done";
  // Wall-clock timestamps for the synthesis phases — power the live + frozen
  // elapsed-time tags on the Combining and Final-answer trace rows.
  combiningStartedAt?: number;
  combiningCompletedAt?: number;
  finalStartedAt?: number;
  finalCompletedAt?: number;
}

export interface SessionListItem {
  session_id: string;
  title: string;
  message_count: number;
  last_active: string | null;
  created_at: string;
}

export interface PersistedMessage {
  id: number;
  question: string;
  answer: string;
  citations: Citation[];
  urls: UrlInfo[];
  chunks: ChunkDict[];
  latency_breakdown: Record<string, number>;
  total_latency_ms: number;
  sub_queries: string[];
  traces: {
    index: number;
    query: string;
    urls: UrlInfo[];
    chunks: ChunkDict[];
    answer: string;
    latency_ms: number;
    extract_stats?: PerSubqueryExtract | null;
    chunk_stats?: PerSubqueryChunk | null;
    embed_count?: number | null;
  }[];
  created_at: string;
}

export interface PersistedSession {
  session_id: string;
  messages: PersistedMessage[];
}

// ── Eval shapes ──────────────────────────────────────────────────────────────

export interface EvalRunSummary {
  run_id: string;
  summary: any;
}

export interface EvalQuestion {
  question: string;
  category?: string;
  metrics?: { m1_factual_correctness?: number; m3_retrieval_recall?: number; m7_judge_score?: number };
  verdict?: string;
  ground_truth?: string;
  key_facts?: string[];
  judge_reasoning?: string;
  pipeline?: {
    answer?: string;
    citations?: Citation[];
    urls?: UrlInfo[];
    chunks?: ChunkDict[];
    sub_queries?: string[];
    error?: string | null;
  };
  timing?: { pipeline_s?: number; total_latency_ms?: number; latency_breakdown?: Record<string, number> };
}

export interface CachedRow {
  query_hash: string;
  query_text: string;
  mode: string;
  inserted_at: string | null;
  expires_at: string | null;
  hit_count: number;
}

export interface EvalRunDetail {
  run_id: string;
  summary: any;
  questions: EvalQuestion[];
  cached_rows?: CachedRow[];
}
