import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ExternalLink, X } from "lucide-react";
import type { ChunkDict, Citation } from "../lib/types";
import { shortHost } from "../lib/format";

interface Props {
  /** When true, the panel is open. */
  open: boolean;
  /** Citations to list when no specific one is selected. */
  citations: Citation[];
  /** Currently-selected citation (preview mode); null = list mode. */
  citation: Citation | null;
  /** Best-matching chunk for the selected citation. */
  chunk: ChunkDict | null;
  onClose: () => void;
  /** Switch to a specific citation (preview mode). */
  onSelectCitation: (num: number) => void;
  /** Go back from preview to list. */
  onBack: () => void;
}

export default function CitationPreview({
  open,
  citations,
  citation,
  chunk,
  onClose,
  onSelectCitation,
  onBack,
}: Props) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="fixed inset-0 bg-black/40 z-40"
            onClick={onClose}
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.22, ease: "easeOut" }}
            className="fixed right-0 top-0 bottom-0 w-full sm:w-[30rem] bg-bg border-l hairline z-50 flex flex-col"
          >
            <div className="h-12 px-4 flex items-center gap-2 border-b hairline">
              {citation ? (
                <>
                  <button onClick={onBack} className="icon-btn !w-8 !h-8" title="Back to citations">
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="cite flex items-center justify-center min-w-[1.5rem] h-[1.5rem] rounded bg-accent/15 text-accent text-2xs font-mono">
                    {citation.num}
                  </span>
                  <span className="text-2xs uppercase tracking-wider text-neutral-200 font-semibold truncate">
                    Source preview
                  </span>
                </>
              ) : (
                <span className="text-sm uppercase tracking-wider text-neutral-100 font-semibold">
                  Citations <span className="text-2xs font-mono text-neutral-400 ml-1">{citations.length}</span>
                </span>
              )}
              <button onClick={onClose} className="icon-btn ml-auto" title="Close (Esc)">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scroll-fat px-4 py-4">
              {citation ? (
                <PreviewBody citation={citation} chunk={chunk} />
              ) : (
                <CitationListBody citations={citations} onSelect={onSelectCitation} />
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function PreviewBody({ citation, chunk }: { citation: Citation; chunk: ChunkDict | null }) {
  return (
    <>
      <h3 className="text-base text-neutral-50 font-semibold mb-1 break-words">
        {citation.title || shortHost(citation.url)}
      </h3>
      <div className="text-2xs font-mono text-neutral-400 break-all mb-3">{citation.url}</div>

      {chunk && (
        <div className="flex items-center gap-2 mb-3 text-2xs flex-wrap">
          <span className="chip chip-info">rank #{chunk.rank + 1}</span>
          <span className="chip chip-info">score {chunk.score?.toFixed(3)}</span>
          {chunk.heading && <span className="text-neutral-300 font-mono truncate">{chunk.heading}</span>}
        </div>
      )}

      <a
        href={citation.url}
        target="_blank"
        rel="noreferrer"
        className="btn-accent !py-1 !text-xs mb-4 inline-flex"
      >
        <ExternalLink className="w-3.5 h-3.5" />
        Open source
      </a>

      <div className="text-2xs uppercase tracking-wider text-neutral-200 font-semibold mb-1.5">
        Chunk
      </div>
      <div className="surface rounded-lg px-4 py-3 text-sm text-neutral-100 leading-7 whitespace-pre-wrap">
        {chunk?.chunk_text || citation.snippet || "No preview text available."}
      </div>
    </>
  );
}

function CitationListBody({
  citations,
  onSelect,
}: {
  citations: Citation[];
  onSelect: (num: number) => void;
}) {
  if (!citations.length) {
    return <div className="text-2xs text-neutral-400 py-4">No citations yet.</div>;
  }
  return (
    <ul className="space-y-1.5">
      {citations.map((c) => (
        <li
          key={c.num}
          onClick={() => onSelect(c.num)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect(c.num);
            }
          }}
          className="surface rounded-lg p-3 hover:bg-white/[0.04] cursor-pointer
                     transition-colors flex items-start gap-2"
        >
          <span className="cite flex items-center justify-center min-w-[1.5rem] h-[1.5rem] mt-0.5
                           rounded bg-accent/15 text-accent text-2xs font-mono shrink-0">
            {c.num}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm text-neutral-50 truncate font-medium">
                {c.title || shortHost(c.url)}
              </span>
              <a
                href={c.url}
                target="_blank"
                rel="noreferrer"
                className="icon-btn !w-5 !h-5"
                title="Open source"
                onClick={(e) => e.stopPropagation()}
              >
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <div className="text-2xs font-mono text-neutral-400 truncate">{c.url}</div>
            {c.snippet && (
              <div className="text-2xs text-neutral-300 mt-1 line-clamp-2">{c.snippet}</div>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

// Re-export for callers that still import the old component shape.
// Kept for compatibility; new callers should pass the full props above.
// Removed: see ChatTurn.tsx for current usage.
export { CitationPreview as _Renamed };
