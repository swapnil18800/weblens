import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowDown, Loader2 } from "lucide-react";
import { useChat } from "../state/chatStore";
import ChatTurn from "./ChatTurn";

export default function ChatThread() {
  const allTurns = useChat((s) => s.turns);
  const selectedVersion = useChat((s) => s.selectedVersion);
  const loadingSessionId = useChat((s) => s.loadingSessionId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastTurnIdRef = useRef<string | null>(null);
  const prevLoadingRef = useRef<string | null>(null);

  // Collapse version-group siblings into a single visible turn per group.
  // Order is preserved by the FIRST appearance of each group; the displayed
  // sibling is whichever index is selected (defaulting to the latest).
  const turns = useMemo(() => {
    const groupSiblings = new Map<string, typeof allTurns>();
    for (const t of allTurns) {
      const arr = groupSiblings.get(t.versionGroupId) || [];
      arr.push(t);
      groupSiblings.set(t.versionGroupId, arr);
    }
    const out: typeof allTurns = [];
    const seen = new Set<string>();
    for (const t of allTurns) {
      if (seen.has(t.versionGroupId)) continue;
      seen.add(t.versionGroupId);
      const sibs = (groupSiblings.get(t.versionGroupId) || []).slice().sort(
        (a, b) => a.versionIndex - b.versionIndex,
      );
      const sel = selectedVersion[t.versionGroupId];
      const idx = sel != null && sel >= 0 && sel < sibs.length ? sel : sibs.length - 1;
      out.push(sibs[idx]);
    }
    return out;
  }, [allTurns, selectedVersion]);

  // New turn → scroll the article to the top edge of the viewport.
  //
  // The previous approach used scrollIntoView({behavior:"smooth"}). Two problems:
  //   1. SSE-driven layout growth (decompose / search rows appearing) shifted
  //      the target while smooth-scroll was still animating, leaving the bubble
  //      "in the middle".
  //   2. Two smooth-scroll calls in a row cancel each other.
  //
  // New approach: compute the article's offset relative to the scroll container
  // and set scrollTop directly. Schedule a smooth pass first, then two instant
  // re-snaps as later SSE events grow the article (typical settle: 250–700 ms).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || turns.length === 0) return;
    const last = turns[turns.length - 1];
    if (last.id === lastTurnIdRef.current) return;
    lastTurnIdRef.current = last.id;

    const snap = (smooth: boolean) => {
      const node = document.querySelector<HTMLElement>(`[data-turn-id="${last.id}"]`);
      if (!node) {
        el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
        return;
      }
      const target = Math.max(0, node.offsetTop - 8);
      el.scrollTo({ top: target, behavior: smooth ? "smooth" : "auto" });
    };

    requestAnimationFrame(() => snap(true));
    // Layout settles in two waves: decompose fires fast (~50–200 ms after submit),
    // search/extract land later. Re-snap instantly to ride out both.
    const t1 = setTimeout(() => snap(false), 320);
    const t2 = setTimeout(() => snap(false), 800);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [turns]);

  // Session switch: position the LAST turn at the top of the viewport (not the
  // bottom of the page). Mirrors the new-turn snap so loaded history feels
  // identical to a fresh stream — the question is visible at the top, with the
  // answer scrollable below. Double-rAF so child rows have laid out first.
  useEffect(() => {
    const wasLoading = prevLoadingRef.current;
    prevLoadingRef.current = loadingSessionId;
    if (wasLoading && !loadingSessionId && turns.length > 0) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const el = scrollRef.current;
          if (!el) return;
          const last = turns[turns.length - 1];
          const node = document.querySelector<HTMLElement>(`[data-turn-id="${last.id}"]`);
          if (!node) {
            el.scrollTop = el.scrollHeight;
            return;
          }
          el.scrollTop = Math.max(0, node.offsetTop - 8);
        });
      });
    }
  }, [loadingSessionId, turns.length]);

  /* ── Scroll-to-latest floating button ──────────────────────────────────────
     With the tail spacer, `scrollHeight` lands inside empty space far below
     the last turn — meaningless. Anchor the button to the LAST TURN's bottom
     edge: show it when the user has scrolled away (the last turn isn't in
     view), and on click jump back to it.
  */
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const check = () => {
      if (turns.length === 0) return setShowScrollBtn(false);
      const last = turns[turns.length - 1];
      const node = document.querySelector<HTMLElement>(`[data-turn-id="${last.id}"]`);
      if (!node) return setShowScrollBtn(false);
      const lastBottom = node.offsetTop + node.offsetHeight;
      const viewportBottom = el.scrollTop + el.clientHeight;
      setShowScrollBtn(viewportBottom < lastBottom - 80);
    };
    el.addEventListener("scroll", check, { passive: true });
    check();
    return () => el.removeEventListener("scroll", check);
  }, [turns]);

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (!el || turns.length === 0) return;
    const last = turns[turns.length - 1];
    const node = document.querySelector<HTMLElement>(`[data-turn-id="${last.id}"]`);
    if (!node) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      return;
    }
    el.scrollTo({ top: Math.max(0, node.offsetTop - 8), behavior: "smooth" });
  };

  /* ── Loading skeleton ──────────────────────────────────────────────────── */
  if (loadingSessionId) {
    return (
      <div className="flex-1 overflow-y-auto scroll-fat relative">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
          <div className="flex items-center gap-2 text-sm text-neutral-400 mb-6">
            <Loader2 className="w-4 h-4 animate-spin text-accent" />
            Loading conversation…
          </div>
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="surface rounded-xl p-4 animate-pulse">
                <div className="h-3 bg-white/10 rounded-full w-2/3 mb-2" />
                <div className="h-3 bg-white/5 rounded-full w-5/6 mb-2" />
                <div className="h-3 bg-white/5 rounded-full w-4/6" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 relative min-h-0 flex flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto scroll-fat">
        {turns.map((t) => <ChatTurn key={t.id} turn={t} />)}
        {/*
          Tail spacer — guarantees the last turn can ALWAYS be scrolled to the
          top of the viewport, even when the conversation is short.
          Without this, `scrollTop = node.offsetTop - 8` clamps to
          `scrollHeight - clientHeight` and the new question lands mid-screen.
          Sized to viewport minus the docked composer (~200px).
        */}
        <div aria-hidden style={{ height: "calc(100vh - 200px)" }} />
      </div>

      {/* Floating scroll-to-bottom button */}
      <AnimatePresence>
        {showScrollBtn && (
          <motion.button
            key="scroll-btn"
            initial={{ opacity: 0, scale: 0.85, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.85, y: 6 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            onClick={scrollToBottom}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20
                       w-10 h-10 rounded-full
                       bg-white/[0.04] hover:bg-white/[0.08] backdrop-blur-md
                       border border-white/10 text-neutral-200
                       flex items-center justify-center
                       transition-colors"
            title="Scroll to bottom"
            aria-label="Scroll to bottom"
          >
            <ArrowDown className="w-4 h-4" />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
