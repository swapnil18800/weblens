import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useChat } from "../state/chatStore";
import { bucketTime, relativeTime } from "../lib/format";
import type { SessionListItem } from "../lib/types";

const GROUP_KEY = (b: string) => `wsr_grp_${b.replace(/\s+/g, "_")}`;
const ORDER = ["Today", "Yesterday", "Last 7 days", "Older"] as const;
const WIDTH_KEY = "wsr_sidebar_width";
const MIN_WIDTH = 200;
const MAX_WIDTH = 540;
const DEFAULT_WIDTH = 248;

export default function Sidebar() {
  const sessions = useChat((s) => s.sessions);
  const refresh = useChat((s) => s.refreshSessions);
  const sessionId = useChat((s) => s.sessionId);
  const loadSession = useChat((s) => s.loadSession);
  const deleteSession = useChat((s) => s.deleteSession);
  const sidebarOpen = useChat((s) => s.sidebarOpen);
  const setSidebarOpen = useChat((s) => s.setSidebarOpen);
  const startNewChat = useChat((s) => s.startNewChat);

  const [confirming, setConfirming] = useState<string | null>(null);
  const [width, setWidth] = useState<number>(() => {
    const stored = Number(localStorage.getItem(WIDTH_KEY));
    return stored >= MIN_WIDTH && stored <= MAX_WIDTH ? stored : DEFAULT_WIDTH;
  });
  const draggingRef = useRef(false);
  const widthRef = useRef(width);
  widthRef.current = width;

  // Auto-collapse on mobile only
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const onChange = () => setSidebarOpen(!mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [setSidebarOpen]);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 30_000);
    return () => clearInterval(t);
  }, [refresh]);

  // Drag-to-resize handle (mounted once; reads cursor X live)
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const w = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX));
      setWidth(w);
    };
    const onUp = () => {
      if (draggingRef.current) {
        draggingRef.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        localStorage.setItem(WIDTH_KEY, String(widthRef.current));
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const grouped = useMemo(() => {
    const buckets: Record<string, SessionListItem[]> = {};
    for (const s of sessions) {
      const b = bucketTime(s.last_active || s.created_at);
      (buckets[b] ||= []).push(s);
    }
    return ORDER.filter((k) => buckets[k]?.length).map((k) => [k, buckets[k]] as const);
  }, [sessions]);

  return (
    <>
      {/* Mobile backdrop */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="fixed inset-0 bg-black/40 z-30 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Collapsed state — desktop edge rail */}
      {!sidebarOpen && (
        <div className="hidden md:flex fixed left-0 top-1/2 -translate-y-1/2 z-30 flex-col gap-1.5">
          <button
            onClick={() => setSidebarOpen(true)}
            className="w-5 h-14 rounded-r-md bg-surface border border-l-0 hairline
                       flex items-center justify-center
                       hover:bg-white/[0.06] hover:w-6 transition-all
                       text-neutral-300 hover:text-neutral-100 shadow-sm"
            title="Show conversations"
            aria-label="Show conversations"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => startNewChat()}
            className="w-5 h-14 rounded-r-md bg-surface border border-l-0 hairline
                       flex items-center justify-center
                       hover:bg-white/[0.06] hover:w-6 transition-all
                       text-neutral-300 hover:text-accent shadow-sm"
            title="New Chat"
            aria-label="New Chat"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Expanded sidebar — proper static flex item on desktop */}
      <aside
        className={`fixed md:relative inset-y-0 left-0 z-40 max-w-[85vw]
                   border-r hairline bg-surface flex-col
                   ${sidebarOpen ? "flex" : "hidden md:hidden"}`}
        style={{
          width: sidebarOpen ? `${width}px` : 0,
        }}
      >
        {/* Top: + New session */}
        <div className="px-3 pt-3 pb-2">
          <button
            onClick={() => startNewChat()}
            className="w-full inline-flex items-center justify-center gap-1.5
                       bg-accent/15 hover:bg-accent/25 text-accent
                       rounded-md px-3 py-2 text-sm font-medium transition-colors"
            title="Start a new session"
          >
            <Plus className="w-4 h-4" />
            New session
          </button>
        </div>

        {/* Conversations header */}
        <div className="px-3 pt-4 pb-1 flex items-center justify-between">
          <span className="text-2xs uppercase tracking-wider text-neutral-400">
            Conversations
          </span>
        </div>

        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto scroll-fat min-h-0">
          {grouped.length === 0 && (
            <div className="px-3 py-4 text-2xs text-neutral-400">No conversations yet.</div>
          )}
          {grouped.map(([bucket, items]) => (
            <SessionGroup
              key={bucket}
              bucket={bucket}
              items={items}
              activeId={sessionId}
              confirming={confirming}
              setConfirming={setConfirming}
              onPick={loadSession}
              onDelete={deleteSession}
            />
          ))}
        </div>

        {/* Right-edge drag handle (desktop only) — wide hit-area but visually thin */}
        <div
          onMouseDown={startDrag}
          className="hidden md:block absolute top-0 right-0 h-full w-1.5 -mr-[3px]
                     cursor-col-resize hover:bg-accent/40 active:bg-accent/60 transition-colors z-20"
          aria-label="Resize sidebar"
          role="separator"
          aria-orientation="vertical"
        />

        {/* Collapse chevron — protrudes from right edge */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="hidden md:flex absolute top-1/2 right-0 translate-x-1/2 -translate-y-1/2
                     w-5 h-14 z-30 rounded-r-md bg-surface border border-l-0 hairline
                     items-center justify-center shadow-sm
                     hover:bg-white/[0.06] hover:w-6 transition-all
                     text-neutral-300 hover:text-neutral-100"
          title="Hide conversations"
          aria-label="Hide conversations"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </button>
      </aside>
    </>
  );
}

interface GroupProps {
  bucket: string;
  items: SessionListItem[];
  activeId: string;
  confirming: string | null;
  setConfirming: (id: string | null) => void;
  onPick: (id: string) => void | Promise<void>;
  onDelete: (id: string) => void | Promise<void>;
}

function SessionGroup({ bucket, items, activeId, confirming, setConfirming, onPick, onDelete }: GroupProps) {
  const key = GROUP_KEY(bucket);
  const [open, setOpen] = useState<boolean>(() => {
    const stored = localStorage.getItem(key);
    if (stored === null) return bucket === "Today";
    return stored === "1";
  });
  useEffect(() => { localStorage.setItem(key, open ? "1" : "0"); }, [key, open]);

  return (
    <div className="py-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-1.5 flex items-center gap-1.5 text-2xs
                   tracking-wider text-neutral-300 font-semibold
                   hover:bg-white/[0.02] transition-colors"
      >
        {open
          ? <ChevronLeft className="w-3 h-3 text-neutral-400 rotate-[-90deg]" />
          : <ChevronRight className="w-3 h-3 text-neutral-400" />}
        <span className="uppercase">{bucket}</span>
        <span className="ml-auto text-2xs text-neutral-500 font-mono normal-case">{items.length}</span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="overflow-hidden"
          >
            {items.map((s) => {
              const active = s.session_id === activeId;
              const isConfirming = confirming === s.session_id;
              return (
                <li
                  key={s.session_id}
                  className={`group relative flex items-start gap-2 px-3 py-2 cursor-pointer transition-colors ${
                    active ? "bg-white/[0.05] border-l-2 border-accent" : "hover:bg-white/[0.025]"
                  }`}
                  onClick={() => !isConfirming && onPick(s.session_id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-neutral-100 truncate" title={s.title || "Untitled"}>
                      {s.title || "Untitled"}
                    </div>
                    <div className="text-2xs text-neutral-400 mt-0.5 flex items-center gap-2">
                      <span>{s.message_count} msg{s.message_count !== 1 ? "s" : ""}</span>
                      <span>·</span>
                      <span>{relativeTime(s.last_active || s.created_at)}</span>
                    </div>
                  </div>
                  {isConfirming ? (
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="text-2xs text-bad hover:text-bad/80 px-1.5 py-0.5 rounded"
                        onClick={() => {
                          setConfirming(null);
                          void onDelete(s.session_id);
                        }}
                      >
                        delete
                      </button>
                      <button
                        className="text-2xs text-neutral-300 hover:text-neutral-100 px-1.5 py-0.5 rounded"
                        onClick={() => setConfirming(null)}
                      >
                        cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      className="md:opacity-0 md:group-hover:opacity-100 transition-opacity icon-btn w-6 h-6 -mr-1"
                      title="Delete session"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirming(s.session_id);
                      }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
