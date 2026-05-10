import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, Plus, Trash2 } from "lucide-react";
import { useChat } from "../state/chatStore";
import { bucketTime, relativeTime } from "../lib/format";
import type { SessionListItem } from "../lib/types";

const GROUP_KEY = (b: string) => `wsr_grp_${b.replace(/\s+/g, "_")}`;
const ORDER = ["Today", "Yesterday", "Last 7 days", "Older"] as const;
const WIDTH_KEY = "wsr_sidebar_width";
const MIN_WIDTH = 200;
const MAX_WIDTH = 540;
const DEFAULT_WIDTH = 248;
// Match the header height (h-12) so the rail/protrusion never overlap the logo.
const HEADER_HEIGHT_PX = 48;

export default function Sidebar() {
  const sessions    = useChat((s) => s.sessions);
  const refresh     = useChat((s) => s.refreshSessions);
  const sessionId   = useChat((s) => s.sessionId);
  const loadSession = useChat((s) => s.loadSession);
  const deleteSession = useChat((s) => s.deleteSession);
  const sidebarOpen = useChat((s) => s.sidebarOpen);
  const setSidebarOpen = useChat((s) => s.setSidebarOpen);
  const startNewChat = useChat((s) => s.startNewChat);

  const [confirming, setConfirming] = useState<string | null>(null);
  const [width, setWidth] = useState<number>(() => {
    const v = Number(localStorage.getItem(WIDTH_KEY));
    return v >= MIN_WIDTH && v <= MAX_WIDTH ? v : DEFAULT_WIDTH;
  });
  const draggingRef = useRef(false);
  const widthRef = useRef(width);
  widthRef.current = width;

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

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX)));
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem(WIDTH_KEY, String(widthRef.current));
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
            transition={{ duration: 0.14 }}
            className="fixed inset-0 bg-black/50 z-30 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* COLLAPSED rail — desktop only. Below header so it never overlaps the logo. */}
      {!sidebarOpen && (
        <div
          className="hidden md:flex fixed left-0 z-30 flex-col gap-1.5 px-1 py-2"
          style={{ top: `${HEADER_HEIGHT_PX + 8}px` }}
        >
          {/* Toggle (now points outward → expand) */}
          <ProtrudingToggle
            open={false}
            onClick={() => setSidebarOpen(true)}
            label="Show conversations"
          />
          {/* New chat */}
          <button
            onClick={() => startNewChat()}
            className="w-10 h-10 rounded-xl bg-surface border hairline
                       flex items-center justify-center shadow-sm
                       text-neutral-400 hover:text-accent hover:bg-white/[0.06]
                       transition-all duration-150"
            title="New chat"
            aria-label="New chat"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* EXPANDED sidebar */}
      <aside
        className={`
          fixed md:relative inset-y-0 left-0 z-40 max-w-[85vw]
          border-r hairline bg-surface flex-col
          ${sidebarOpen ? "flex" : "hidden md:flex"}
        `}
        style={{
          width: sidebarOpen ? `${width}px` : 0,
          transition: "width 180ms cubic-bezier(0.16, 1, 0.3, 1)",
          pointerEvents: sidebarOpen ? undefined : "none",
          // Don't apply overflow-hidden to the aside itself — we need the protruding
          // toggle to escape the right edge.
        }}
      >
        {/* Scrollable list — explicit "+ New chat" lives at the top so it's
            discoverable even when the sidebar is wide; the collapsed rail keeps
            its own copy. */}
        <div className="flex-1 overflow-y-auto scroll-fat min-h-0 pt-2">
          <button
            onClick={() => startNewChat()}
            className="mx-2 mb-2 w-[calc(100%-1rem)] flex items-center gap-2 px-3 py-2 rounded-lg
                       border hairline bg-white/[0.02] hover:bg-white/[0.06] hover:border-accent/30
                       text-neutral-200 hover:text-accent transition-colors"
            title="New chat"
          >
            <Plus className="w-4 h-4 shrink-0" />
            <span className="text-sm font-medium">New chat</span>
          </button>
          {grouped.length === 0 && (
            <div className="px-3 py-4 text-2xs text-neutral-500">No conversations yet.</div>
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

        {/* Drag-resize handle */}
        <div
          onMouseDown={startDrag}
          className="hidden md:block absolute top-0 right-0 h-full w-1.5 -mr-[3px]
                     cursor-col-resize hover:bg-accent/30 active:bg-accent/50
                     transition-colors z-10"
          aria-label="Resize sidebar"
          role="separator"
          aria-orientation="vertical"
        />

        {/* PROTRUDING TOGGLE — sits FULLY outside the sidebar with its left edge
            kissing the sidebar's right edge (translateX(100%)), so it never
            overlaps the session list. */}
        {sidebarOpen && (
          <div
            className="hidden md:block absolute right-0 z-30"
            style={{ top: `${HEADER_HEIGHT_PX + 8}px`, transform: "translateX(100%)" }}
          >
            <ProtrudingToggle
              open={true}
              onClick={() => setSidebarOpen(false)}
              label="Collapse conversations"
            />
          </div>
        )}
      </aside>
    </>
  );
}

/**
 * The single toggle button. Same component used for both expanded (points inward, ←)
 * and collapsed (points outward, →) states — the chevron rotates 180° via animation.
 */
function ProtrudingToggle({
  open,
  onClick,
  label,
}: {
  open: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className="w-10 h-10 rounded-xl bg-surface border hairline shadow-md
                 flex items-center justify-center
                 text-neutral-400 hover:text-neutral-100 hover:bg-white/[0.06]
                 transition-all duration-150"
    >
      <motion.span
        animate={{ rotate: open ? 0 : 180 }}
        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
        className="flex items-center justify-center"
      >
        <ChevronLeft className="w-4 h-4" />
      </motion.span>
    </button>
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
    const v = localStorage.getItem(key);
    return v === null ? bucket === "Today" : v === "1";
  });
  useEffect(() => { localStorage.setItem(key, open ? "1" : "0"); }, [key, open]);

  return (
    <div className="py-0.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-1.5 flex items-center gap-1.5 text-2xs
                   tracking-wider text-neutral-400 font-semibold
                   hover:bg-white/[0.02] transition-colors rounded-sm"
      >
        <ChevronLeft
          className={`w-3 h-3 text-neutral-500 transition-transform duration-150 ${open ? "-rotate-90" : "-rotate-180"}`}
        />
        <span className="uppercase">{bucket}</span>
        <span className="ml-auto text-2xs text-neutral-600 font-mono normal-case">{items.length}</span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            {items.map((s) => {
              const active = s.session_id === activeId;
              const isConfirming = confirming === s.session_id;
              return (
                <li
                  key={s.session_id}
                  className={`group relative flex items-start gap-2 px-3 py-2 cursor-pointer transition-colors ${
                    active
                      ? "bg-accent/[0.08] border-l-2 border-accent"
                      : "hover:bg-white/[0.025]"
                  }`}
                  onClick={() => !isConfirming && onPick(s.session_id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-neutral-100 truncate" title={s.title || "Untitled"}>
                      {s.title || "Untitled"}
                    </div>
                    <div className="text-2xs text-neutral-500 mt-0.5 flex items-center gap-1.5">
                      <span>{s.message_count} msg{s.message_count !== 1 ? "s" : ""}</span>
                      <span className="text-neutral-700">·</span>
                      <span>{relativeTime(s.last_active || s.created_at)}</span>
                    </div>
                  </div>
                  {isConfirming ? (
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="text-2xs text-bad hover:text-bad/80 px-1.5 py-0.5 rounded"
                        onClick={() => { setConfirming(null); void onDelete(s.session_id); }}
                      >
                        delete
                      </button>
                      <button
                        className="text-2xs text-neutral-400 hover:text-neutral-100 px-1.5 py-0.5 rounded"
                        onClick={() => setConfirming(null)}
                      >
                        cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      className="md:opacity-0 md:group-hover:opacity-100 transition-opacity icon-btn w-6 h-6 -mr-1"
                      title="Delete session"
                      onClick={(e) => { e.stopPropagation(); setConfirming(s.session_id); }}
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
