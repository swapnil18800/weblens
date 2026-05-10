import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronRight, ExternalLink, Layers, X } from "lucide-react";
import type { ChunkDict, SubqueryState } from "../lib/types";
import { shortHost } from "../lib/format";
import ChunkBody from "./ChunkBody";

interface Props {
  open: boolean;
  subqueries: SubqueryState[];
  /** Pre-select a chunk on open: { sqIndex, rank } */
  preselect: { sqIndex: number; rank: number } | null;
  onClose: () => void;
}

/**
 * Right slide-in panel showing the ranked retrieved chunks per sub-query.
 * Distinct from CitationPreview — that panel is the post-answer "what got cited"
 * surface; this is the pre-answer "what got retrieved" surface, with all chunks
 * (cited or not) and per-sub-query grouping.
 */
export default function RetrievedDataPanel({ open, subqueries, preselect, onClose }: Props) {
  const [openSqs, setOpenSqs] = useState<Set<number>>(new Set());
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setOpenSqs(new Set());
      setExpandedKey(null);
      return;
    }
    if (preselect) {
      setOpenSqs(new Set([preselect.sqIndex]));
      setExpandedKey(`${preselect.sqIndex}-${preselect.rank}`);
    } else if (subqueries.length === 1) {
      setOpenSqs(new Set([0]));
      setExpandedKey(null);
    } else {
      // Default: open the first sub-query
      setOpenSqs(new Set(subqueries.length > 0 ? [subqueries[0].index] : []));
      setExpandedKey(null);
    }
  }, [open, preselect, subqueries]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const toggleSq = (idx: number) => {
    setOpenSqs((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleChunk = (key: string) =>
    setExpandedKey((prev) => (prev === key ? null : key));

  const totalChunks = subqueries.reduce((n, sq) => n + sq.chunks.length, 0);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.14 }}
            className="fixed inset-0 bg-black/40 z-40"
            onClick={onClose}
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            className="fixed right-0 top-0 bottom-0 w-full sm:w-[34rem] bg-bg border-l hairline z-50 flex flex-col"
          >
            <div className="h-12 px-4 flex items-center gap-2 border-b hairline shrink-0">
              <Layers className="w-4 h-4 text-accent" />
              <span className="text-sm uppercase tracking-wider text-neutral-100 font-semibold">
                Retrieved data
                <span className="text-2xs font-mono text-neutral-400 ml-2">
                  {totalChunks} passage{totalChunks === 1 ? "" : "s"}
                </span>
              </span>
              <button onClick={onClose} className="icon-btn ml-auto" title="Close (Esc)">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scroll-fat px-3 py-3 space-y-2">
              {subqueries.length === 0 && (
                <div className="text-2xs text-neutral-400 py-4 px-2">No retrieved chunks yet.</div>
              )}
              {subqueries.map((sq) => (
                <SubquerySection
                  key={sq.index}
                  sq={sq}
                  open={openSqs.has(sq.index)}
                  onToggle={() => toggleSq(sq.index)}
                  expandedKey={expandedKey}
                  onToggleChunk={toggleChunk}
                />
              ))}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function SubquerySection({
  sq,
  open,
  onToggle,
  expandedKey,
  onToggleChunk,
}: {
  sq: SubqueryState;
  open: boolean;
  onToggle: () => void;
  expandedKey: string | null;
  onToggleChunk: (key: string) => void;
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-surface overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-2 px-3 py-2.5 text-left hover:bg-white/[0.03] transition-colors"
      >
        <ChevronRight
          className={`w-3.5 h-3.5 text-neutral-500 mt-0.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-2xs font-mono text-neutral-400 mt-0.5 shrink-0">Q{sq.index + 1}</span>
        <span className="text-sm text-neutral-100 flex-1 min-w-0 break-words">{sq.query}</span>
        <span className="text-2xs font-mono text-neutral-400 shrink-0 mt-0.5">
          {sq.chunks.length}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <ul className="px-3 pb-3 pt-1 space-y-1.5 border-t border-white/[0.04]">
              {sq.chunks.map((ch) => {
                const key = `${sq.index}-${ch.rank}`;
                return (
                  <ChunkRow
                    key={key}
                    chunk={ch}
                    expanded={expandedKey === key}
                    onToggle={() => onToggleChunk(key)}
                  />
                );
              })}
              {sq.chunks.length === 0 && (
                <li className="text-2xs text-neutral-500 py-2">No chunks for this sub-query.</li>
              )}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ChunkRow({
  chunk,
  expanded,
  onToggle,
}: {
  chunk: ChunkDict;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <li
      className={`rounded-lg border overflow-hidden transition-colors
                  ${expanded
                    ? "border-accent/30 bg-accent/[0.04]"
                    : "border-white/[0.05] bg-white/[0.012] hover:bg-white/[0.025]"}`}
    >
      <button onClick={onToggle} className="w-full flex items-start gap-2 px-2.5 py-2 text-left">
        <span className="font-mono text-2xs text-neutral-500 w-7 shrink-0 mt-0.5">#{chunk.rank + 1}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-100 truncate">
              {chunk.title || shortHost(chunk.url)}
            </span>
            <span className="text-2xs font-mono text-neutral-500 truncate">{shortHost(chunk.url)}</span>
          </div>
          {chunk.heading && (
            <div className="text-2xs font-mono text-neutral-500 truncate">{chunk.heading}</div>
          )}
        </div>
        <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px]
                         font-mono bg-metric/10 text-metric border border-metric/25 shrink-0">
          {chunk.score?.toFixed(3)}
        </span>
        <a
          href={chunk.url}
          target="_blank"
          rel="noreferrer"
          className="icon-btn !w-6 !h-6 shrink-0 mt-0.5"
          title="Open source"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink className="w-3 h-3" />
        </a>
        <ChevronDown
          className={`w-3.5 h-3.5 text-neutral-400 shrink-0 mt-1 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-2.5 pb-2.5 pt-1 border-t border-accent/15">
              <ChunkBody text={chunk.chunk_text} defaultOpen={false} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
