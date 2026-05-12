import { create } from "zustand";
import { streamSearch } from "../lib/sse";
import { api } from "../lib/api";
import type {
  ChunkDict,
  ErrorReason,
  ExtractFailure,
  PersistedSession,
  ReasoningStep,
  SessionListItem,
  SseEvent,
  SubqueryState,
  Turn,
} from "../lib/types";

const FRIENDLY_ERROR: Record<ErrorReason, string> = {
  tavily_timeout:    "Search timed out. The web is slow or unreachable — try again.",
  tavily_http_error: "Search provider returned an error. Try again in a moment.",
  no_api_key:        "Search is not configured. Set TAVILY_API_KEY on the server.",
  no_urls:           "Couldn't find any web sources for this question.",
  extract_failed:    "Found sources but couldn't read any of them.",
  no_chunks:         "Sources read, but nothing useful to cite — try a different query.",
  internal:          "Something went wrong on our end.",
};

function friendlyError(reason: ErrorReason | undefined, fallback: string): string {
  if (reason && FRIENDLY_ERROR[reason]) return FRIENDLY_ERROR[reason];
  return fallback || "Something went wrong.";
}

function summariseFailures(failures: ExtractFailure[] | undefined): string {
  if (!failures || failures.length === 0) return "";
  const counts: Record<string, number> = {};
  for (const f of failures) counts[f.reason] = (counts[f.reason] || 0) + 1;
  const parts: string[] = [];
  for (const [reason, n] of Object.entries(counts)) {
    parts.push(`${n} ${reason.replace(/_/g, " ")}`);
  }
  return parts.join(", ");
}

const SESSION_KEY = "wsr_session_id";

// In public mode (production), session_id is held in memory only — neither
// localStorage nor sessionStorage. That means every page reload (and every
// tab close) starts a fresh anonymous session in the UI. The DB still keeps
// the full history scoped to that session_id, for analytics/debugging.
//
// In dev mode (default), session_id is persisted in localStorage so the
// developer can come back to the same conversation across reloads, and the
// sidebar lists all past sessions.
const IS_PUBLIC = (import.meta.env.VITE_PUBLIC_MODE ?? "false").toString() === "true";

function _store(): Storage | null {
  return IS_PUBLIC ? null : localStorage;
}

function newSessionId(): string {
  const s = crypto.randomUUID();
  const store = _store();
  if (store) store.setItem(SESSION_KEY, s);
  return s;
}

function readSessionId(): string {
  const store = _store();
  if (!store) return newSessionId();   // public mode: fresh id per page load
  return store.getItem(SESSION_KEY) || newSessionId();
}

// ── "My sessions" tracker (dev-only) ────────────────────────────────────────
// Records session IDs created from this browser so the sidebar can show a
// small "you" badge that distinguishes the developer's own sessions from
// anonymous traffic on the shared DB. Never used in public mode.
const MY_SESSIONS_KEY = "wsr_my_sessions";

export function getMySessions(): Set<string> {
  if (IS_PUBLIC) return new Set();
  try {
    const raw = localStorage.getItem(MY_SESSIONS_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw));
  } catch {
    return new Set();
  }
}

export function addMySession(id: string): void {
  if (IS_PUBLIC) return;
  try {
    const set = getMySessions();
    if (set.has(id)) return;
    set.add(id);
    localStorage.setItem(MY_SESSIONS_KEY, JSON.stringify([...set]));
  } catch {
    /* storage full / unavailable — non-fatal */
  }
}

function newTurn(question: string, versionGroupId?: string, versionIndex = 0): Turn {
  return {
    id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    versionGroupId: versionGroupId || `grp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    versionIndex,
    question,
    status: "streaming",
    subQueries: [],
    subqueries: [],
    pipeline: {},
    synthesisMd: "",
    synthesizing: false,
    citations: [],
    createdAt: Date.now(),
  };
}

function newSubqueryState(index: number, query: string): SubqueryState {
  return {
    index,
    query,
    steps: [],
    tokens: "",
    done: false,
    chunks: [],
    urls: [],
    citations: [],
    startedAt: Date.now(),
  };
}

function step(
  kind: ReasoningStep["kind"],
  label: string,
  detail: string,
  status: ReasoningStep["status"] = "done",
  payload?: any,
  latencyMs?: number,
): ReasoningStep {
  return {
    id: `${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    kind,
    label,
    detail,
    status,
    payload,
    latencyMs,
  };
}

interface ChatStore {
  sessionId: string;
  turns: Turn[];
  isStreaming: boolean;
  controller: AbortController | null;
  sessions: SessionListItem[];
  devMode: boolean;
  pendingInput: string;
  sidebarOpen: boolean;
  loadingSessionId: string | null;
  reactions: Record<string, "like" | "dislike" | undefined>;
  setReaction: (turnId: string, r: "like" | "dislike" | null) => void;
  /** versionGroupId → index of the currently displayed sibling. */
  selectedVersion: Record<string, number>;
  selectVersion: (groupId: string, index: number) => void;

  // Lifecycle
  init: () => Promise<void>;
  setDevMode: (d: boolean) => void;
  startNewChat: () => void;
  loadSession: (id: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
  deleteSession: (id: string) => Promise<void>;

  // UI
  setPendingInput: (q: string) => void;
  setSidebarOpen: (v: boolean) => void;

  // Streaming
  submitQuery: (q: string, versionGroupId?: string) => Promise<void>;
  retryTurn: (turnId: string) => Promise<void>;
  editTurn: (turnId: string, newQuestion: string) => Promise<void>;
  stop: () => void;

  // SSE handler (exposed for tests; called internally by submitQuery)
  handleSse: (e: SseEvent) => void;
}

export const useChat = create<ChatStore>((set, get) => ({
  sessionId: readSessionId(),
  turns: [],
  isStreaming: false,
  controller: null,
  sessions: [],
  devMode: false,
  pendingInput: "",
  sidebarOpen: typeof window !== "undefined" ? window.matchMedia("(min-width: 768px)").matches : true,
  loadingSessionId: null,
  reactions: {},
  setReaction: (turnId, r) => set((s) => {
    const next = { ...s.reactions };
    if (r === null) delete next[turnId];
    else next[turnId] = r;
    return { reactions: next };
  }),
  selectedVersion: {},
  selectVersion: (groupId, index) =>
    set((s) => ({ selectedVersion: { ...s.selectedVersion, [groupId]: index } })),

  init: async () => {
    try {
      const h = await api.health();
      set({ devMode: h.dev_mode });
    } catch {
      // Backend down — leave devMode false
    }
    await get().refreshSessions();
  },

  setDevMode: (d) => set({ devMode: d }),
  setPendingInput: (q) => set({ pendingInput: q }),
  setSidebarOpen: (v) => set({ sidebarOpen: v }),

  startNewChat: () => {
    const id = newSessionId();
    set({ sessionId: id, turns: [] });
  },

  loadSession: async (id: string) => {
    set({ sessionId: id, loadingSessionId: id, turns: [] });
    const store = _store();
    if (store) store.setItem(SESSION_KEY, id);
    try {
      const data: PersistedSession = await api.getSession(id);
      const turns: Turn[] = data.messages.map((m) => {
        const br = (m.latency_breakdown || {}) as Record<string, any>;
        const createdAtMs = new Date(m.created_at).getTime();
        const subqueries: SubqueryState[] = (m.traces || []).map((t) => ({
          index: t.index,
          query: t.query,
          steps: rehydrateSteps(t, br),
          tokens: t.answer || "",
          done: true,
          chunks: t.chunks || [],
          urls: t.urls || [],
          citations: [],
          latencyMs: t.latency_ms,
          startedAt: createdAtMs,
          completedAt: createdAtMs + (t.latency_ms || 0),
        }));

        const remap: Record<number, number> = {};
        (m.citations || []).forEach((c, i) => { remap[c.num] = i + 1; });
        const followups: string[] | undefined = Array.isArray((br as any).followups)
          ? ((br as any).followups as string[]).slice(0, 3)
          : undefined;
        const rewrittenQuery: string | undefined = typeof (br as any).rewritten_query === "string"
          ? ((br as any).rewritten_query as string)
          : undefined;
        const turn: Turn = {
          id: `hydrated-${m.id}`,
          // Each hydrated turn is its own group — version history isn't
          // persisted to DB yet, so loaded sessions show each row as a single
          // version. Live retries in this session still group correctly.
          versionGroupId: `hydrated-grp-${m.id}`,
          versionIndex: 0,
          question: m.question,
          status: "done",
          subQueries: m.sub_queries || [],
          subqueries,
          citationRemap: remap,
          followups,
          rewrittenQuery,
          pipeline: {
            decomposeMs: br.decompose_ms,
            decomposeMode: br.decompose_mode,
            searchMs: br.search_ms,
            extractMs: br.extract_ms,
            chunkMs: br.chunk_ms,
            embedMs: br.embed_ms,
            embedDevice: br.embed_device,
            retrieveMs: br.retrieve_ms,
            rerankMs: br.rerank_ms,
            totalChunks: br.chunks_count ?? m.chunks?.length,
          },
          synthesisMd: m.answer,
          synthesizing: false,
          citations: m.citations || [],
          totalLatencyMs: m.total_latency_ms,
          createdAt: createdAtMs,
          // Restore synthesis-phase rows so the trace renders the full sequence,
          // and set wall-clock anchors so the elapsed-time chips render. For
          // multi-Q runs the synthesis call dominates the final phase; combining
          // is essentially instant. For single-Q both phases are zero-length.
          combiningStatus: "done",
          finalStatus: "done",
          combiningStartedAt: createdAtMs,
          combiningCompletedAt: createdAtMs,
          finalStartedAt: createdAtMs,
          finalCompletedAt: createdAtMs + (br.synthesis_ms || 0),
        };
        return turn;
      });
      set({ turns });
    } catch (err) {
      console.warn("loadSession failed", err);
    } finally {
      set({ loadingSessionId: null });
    }
  },

  refreshSessions: async () => {
    try {
      const list = await api.listSessions();
      set({ sessions: list });
    } catch {
      set({ sessions: [] });
    }
  },

  deleteSession: async (id: string) => {
    try {
      await api.deleteSession(id);
    } catch (err) {
      console.warn("deleteSession failed", err);
    }
    set((s) => ({ sessions: s.sessions.filter((x) => x.session_id !== id) }));
    if (get().sessionId === id) {
      get().startNewChat();
    }
  },

  submitQuery: async (q: string, versionGroupId?: string) => {
    if (!q.trim() || get().isStreaming) return;
    const controller = new AbortController();
    // If versionGroupId is set, this is a retry/edit — append as a sibling and
    // select it (so the user sees the new run immediately).
    let nextIdx = 0;
    if (versionGroupId) {
      const siblings = get().turns.filter((t) => t.versionGroupId === versionGroupId);
      nextIdx = siblings.length;
    }
    const turn = newTurn(q.trim(), versionGroupId, nextIdx);
    const sessionId = get().sessionId;
    const nowIso = new Date().toISOString();
    set((s) => {
      // Optimistically add or update this session in the sidebar list.
      // For continued sessions, preserve the existing title — overwriting it
      // with the latest query causes a visible flash when refreshSessions()
      // later returns the canonical title from the server.
      const existing = s.sessions.find((x) => x.session_id === sessionId);
      const optimistic: SessionListItem = {
        session_id: sessionId,
        title: existing?.title ?? q.trim().slice(0, 60),
        message_count: (existing?.message_count ?? 0) + 1,
        last_active: nowIso,
        created_at: existing?.created_at ?? nowIso,
      };
      const others = s.sessions.filter((x) => x.session_id !== sessionId);
      // Mark this session as locally-owned (dev-only "you" badge in Sidebar).
      addMySession(sessionId);
      return {
        turns: [...s.turns, turn],
        isStreaming: true,
        controller,
        sessions: [optimistic, ...others],
        selectedVersion: versionGroupId
          ? { ...s.selectedVersion, [versionGroupId]: nextIdx }
          : s.selectedVersion,
      };
    });

    try {
      await streamSearch({
        query: q.trim(),
        sessionId: get().sessionId,
        signal: controller.signal,
        onEvent: (e) => get().handleSse(e),
      });
      // Mark current turn done if not already
      mutateTurn(set, turn.id, (t) => {
        if (t.status === "streaming") t.status = "done";
        if (t.synthesizing) t.synthesizing = false;
      });
    } catch (err: any) {
      if (err?.name === "AbortError") {
        // Stop already mutated state
      } else {
        mutateTurn(set, turn.id, (t) => {
          t.status = "error";
          t.errorMsg = String(err?.message || err);
          t.synthesizing = false;
          if (t.combiningStatus === "running") t.combiningStatus = "done";
          if (t.finalStatus === "running") t.finalStatus = "done";
          t.subqueries = t.subqueries.map((sq) => {
            if (sq.done) return sq;
            const steps = sq.steps.map((st) =>
              st.status === "running" ? { ...st, status: "failed" as const } : st,
            );
            return { ...sq, steps, done: true, errorMsg: sq.errorMsg || t.errorMsg };
          });
        });
      }
    } finally {
      set({ isStreaming: false, controller: null });
      // Refresh sidebar so the new session shows up
      void get().refreshSessions();
    }
  },

  retryTurn: async (turnId: string) => {
    const t = get().turns.find((x) => x.id === turnId);
    if (!t) return;
    // Re-run the SAME question as a sibling of the original turn so the user
    // can flip between attempts via the < n/N > navigator.
    await get().submitQuery(t.question, t.versionGroupId);
  },
  editTurn: async (turnId: string, newQuestion: string) => {
    const q = (newQuestion || "").trim();
    if (!q) return;
    const t = get().turns.find((x) => x.id === turnId);
    if (!t) return;
    // Edits also become siblings (different question text, same group) so the
    // user can compare the two phrasings side by side.
    await get().submitQuery(q, t.versionGroupId);
  },

  stop: () => {
    const c = get().controller;
    if (c) c.abort();
    // Mark the active streaming turn as stopped, freeze any running steps
    set((s) => ({
      turns: s.turns.map((t) => {
        if (t.status !== "streaming") return t;
        const subqueries = t.subqueries.map((sq) => {
          if (sq.done) return sq;
          const steps = sq.steps.map((st) =>
            st.status === "running" ? { ...st, status: "failed" as const, detail: "stopped" } : st,
          );
          return { ...sq, steps, done: true, cancelled: true };
        });
        return { ...t, status: "stopped" as const, synthesizing: false, subqueries };
      }),
      isStreaming: false,
      controller: null,
    }));
  },

  handleSse: (e: SseEvent) => {
    set((s) => {
      const turns = [...s.turns];
      const i = turns.length - 1;
      if (i < 0) return {};
      const t = { ...turns[i] };
      // Don't mutate stopped/errored turns
      if (t.status !== "streaming") return {};

      switch (e.event) {
        case "rewrite_done": {
          // Top-level rewrite step — capture latency and whether a rewrite occurred.
          // The actual rewritten query is also surfaced on decompose_done; we set
          // it early here so the trace UI can show the rewrite stage before analyze.
          t.pipeline = { ...t.pipeline, rewriteMs: e.data.latency_ms, rewrote: e.data.rewrote };
          if (e.data.rewrote && e.data.rewritten_query !== e.data.original_query) {
            t.rewrittenQuery = e.data.rewritten_query;
          }
          break;
        }
        case "decompose_done": {
          t.subQueries = e.data.sub_queries;
          t.pipeline = { ...t.pipeline, decomposeMs: e.data.latency_ms, decomposeMode: e.data.mode };
          if (e.data.rewrote && e.data.rewritten_query && e.data.rewritten_query !== e.data.original_query) {
            t.rewrittenQuery = e.data.rewritten_query;
          }
          // Pre-create subquery states
          t.subqueries = e.data.sub_queries.map((q, idx) => newSubqueryState(idx, q));
          break;
        }
        case "page_cache_info": {
          // Surface page-cache hit/miss summary at the pipeline level.
          // Per-URL status remains in extract_done's per_subquery slices.
          t.pipeline = {
            ...t.pipeline,
            pageCacheHits: e.data.hits,
            pageCacheMisses: e.data.misses,
          };
          break;
        }
        case "embedding_cleanup_done": {
          t.pipeline = {
            ...t.pipeline,
            cleanupMs: e.data.latency_ms,
            cleanupFreedChunks: e.data.freed_chunks_count,
          };
          break;
        }
        case "search_done": {
          t.pipeline = { ...t.pipeline, searchMs: e.data.latency_ms };
          const perSq = e.data.per_subquery || [];
          t.subqueries = t.subqueries.map((sq) => {
            const ps = perSq.find((p) => p.index === sq.index);
            if (!ps) return sq;
            return {
              ...sq,
              urls: ps.urls,
              steps: [
                ...sq.steps,
                step(
                  "search",
                  "Searched the web",
                  `Found ${ps.count} source${ps.count === 1 ? "" : "s"}`,
                  "done",
                  { urls: ps.urls, query: ps.subquery },
                  e.data.latency_ms,
                ),
              ],
            };
          });
          break;
        }
        case "extract_done": {
          // Per-sub-query slices honour the user's request that each sub-query
          // shows numbers reflecting only its own sources. Falls back to the
          // global counts if the backend didn't send per_subquery (older event).
          t.pipeline = { ...t.pipeline, extractMs: e.data.latency_ms, pages: e.data.pages };
          const perSq = e.data.per_subquery || [];
          t.subqueries = t.subqueries.map((sq) => {
            const slice = perSq.find((p) => p.index === sq.index);
            const attempted = slice ? slice.attempted : (e.data.attempted ?? e.data.pages.length);
            const succeeded = slice ? slice.succeeded : (e.data.succeeded ?? e.data.pages.length);
            const failures = slice ? slice.failures : (e.data.failures || []);
            const failSummary = summariseFailures(failures);
            const detail = failures.length > 0
              ? `Read ${succeeded} of ${attempted} pages — ${failures.length} skipped (${failSummary})`
              : `Read ${succeeded} page${succeeded === 1 ? "" : "s"}`;
            // Payload for the expandable list: prefer the per-sub-query enriched
            // page entries (with title + status chip data); fallback to global.
            const payloadPages = slice ? slice.pages : e.data.pages;
            return {
              ...sq,
              steps: [
                ...sq.steps,
                step(
                  "extract",
                  "Read pages",
                  detail,
                  "done",
                  { pages: payloadPages, failures, attempted, succeeded, enriched: !!slice },
                  e.data.latency_ms,
                ),
              ],
            };
          });
          break;
        }
        case "chunk_done": {
          t.pipeline = { ...t.pipeline, chunkMs: e.data.latency_ms, totalChunks: e.data.count };
          const perSq = e.data.per_subquery || [];
          t.subqueries = t.subqueries.map((sq) => {
            const slice = perSq.find((p) => p.index === sq.index);
            const count = slice ? slice.count : e.data.count;
            const stats = slice ? slice.stats : e.data.stats;
            const dropped = stats
              ? (stats.garbage_dropped + stats.min_body_dropped + stats.dedup_dropped)
              : 0;
            const detail = stats && dropped > 0
              ? `Built ${count} passages (dropped ${dropped}: ${stats.garbage_dropped} boilerplate, ${stats.min_body_dropped} short, ${stats.dedup_dropped} duplicate)`
              : `Built ${count} passage${count === 1 ? "" : "s"}`;
            return {
              ...sq,
              steps: [
                ...sq.steps,
                step("chunk", "Split into passages", detail, "done", null, e.data.latency_ms),
              ],
            };
          });
          break;
        }
        case "embed_done": {
          t.pipeline = { ...t.pipeline, embedMs: e.data.latency_ms, embedDevice: e.data.device };
          const perSq = e.data.per_subquery || [];
          t.subqueries = t.subqueries.map((sq) => {
            const slice = perSq.find((p) => p.index === sq.index);
            const count = slice ? slice.candidate_count : e.data.candidate_count;
            return {
              ...sq,
              steps: [
                ...sq.steps,
                step(
                  "embed",
                  "Indexed passages",
                  `${count} passage${count === 1 ? "" : "s"} ready for ranking`,
                  "done",
                  null,
                  e.data.latency_ms,
                ),
              ],
            };
          });
          break;
        }
        case "retrieve_done": {
          t.pipeline = { ...t.pipeline, retrieveMs: e.data.latency_ms };
          break;
        }
        case "rerank_done": {
          // Fold BM25 / dense / RRF / cross-encoder into a single semantic step.
          // Detail text is intentionally simple ("Selected top N passages") — the
          // funnel internals are misleading without explaining all four stages.
          // Payload starts empty; sub_answer_start later attaches the actual
          // top-N chunks so the step expands into a passage list.
          t.pipeline = { ...t.pipeline, rerankMs: e.data.latency_ms };
          const perSq = e.data.per_subquery || [];
          t.subqueries = t.subqueries.map((sq) => {
            const r = perSq.find((p) => p.index === sq.index);
            if (!r) return sq;
            const detail = `Selected top ${r.top_k} passage${r.top_k === 1 ? "" : "s"}`;
            return {
              ...sq,
              steps: [
                ...sq.steps,
                step(
                  "rerank",
                  "Picked best evidence",
                  detail,
                  "done",
                  { chunks: [] },
                  e.data.latency_ms,
                ),
              ],
            };
          });
          break;
        }
        case "sub_answer_start": {
          const idx = e.data.index;
          const sq = t.subqueries[idx];
          if (!sq) break;
          t.subqueries = t.subqueries.map((s) =>
            s.index !== idx
              ? s
              : {
                  ...s,
                  chunks: e.data.chunks,
                  citations: e.data.citations,
                  bm25Top: e.data.bm25_top,
                  denseTop: e.data.dense_top,
                  // Backfill chunks into the rerank step's payload so its
                  // expandable body shows the actual top-N passages.
                  steps: [
                    ...s.steps.map((st) =>
                      st.kind === "rerank"
                        ? { ...st, payload: { chunks: e.data.chunks } }
                        : st,
                    ),
                    step("generate", "Drafted answer", "writing…", "running"),
                  ],
                },
          );
          // Accumulate citations on the turn (deduped by URL across subqueries)
          const seen = new Set(t.citations.map((c) => c.url));
          const merged = [...t.citations];
          for (const c of e.data.citations) {
            if (!seen.has(c.url)) {
              seen.add(c.url);
              merged.push({ ...c, num: merged.length + 1 });
            }
          }
          t.citations = merged;
          break;
        }
        case "sub_answer_token": {
          const idx = e.data.index;
          t.subqueries = t.subqueries.map((sq) =>
            sq.index !== idx ? sq : { ...sq, tokens: sq.tokens + e.data.text },
          );
          break;
        }
        case "sub_answer_done": {
          const idx = e.data.index;
          t.subqueries = t.subqueries.map((sq) =>
            sq.index !== idx
              ? sq
              : {
                  ...sq,
                  done: true,
                  cancelled: e.data.cancelled,
                  errorMsg: e.data.error,
                  latencyMs: e.data.latency_ms,
                  completedAt: Date.now(),
                  steps: sq.steps.map((st) =>
                    st.kind === "generate" && st.status === "running"
                      ? {
                          ...st,
                          status: e.data.error ? "failed" : "done",
                          label: "Drafted answer",
                          detail: e.data.error ? "failed" : `${wordCount(sq.tokens)} word${wordCount(sq.tokens) === 1 ? "" : "s"}`,
                          latencyMs: e.data.latency_ms,
                        }
                      : st,
                  ),
                },
          );
          // When all sub-answers are done, kick off the combining phase
          const allDone = t.subqueries.every((sq) => sq.done);
          if (allDone && !t.combiningStatus) {
            const tNow = Date.now();
            t.combiningStatus = "running";
            t.combiningStartedAt = tNow;
            // For single-Q there's no real synthesis call — make combining instant
            // and start finalizing. The `done` event will close it out.
            if (t.subqueries.length === 1) {
              t.combiningStatus = "done";
              t.combiningCompletedAt = tNow;
              t.finalStatus = "running";
              t.finalStartedAt = tNow;
            }
          }
          break;
        }
        case "synthesis_start": {
          const tNow = Date.now();
          t.synthesizing = true;
          t.combiningStatus = "done";
          t.combiningCompletedAt = tNow;
          t.finalStatus = "running";
          t.finalStartedAt = tNow;
          break;
        }
        case "token": {
          t.synthesisMd += e.data.text;
          break;
        }
        case "done": {
          const tNow = Date.now();
          t.totalLatencyMs = e.data.total_latency_ms;
          t.citations = e.data.citations;
          // Build display-time renumber so [N]s start at 1 even after backend
          // reconciliation drops never-cited entries. Keep Citation.num intact —
          // render layers translate via citationRemap.
          const remap: Record<number, number> = {};
          (e.data.citations || []).forEach((c, i) => {
            remap[c.num] = i + 1;
          });
          t.citationRemap = remap;
          if (Array.isArray(e.data.followups) && e.data.followups.length > 0) {
            t.followups = e.data.followups.slice(0, 3);
          }
          t.status = "done";
          t.synthesizing = false;
          t.combiningStatus = "done";
          t.finalStatus = "done";
          if (!t.combiningCompletedAt) t.combiningCompletedAt = tNow;
          if (!t.finalStartedAt) t.finalStartedAt = tNow;
          t.finalCompletedAt = tNow;
          if (!t.synthesisMd && t.subqueries.length === 1) {
            t.synthesisMd = t.subqueries[0].tokens;
          }
          break;
        }
        case "error": {
          // Translate machine reason → friendly copy, then mark every still-running
          // step / subquery as failed so spinners stop dead.
          t.status = "error";
          t.errorMsg = friendlyError(e.data.reason as ErrorReason | undefined, e.data.message);
          t.synthesizing = false;
          if (t.combiningStatus === "running") t.combiningStatus = "done";
          if (t.finalStatus === "running") t.finalStatus = "done";
          t.subqueries = t.subqueries.map((sq) => {
            if (sq.done) return sq;
            const steps = sq.steps.map((st) =>
              st.status === "running" ? { ...st, status: "failed" as const } : st,
            );
            return { ...sq, steps, done: true, errorMsg: sq.errorMsg || t.errorMsg };
          });
          break;
        }
      }

      turns[i] = t;
      return { turns };
    });
  },
}));

function mutateTurn(
  setter: any,
  turnId: string,
  fn: (t: Turn) => void,
) {
  setter((s: ChatStore) => {
    const turns = s.turns.map((t) => {
      if (t.id !== turnId) return t;
      const copy = { ...t };
      fn(copy);
      return copy;
    });
    return { turns };
  });
}

/**
 * Rebuild the full live-trace step sequence from persisted data so historical /
 * eval turns render IDENTICALLY to a fresh streamed run. Labels and payloads
 * mirror chatStore's SSE handlers exactly.
 *
 * When the persisted trace carries per-sub-query slices (`extract_stats`,
 * `chunk_stats`, `embed_count` — added in 2026-05), the rich live trace is
 * reconstructed: status chips on the source list, per-sub-query chunk drop
 * breakdowns, and per-sub-query passage counts. Older traces fall back to the
 * coarse global counts derived from `latency_breakdown`.
 */
function rehydrateSteps(
  t: {
    urls: any[];
    chunks: any[];
    answer?: string;
    latency_ms: number;
    extract_stats?: any;
    chunk_stats?: any;
    embed_count?: number | null;
  },
  br: Record<string, any>,
): ReasoningStep[] {
  const steps: ReasoningStep[] = [];
  const urlCount = t.urls?.length || 0;
  const topCount = t.chunks?.length || 0;
  const wc = (t.answer || "").trim() ? (t.answer || "").trim().split(/\s+/).length : 0;

  if (urlCount > 0) {
    steps.push(step(
      "search", "Searched the web",
      `Found ${urlCount} source${urlCount === 1 ? "" : "s"}`,
      "done", { urls: t.urls }, br?.search_ms,
    ));
  }

  // Extract — prefer the persisted per-sub-query slice for the rich shape.
  const ex = t.extract_stats as
    | { pages: any[]; succeeded: number; attempted: number; failures: any[] }
    | null
    | undefined;
  if (ex && Array.isArray(ex.pages)) {
    const failSummary = summariseFailures(ex.failures);
    const detail = (ex.failures?.length ?? 0) > 0
      ? `Read ${ex.succeeded} of ${ex.attempted} pages — ${ex.failures.length} skipped (${failSummary})`
      : `Read ${ex.succeeded} page${ex.succeeded === 1 ? "" : "s"}`;
    steps.push(step(
      "extract", "Read pages", detail, "done",
      { pages: ex.pages, failures: ex.failures, attempted: ex.attempted, succeeded: ex.succeeded, enriched: true },
      br?.extract_ms,
    ));
  } else {
    const pageCount = br?.pages_count ?? urlCount;
    if (pageCount > 0) {
      steps.push(step(
        "extract", "Read pages",
        `Read ${pageCount} page${pageCount === 1 ? "" : "s"}`,
        "done", null, br?.extract_ms,
      ));
    }
  }

  // Chunk — prefer per-sub-query stats for descriptive text and counts.
  const cs = t.chunk_stats as
    | { count: number; pages: number; stats: { garbage_dropped: number; min_body_dropped: number; dedup_dropped: number; kept: number } }
    | null
    | undefined;
  if (cs) {
    const dropped = cs.stats.garbage_dropped + cs.stats.min_body_dropped + cs.stats.dedup_dropped;
    const detail = dropped > 0
      ? `Built ${cs.count} passages (dropped ${dropped}: ${cs.stats.garbage_dropped} boilerplate, ${cs.stats.min_body_dropped} short, ${cs.stats.dedup_dropped} duplicate)`
      : `Built ${cs.count} passage${cs.count === 1 ? "" : "s"}`;
    steps.push(step("chunk", "Split into passages", detail, "done", null, br?.chunk_ms));
    const embedN = t.embed_count ?? cs.count;
    steps.push(step(
      "embed", "Indexed passages",
      `${embedN} passage${embedN === 1 ? "" : "s"} ready for ranking`,
      "done", null, br?.embed_ms,
    ));
  } else {
    const passageCount = br?.chunks_count ?? 0;
    if (passageCount > 0) {
      steps.push(step(
        "chunk", "Split into passages",
        `Built ${passageCount} passage${passageCount === 1 ? "" : "s"}`,
        "done", null, br?.chunk_ms,
      ));
      steps.push(step(
        "embed", "Indexed passages",
        `${passageCount} passage${passageCount === 1 ? "" : "s"} ready for ranking`,
        "done", null, br?.embed_ms,
      ));
    }
  }

  if (topCount > 0) {
    steps.push(step(
      "rerank", "Picked best evidence",
      `Selected top ${topCount} passage${topCount === 1 ? "" : "s"}`,
      "done", { chunks: t.chunks }, br?.rerank_ms ?? br?.retrieve_ms,
    ));
  }
  steps.push(step(
    "generate", "Drafted answer",
    `${wc} word${wc === 1 ? "" : "s"}`,
    "done", null, t.latency_ms,
  ));
  return steps;
}

function wordCount(s: string): number {
  return s.trim() ? s.trim().split(/\s+/).length : 0;
}
