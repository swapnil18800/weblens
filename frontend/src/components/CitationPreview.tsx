import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ExternalLink, X } from "lucide-react";
import type { ChunkDict, Citation } from "../lib/types";
import { shortHost } from "../lib/format";
import ChunkBody from "./ChunkBody";

interface Props {
  open: boolean;
  citations: Citation[];
  /** Open the panel pre-expanded on this citation (e.g. clicked from a [N] or chunk). */
  citation: Citation | null;
  /** All chunks from all sub-queries for this turn; used to build the per-URL preview map. */
  allChunks: ChunkDict[];
  /** Display-time renumber: original Citation.num → 1..N display number. */
  citationRemap?: Record<number, number>;
  onClose: () => void;
  onSelectCitation?: (num: number) => void;
  onBack?: () => void;
}

/**
 * Side panel with a single chunk-list. Clicking a row toggles an inline preview
 * card BELOW that row — only one preview is open at a time. No separate
 * "preview mode" / sub-screen.
 */
export default function CitationPreview({ open, citations, citation, allChunks, citationRemap, onClose }: Props) {
  // Track the currently expanded citation by num; preset to the chunk-clicked citation.
  const [expandedNum, setExpandedNum] = useState<number | null>(citation?.num ?? null);

  // When the panel re-opens with a pre-selected citation (e.g. via chunk-click),
  // honour that selection. Closing the panel resets the expanded item.
  useEffect(() => {
    if (open) setExpandedNum(citation?.num ?? null);
    else setExpandedNum(null);
  }, [open, citation?.num]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  // Map url → best-score chunk so every row gets a full preview regardless of how the panel was opened.
  const chunksByUrl = useMemo(() => {
    const m = new Map<string, ChunkDict>();
    for (const ch of allChunks) {
      const existing = m.get(ch.url);
      if (!existing || ch.score > existing.score) m.set(ch.url, ch);
    }
    return m;
  }, [allChunks]);

  const onToggle = (num: number) =>
    setExpandedNum((prev) => (prev === num ? null : num));

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
            className="fixed right-0 top-0 bottom-0 w-full sm:w-[32rem] bg-bg border-l hairline z-50 flex flex-col"
          >
            <div className="h-12 px-4 flex items-center gap-2 border-b hairline shrink-0">
              <span className="text-sm uppercase tracking-wider text-neutral-100 font-semibold">
                Citations
                <span className="text-2xs font-mono text-neutral-400 ml-2">{citations.length}</span>
              </span>
              <button onClick={onClose} className="icon-btn ml-auto" title="Close (Esc)">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scroll-fat px-3 py-3">
              {!citations.length ? (
                <div className="text-2xs text-neutral-400 py-4 px-2">No citations yet.</div>
              ) : (
                <ul className="space-y-1.5">
                  {citations.map((c) => (
                    <CitationRow
                      key={c.num}
                      citation={c}
                      displayNum={citationRemap?.[c.num] ?? c.num}
                      chunk={chunksByUrl.get(c.url) || null}
                      expanded={expandedNum === c.num}
                      onToggle={() => onToggle(c.num)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function CitationRow({
  citation,
  displayNum,
  chunk,
  expanded,
  onToggle,
}: {
  citation: Citation;
  displayNum: number;
  chunk: ChunkDict | null;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <li
      className={`rounded-xl border overflow-hidden transition-colors
                  ${expanded
                    ? "border-accent/30 bg-accent/[0.04]"
                    : "border-white/[0.06] bg-surface hover:bg-white/[0.025]"}`}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-2.5 px-3 py-2.5 text-left"
      >
        <span className="inline-flex items-center justify-center min-w-[1.5rem] h-6 mt-0.5
                         rounded-md bg-accent/15 text-accent text-2xs font-mono font-semibold shrink-0">
          {displayNum}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-neutral-50 font-medium truncate">
            {citation.title || shortHost(citation.url)}
          </div>
          <div className="text-2xs font-mono text-neutral-400 truncate">
            {shortHost(citation.url)}
          </div>
        </div>
        <a
          href={citation.url}
          target="_blank"
          rel="noreferrer"
          className="icon-btn !w-7 !h-7 shrink-0"
          title="Open source"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
        <ChevronDown
          className={`w-4 h-4 text-neutral-400 transition-transform duration-200 shrink-0 mt-0.5
                      ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 pt-1 border-t border-accent/15">
              <div className="flex items-center gap-1.5 mb-2 text-2xs flex-wrap">
                {chunk && (
                  <>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px]
                                     font-mono bg-accent/10 text-accent border border-accent/25">
                      rank #{chunk.rank + 1}
                    </span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px]
                                     font-mono bg-metric/10 text-metric border border-metric/25">
                      score {chunk.score?.toFixed(3)}
                    </span>
                    {chunk.heading && (
                      <span className="text-neutral-300 font-mono truncate text-2xs">
                        {chunk.heading}
                      </span>
                    )}
                  </>
                )}
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px]
                                 font-mono bg-white/[0.04] text-neutral-400 border border-white/[0.08]">
                  BM25 + cross-encoder
                </span>
              </div>
              <ChunkBody
                text={chunk?.chunk_text || citation.snippet || "No preview text available."}
                defaultOpen={false}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

