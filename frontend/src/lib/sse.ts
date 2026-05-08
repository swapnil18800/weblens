// Streaming POST → SSE parser. We can't use EventSource because we need to POST a body.
// Returns a promise that resolves on `done` event, rejects on AbortError or HTTP error.

import { API_BASE } from "./api";
import type { SseEvent } from "./types";

export interface StreamSearchOptions {
  query: string;
  sessionId: string;
  signal: AbortSignal;
  onEvent: (e: SseEvent) => void;
}

export async function streamSearch(opts: StreamSearchOptions): Promise<void> {
  const res = await fetch(`${API_BASE}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: opts.query, session_id: opts.sessionId }),
    signal: opts.signal,
  });

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE: events separated by \n\n
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      let eventName = "";
      let dataStr = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) eventName = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataStr = line.slice(6);
      }
      if (!eventName || !dataStr) continue;
      try {
        const data = JSON.parse(dataStr);
        opts.onEvent({ event: eventName, data } as SseEvent);
      } catch {
        // Ignore malformed events
      }
    }
  }
}
