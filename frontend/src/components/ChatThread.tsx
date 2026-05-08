import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { useChat } from "../state/chatStore";
import ChatTurn from "./ChatTurn";

export default function ChatThread() {
  const turns = useChat((s) => s.turns);
  const loadingSessionId = useChat((s) => s.loadingSessionId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastTurnIdRef = useRef<string | null>(null);

  // When a NEW turn appears, scroll so its question is at the top of the visible area.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || turns.length === 0) return;
    const last = turns[turns.length - 1];
    if (last.id === lastTurnIdRef.current) return;
    lastTurnIdRef.current = last.id;
    requestAnimationFrame(() => {
      const node = document.querySelector<HTMLElement>(`[data-turn-id="${last.id}"]`);
      if (node) {
        node.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      }
    });
  }, [turns]);

  if (loadingSessionId) {
    return (
      <div className="flex-1 overflow-y-auto scroll-fat">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
          <div className="flex items-center gap-2 text-sm text-neutral-300 mb-6">
            <Loader2 className="w-4 h-4 animate-spin text-accent" />
            Loading conversation…
          </div>
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="surface rounded-lg p-4 animate-pulse">
                <div className="h-3 bg-white/10 rounded w-2/3 mb-2" />
                <div className="h-3 bg-white/5 rounded w-5/6 mb-2" />
                <div className="h-3 bg-white/5 rounded w-4/6" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto scroll-fat">
      {turns.map((t) => (
        <ChatTurn key={t.id} turn={t} />
      ))}
    </div>
  );
}
