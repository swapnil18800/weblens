import { useState } from "react";
import { CheckCircle2, ChevronRight, Loader2, XCircle } from "lucide-react";
import type { ChunkDict, SubqueryState } from "../lib/types";
import { ms, shortHost } from "../lib/format";
import PipelineStep from "./PipelineStep";
import { Tag } from "./ReasoningTrace";

interface Props {
  sq: SubqueryState;
  /** Live `Date.now()` from the parent — used to drive live timers */
  now: number;
  isStreaming: boolean;
  defaultOpen?: boolean;
  onChunkClick?: (chunk: ChunkDict) => void;
}

export default function SubqueryTrace({
  sq,
  now,
  isStreaming,
  defaultOpen = false,
  onChunkClick,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const status: "running" | "done" | "failed" =
    sq.cancelled ? "failed" :
    sq.errorMsg ? "failed" :
    sq.done ? "done" :
    "running";

  // Live elapsed: until done, count up from startedAt; afterwards show stored latency.
  const elapsedMs =
    sq.latencyMs ??
    (sq.startedAt && (isStreaming || status === "running") ? now - sq.startedAt : undefined);

  return (
    <div className="rounded-md border border-white/[0.05] bg-white/[0.012] ml-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.02] rounded-md"
      >
        <ChevronRight
          className={`w-3.5 h-3.5 text-neutral-400 transition-transform shrink-0 ${open ? "rotate-90" : ""}`}
        />
        <StatusIcon status={status} />
        <span className="text-2xs font-mono text-neutral-400 shrink-0">Q{sq.index + 1}</span>
        <span className="text-sm text-neutral-100 flex-1 min-w-0 break-words">{sq.query}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          {sq.steps.length > 0 && (
            <Tag color="warn">
              {sq.steps.length} step{sq.steps.length === 1 ? "" : "s"}
            </Tag>
          )}
          {elapsedMs !== undefined && (
            <Tag color={status === "failed" ? "bad" : "good"}>{ms(elapsedMs)}</Tag>
          )}
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1">
          {sq.steps.length === 0 && status === "running" && (
            <div className="step-row px-2 cursor-default">
              <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
              <span className="text-sm text-neutral-300">Getting started…</span>
            </div>
          )}
          {sq.steps.map((s) => (
            <PipelineStep key={s.id} step={s} />
          ))}
          {sq.chunks.length > 0 && (
            <ChunksPanel sq={sq} onChunkClick={onChunkClick} />
          )}
        </div>
      )}
    </div>
  );
}

function StatusIcon({ status }: { status: "running" | "done" | "failed" }) {
  if (status === "running")
    return <Loader2 className="w-3.5 h-3.5 text-accent animate-spin shrink-0" />;
  if (status === "done")
    return <CheckCircle2 className="w-3.5 h-3.5 text-good shrink-0" />;
  return <XCircle className="w-3.5 h-3.5 text-bad shrink-0" />;
}

function ChunksPanel({ sq, onChunkClick }: { sq: SubqueryState; onChunkClick?: (chunk: ChunkDict) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 border-t hairline pt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-2xs uppercase tracking-wider text-neutral-200 font-semibold hover:text-neutral-50"
      >
        <ChevronRight className={`w-3 h-3 transition-transform ${open ? "rotate-90" : ""}`} />
        Top passages used ({sq.chunks.length})
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {sq.chunks.map((c, i) => (
            <li
              key={i}
              data-chunk-anchor={`${sq.index}-${i}`}
              onClick={() => onChunkClick?.(c)}
              className={`text-2xs text-neutral-300 flex items-start gap-2 px-2 py-1.5 rounded
                          bg-white/[0.025] transition-colors
                          ${onChunkClick ? "cursor-pointer hover:bg-white/[0.05]" : ""}`}
              role={onChunkClick ? "button" : undefined}
              tabIndex={onChunkClick ? 0 : undefined}
              onKeyDown={(e) => {
                if (onChunkClick && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onChunkClick(c);
                }
              }}
            >
              <span className="font-mono text-neutral-400 w-6 shrink-0">#{c.rank + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-neutral-100 truncate">{c.title || shortHost(c.url)}</span>
                  <span className="text-neutral-400 truncate">{shortHost(c.url)}</span>
                </div>
                {c.heading && <div className="font-mono text-neutral-400 truncate">{c.heading}</div>}
                <div className="mt-1 text-neutral-300 line-clamp-2">
                  {c.chunk_text.slice(0, 220)}
                  {c.chunk_text.length > 220 && "…"}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
