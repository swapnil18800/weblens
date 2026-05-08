import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  CheckCircle2,
  ChevronRight,
  GitMerge,
  Loader2,
  OctagonX,
  Sparkles,
  Zap,
} from "lucide-react";
import type { ChunkDict, Turn } from "../lib/types";
import { ms } from "../lib/format";
import { useNow } from "../lib/useNow";
import SubqueryTrace from "./SubqueryTrace";

interface Props {
  turn: Turn;
  defaultOpen?: boolean;
  onChunkClick?: (chunk: ChunkDict) => void;
}

export default function ReasoningTrace({ turn, defaultOpen = true, onChunkClick }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const isStreaming = turn.status === "streaming";
  const isStopped = turn.status === "stopped";
  const totalSteps = turn.subqueries.reduce((acc, sq) => acc + sq.steps.length, 0);
  const now = useNow(isStreaming);

  // Live elapsed time on the main header
  const elapsedMs = turn.totalLatencyMs ?? (isStreaming ? now - turn.createdAt : undefined);

  // Decompose-step state
  const decomposed = turn.subQueries.length > 0;
  const analyzeStatus: "running" | "done" = decomposed ? "done" : "running";
  const analyzeElapsedMs = turn.pipeline.decomposeMs ?? (isStreaming ? now - turn.createdAt : undefined);

  // Show "Question decomposed" step only if decomposition really happened
  const showDecomposeStep = turn.subQueries.length > 1;

  return (
    <div className="surface rounded-lg overflow-hidden font-sans">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-white/[0.02]"
      >
        <ChevronRight className={`w-4 h-4 text-neutral-400 transition-transform shrink-0 ${open ? "rotate-90" : ""}`} />
        <Sparkles className="w-4 h-4 text-accent shrink-0" />
        <span className="text-[15px] text-neutral-100 font-semibold">Reasoning trace</span>
        <div className="ml-auto flex items-center gap-1.5 flex-wrap justify-end">
          {turn.subQueries.length > 0 && (
            <Tag color="info">
              {turn.subQueries.length} sub-Q{turn.subQueries.length === 1 ? "" : "s"}
            </Tag>
          )}
          {totalSteps > 0 && (
            <Tag color="warn">
              {totalSteps} step{totalSteps === 1 ? "" : "s"}
            </Tag>
          )}
          {elapsedMs !== undefined && (
            <Tag color={isStopped ? "bad" : isStreaming ? "warn" : "good"}>
              {ms(elapsedMs)}
            </Tag>
          )}
          {isStopped && <Tag color="bad">Stopped</Tag>}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 pt-2 border-t hairline space-y-1.5">
              {/* Analyze step — always shown */}
              <PhaseRow
                status={analyzeStatus}
                Icon={Brain}
                runningLabel="Analyzing question"
                doneLabel="Analyzed question"
                elapsedMs={analyzeElapsedMs}
                showElapsedWhileRunning
              />

              {/* Decomposed step — only when decomposition happened */}
              {showDecomposeStep && (
                <PhaseRow
                  status="done"
                  Icon={Sparkles}
                  runningLabel=""
                  doneLabel={`Question decomposed into ${turn.subQueries.length} sub-questions`}
                  rightTags={[
                    <Tag key="c" color="info">
                      {turn.subQueries.length}
                    </Tag>,
                  ]}
                />
              )}

              {/* Sub-query traces */}
              {turn.subqueries.map((sq) => (
                <SubqueryTrace
                  key={sq.index}
                  sq={sq}
                  now={now}
                  isStreaming={isStreaming}
                  defaultOpen={turn.subqueries.length === 1}
                  onChunkClick={onChunkClick}
                />
              ))}

              {/* Combining sub-answers — only for multi-Q turns */}
              {turn.combiningStatus !== undefined && turn.subQueries.length > 1 && (
                <PhaseRow
                  status={turn.combiningStatus}
                  Icon={GitMerge}
                  runningLabel="Combining sub-answers"
                  doneLabel="Combined sub-answers"
                />
              )}

              {/* Generating final answer */}
              {turn.finalStatus !== undefined && (
                <PhaseRow
                  status={turn.finalStatus}
                  Icon={Zap}
                  runningLabel="Generating final answer"
                  doneLabel="Final answer ready"
                />
              )}

              {/* Interrupted */}
              {isStopped && (
                <div className="step-row px-2 cursor-default">
                  <OctagonX className="w-4 h-4 text-bad shrink-0" />
                  <span className="text-sm text-bad font-medium">
                    Generation stopped — incomplete answer
                  </span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface PhaseRowProps {
  status: "running" | "done";
  Icon: React.ComponentType<{ className?: string }>;
  runningLabel: string;
  doneLabel: string;
  elapsedMs?: number;
  /** Show the elapsed-time chip while still running (live) */
  showElapsedWhileRunning?: boolean;
  rightTags?: React.ReactNode[];
}

function PhaseRow({
  status,
  Icon,
  runningLabel,
  doneLabel,
  elapsedMs,
  showElapsedWhileRunning,
  rightTags,
}: PhaseRowProps) {
  const showTime =
    elapsedMs !== undefined && (status === "done" || showElapsedWhileRunning);

  return (
    <div className="step-row px-2 cursor-default">
      {status === "running" ? (
        <Loader2 className="w-4 h-4 text-accent animate-spin shrink-0" />
      ) : (
        <Icon className="w-4 h-4 text-good shrink-0" />
      )}
      <span className="text-sm text-neutral-100 font-medium">
        {status === "running" ? runningLabel : doneLabel}
      </span>
      <div className="ml-auto flex items-center gap-1.5 shrink-0">
        {rightTags}
        {showTime && <Tag color={status === "done" ? "good" : "warn"}>{ms(elapsedMs)}</Tag>}
      </div>
    </div>
  );
}

/* ── Tag chip ─────────────────────────────────────────────────────────────── */

type TagColor = "good" | "info" | "warn" | "bad";

export function Tag({
  children,
  color,
}: {
  children: React.ReactNode;
  color: TagColor;
}) {
  return (
    <span className={`tag tag-${color} font-mono`}>{children}</span>
  );
}
