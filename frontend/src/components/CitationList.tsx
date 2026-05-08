import { useState } from "react";
import { ChevronRight, ExternalLink } from "lucide-react";
import type { Citation } from "../lib/types";
import { shortHost } from "../lib/format";

interface Props {
  citations: Citation[];
  onCiteClick: (num: number) => void;
  anchorId?: string;
}

export default function CitationList({ citations, onCiteClick, anchorId }: Props) {
  const [open, setOpen] = useState(true);
  if (!citations.length) return null;

  return (
    <div className="surface rounded-lg overflow-hidden mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.02]"
      >
        <ChevronRight className={`w-3.5 h-3.5 text-neutral-400 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="text-sm text-neutral-200 font-semibold">Citations</span>
        <span className="text-2xs font-mono text-neutral-400 ml-auto">{citations.length}</span>
      </button>
      {open && (
        <ul className="px-3 pb-3 pt-1 border-t hairline space-y-1">
          {citations.map((c) => (
            <li
              key={c.num}
              data-citation-anchor={anchorId ? `${anchorId}-${c.num}` : undefined}
              onClick={() => onCiteClick(c.num)}
              className="flex items-start gap-2 py-2 px-2 -mx-2 rounded
                         hover:bg-white/[0.03] cursor-pointer transition-colors"
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onCiteClick(c.num);
                }
              }}
            >
              <span
                className="flex items-center justify-center min-w-[1.5rem] h-[1.5rem] mt-0.5
                           rounded bg-accent/15 text-accent text-2xs font-mono shrink-0"
              >
                {c.num}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-neutral-100 truncate">{c.title || shortHost(c.url)}</span>
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
      )}
    </div>
  );
}
