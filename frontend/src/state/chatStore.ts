import { create } from "zustand";
import { streamSearch } from "../lib/sse";
import { api } from "../lib/api";
import type {
  ChunkDict,
  PersistedSession,
  ReasoningStep,
  SessionListItem,
  SseEvent,
  SubqueryState,
  Turn,
} from "../lib/types";
import { ms } from "../lib/format";

const SESSION_KEY = "wsr_session_id";

function newSessionId(): string {
  const s = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, s);
  return s;
}

function readSessionId(): string {
  return localStorage.getItem(SESSION_KEY) || newSessionId();
}

function newTurn(question: string): Turn {
  return {
    id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
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
  submitQuery: (q: string) => Promise<void>;
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
    localStorage.setItem(SESSION_KEY, id);
    try {
      const data: PersistedSession = await api.getSession(id);
      const turns: Turn[] = data.messages.map((m) => {
        const subqueries: SubqueryState[] = (m.traces || []).map((t) => ({
          index: t.index,
          query: t.query,
          steps: rehydrateSteps(t),
          tokens: t.answer || "",
          done: true,
          chunks: t.chunks || [],
          urls: t.urls || [],
          citations: [],
          latencyMs: t.latency_ms,
        }));

        const turn: Turn = {
          id: `hydrated-${m.id}`,
          question: m.question,
          status: "done",
          subQueries: m.sub_queries || [],
          subqueries,
          pipeline: {
            decomposeMs: m.latency_breakdown?.decompose_ms,
            searchMs: m.latency_breakdown?.search_ms,
            extractMs: m.latency_breakdown?.extract_ms,
            chunkMs: m.latency_breakdown?.chunk_ms,
            retrieveMs: m.latency_breakdown?.retrieve_ms,
            totalChunks: m.chunks?.length,
          },
          synthesisMd: m.answer,
          synthesizing: false,
          citations: m.citations || [],
          totalLatencyMs: m.total_latency_ms,
          createdAt: new Date(m.created_at).getTime(),
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

  submitQuery: async (q: string) => {
    if (!q.trim() || get().isStreaming) return;
    const controller = new AbortController();
    const turn = newTurn(q.trim());
    const sessionId = get().sessionId;
    const nowIso = new Date().toISOString();
    set((s) => {
      // Optimistically add or update this session in the sidebar list
      const optimistic: SessionListItem = {
        session_id: sessionId,
        title: q.trim().slice(0, 60),
        message_count: 1,
        last_active: nowIso,
        created_at: nowIso,
      };
      const others = s.sessions.filter((x) => x.session_id !== sessionId);
      return {
        turns: [...s.turns, turn],
        isStreaming: true,
        controller,
        sessions: [optimistic, ...others],
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
        });
      }
    } finally {
      set({ isStreaming: false, controller: null });
      // Refresh sidebar so the new session shows up
      void get().refreshSessions();
    }
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
        case "decompose_done": {
          t.subQueries = e.data.sub_queries;
          t.pipeline = { ...t.pipeline, decomposeMs: e.data.latency_ms, decomposeMode: e.data.mode };
          // Pre-create subquery states
          t.subqueries = e.data.sub_queries.map((q, idx) => newSubqueryState(idx, q));
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
          t.pipeline = { ...t.pipeline, extractMs: e.data.latency_ms, pages: e.data.pages };
          t.subqueries = t.subqueries.map((sq) => ({
            ...sq,
            steps: [
              ...sq.steps,
              step(
                "extract",
                "Read pages",
                `Read ${e.data.pages.length} page${e.data.pages.length === 1 ? "" : "s"}`,
                "done",
                { pages: e.data.pages },
                e.data.latency_ms,
              ),
            ],
          }));
          break;
        }
        case "chunk_done": {
          t.pipeline = { ...t.pipeline, chunkMs: e.data.latency_ms, totalChunks: e.data.count, perPageChunks: e.data.per_page };
          t.subqueries = t.subqueries.map((sq) => ({
            ...sq,
            steps: [
              ...sq.steps,
              step(
                "chunk",
                "Split into passages",
                `Built ${e.data.count} passage${e.data.count === 1 ? "" : "s"}`,
                "done",
                { perPage: e.data.per_page },
                e.data.latency_ms,
              ),
            ],
          }));
          break;
        }
        case "embed_done": {
          t.pipeline = { ...t.pipeline, embedMs: e.data.latency_ms, embedDevice: e.data.device };
          t.subqueries = t.subqueries.map((sq) => ({
            ...sq,
            steps: [
              ...sq.steps,
              step(
                "embed",
                "Indexed passages",
                `${e.data.candidate_count} passage${e.data.candidate_count === 1 ? "" : "s"} ready for ranking`,
                "done",
                null,
                e.data.latency_ms,
              ),
            ],
          }));
          break;
        }
        case "retrieve_done": {
          t.pipeline = { ...t.pipeline, retrieveMs: e.data.latency_ms };
          break;
        }
        case "rerank_done": {
          // Fold BM25 / dense / RRF / cross-encoder rerank into a single semantic step.
          t.pipeline = { ...t.pipeline, rerankMs: e.data.latency_ms };
          const perSq = e.data.per_subquery || [];
          t.subqueries = t.subqueries.map((sq) => {
            const r = perSq.find((p) => p.index === sq.index);
            if (!r) return sq;
            return {
              ...sq,
              steps: [
                ...sq.steps,
                step(
                  "rerank",
                  "Picked best evidence",
                  `Selected top ${r.top_k} passage${r.top_k === 1 ? "" : "s"}`,
                  "done",
                  null,
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
                  steps: [
                    ...s.steps,
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
            t.combiningStatus = "running";
            // For single-Q there's no real synthesis call — make combining instant
            // and start finalizing. The `done` event will close it out.
            if (t.subqueries.length === 1) {
              t.combiningStatus = "done";
              t.finalStatus = "running";
            }
          }
          break;
        }
        case "synthesis_start": {
          t.synthesizing = true;
          t.combiningStatus = "done";
          t.finalStatus = "running";
          break;
        }
        case "token": {
          t.synthesisMd += e.data.text;
          break;
        }
        case "done": {
          t.totalLatencyMs = e.data.total_latency_ms;
          t.citations = e.data.citations;
          t.status = "done";
          t.synthesizing = false;
          t.combiningStatus = "done";
          t.finalStatus = "done";
          if (!t.synthesisMd && t.subqueries.length === 1) {
            t.synthesisMd = t.subqueries[0].tokens;
          }
          break;
        }
        case "error": {
          t.status = "error";
          t.errorMsg = e.data.message;
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

function rehydrateSteps(t: { urls: any[]; chunks: any[]; latency_ms: number }): ReasoningStep[] {
  const steps: ReasoningStep[] = [];
  if (t.urls?.length) {
    steps.push(step("search", "Search", `${t.urls.length} URLs`, "done", { urls: t.urls }));
  }
  if (t.chunks?.length) {
    steps.push(step("rerank", "Cross-encoder rerank", `top ${t.chunks.length}`, "done", { chunks: t.chunks }));
  }
  steps.push(step("generate", "Generate", `${ms(t.latency_ms)}`, "done", null, t.latency_ms));
  return steps;
}

function wordCount(s: string): number {
  return s.trim() ? s.trim().split(/\s+/).length : 0;
}
