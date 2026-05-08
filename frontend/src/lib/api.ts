// REST + SSE wrappers. In dev, vite proxies /api → http://127.0.0.1:8765.
// In production single-process mode, both are served from the same origin.

import type { EvalRunDetail, EvalRunSummary, PersistedSession, SessionListItem } from "./types";

export const API_BASE = "";

async function jsonGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export interface HealthResponse {
  status: "ok";
  env: string;
  dev_mode: boolean;
  version: string;
}

export const api = {
  health: () => jsonGet<HealthResponse>("/api/health"),
  listSessions: () => jsonGet<SessionListItem[]>("/api/sessions"),
  getSession: (id: string) => jsonGet<PersistedSession>(`/api/sessions/${id}`),
  deleteSession: async (id: string) => {
    const res = await fetch(`${API_BASE}/api/sessions/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  },
  evalRuns: () => jsonGet<EvalRunSummary[]>("/api/eval/results"),
  evalRunDetail: (runId: string) => jsonGet<EvalRunDetail>(`/api/eval/results/${runId}`),
  evalQuestions: (set: string) => jsonGet<any>(`/api/eval/questions?set=${encodeURIComponent(set)}`),
};
