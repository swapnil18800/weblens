import { useState } from "react";
import { CheckCircle2, ChevronRight, Loader2, XCircle } from "lucide-react";
import type { ChunkDict, SubqueryState } from "../lib/types";
import { ms } from "../lib/format";
import PipelineStep from "./PipelineStep";
import { Tag } from "./ReasoningTrace";

interface Props {
  sq: SubqueryState;
  now: number;
  isStreaming: boolean;
  isError?: boolean;
  defaultOpen?: boolean;
  onChunkClick?: (chunk: ChunkDict) => void;
}

export default function SubqueryTrace({
  sq,
  now,
  isStreaming,
  isError,
  defaultOpen = false,
  onChunkClick,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const status: "running" | "done" | "failed" =
    sq.cancelled ? "failed" :
    sq.errorMsg ? "failed" :
    sq.done ? "done" :
    isError ? "failed" :
    "running";

  // Total elapsed = completedAt − startedAt (wall-clock from decompose → answer done).
  // While still running, show live count from startedAt.
  // This is intentionally separate from the per-step latency shown inside the trace.
  const elapsedMs = (() => {
    if (sq.completedAt && sq.startedAt) return sq.completedAt - sq.startedAt;
    if (sq.startedAt && (isStreaming || status === "running")) return now - sq.startedAt;
    return undefined;
  })();

  return (
    <div className="rounded-xl border border-white/[0.05] bg-white/[0.012] ml-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.025] rounded-xl transition-colors"
      >
        <ChevronRight
          className={`w-3.5 h-3.5 text-neutral-500 transition-transform duration-200 shrink-0 ${open ? "rotate-90" : ""}`}
        />
        <StatusIcon status={status} />
        <span className="text-2xs font-mono text-neutral-500 shrink-0">Q{sq.index + 1}</span>
        <span className="text-sm text-neutral-200 flex-1 min-w-0 break-words">{sq.query}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          {sq.steps.length > 0 && (
            <Tag color="warn">{sq.steps.length} step{sq.steps.length === 1 ? "" : "s"}</Tag>
          )}
          {elapsedMs !== undefined && (
            <Tag color={status === "failed" ? "bad" : status === "done" ? "good" : "warn"}>
              {ms(elapsedMs)}
            </Tag>
          )}
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-white/[0.04]">
          {sq.steps.length === 0 && status === "running" && !isError && (
            <div className="step-row px-2 cursor-default">
              <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
              <span className="text-sm text-neutral-400">Getting started…</span>
            </div>
          )}
          {sq.steps.map((s) => (
            <PipelineStep key={s.id} step={s} onChunkClick={onChunkClick} />
          ))}
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
