import { useEffect, useRef, useState } from "react";
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
  const isStreaming = turn.status === "streaming";
  const isStopped = turn.status === "stopped";
  const isDone = turn.status === "done";

  // Open while streaming; collapsed for historical / loaded turns; user can override
  const [open, setOpen] = useState(() =>
    turn.status === "streaming" ? defaultOpen : false,
  );
  // Track user's explicit intent so we don't fight auto-collapse
  const userToggledRef = useRef(false);

  // Auto-collapse a beat after streaming finishes
  const prevStreamingRef = useRef(isStreaming);
  useEffect(() => {
    if (prevStreamingRef.current && !isStreaming && !userToggledRef.current) {
      const t = setTimeout(() => setOpen(false), 700);
      prevStreamingRef.current = isStreaming;
      return () => clearTimeout(t);
    }
    prevStreamingRef.current = isStreaming;
  }, [isStreaming]);

  const toggle = () => {
    userToggledRef.current = true;
    setOpen((v) => !v);
  };

  const totalSteps = turn.subqueries.reduce((acc, sq) => acc + sq.steps.length, 0);
  const now = useNow(isStreaming);

  const elapsedMs = turn.totalLatencyMs ?? (isStreaming ? now - turn.createdAt : undefined);
  const decomposed = turn.subQueries.length > 0;
  const analyzeStatus: "running" | "done" = decomposed ? "done" : "running";
  const analyzeElapsedMs = turn.pipeline.decomposeMs ?? (isStreaming ? now - turn.createdAt : undefined);
  const showDecomposeStep = turn.subQueries.length > 1;

  return (
    <div className="surface rounded-xl overflow-hidden">
      <button
        onClick={toggle}
        className="w-full flex items-center gap-2.5 px-3.5 py-3 text-left hover:bg-white/[0.025] transition-colors"
      >
        <ChevronRight
          className={`w-3.5 h-3.5 text-neutral-500 transition-transform duration-200 shrink-0 ${open ? "rotate-90" : ""}`}
        />
        <Sparkles className="w-3.5 h-3.5 text-accent shrink-0" />
        <span className="text-[14px] text-neutral-100 font-semibold tracking-tight">Reasoning trace</span>
        <div className="ml-auto flex items-center gap-1.5 flex-wrap justify-end">
          {turn.subQueries.length > 0 && (
            <Tag color="info">{turn.subQueries.length} sub-Q{turn.subQueries.length === 1 ? "" : "s"}</Tag>
          )}
          {totalSteps > 0 && (
            <Tag color="warn">{totalSteps} step{totalSteps === 1 ? "" : "s"}</Tag>
          )}
          {elapsedMs !== undefined && (
            <Tag color={isStopped ? "bad" : isDone ? "good" : "warn"}>{ms(elapsedMs)}</Tag>
          )}
          {isStopped && <Tag color="bad">Stopped</Tag>}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="trace-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-3.5 pb-3.5 pt-2.5 border-t border-white/[0.06] space-y-2">
              {/* Analyze */}
              <PhaseRow
                status={analyzeStatus}
                Icon={Brain}
                runningLabel="Analyzing question"
                doneLabel="Analyzed question"
                elapsedMs={analyzeElapsedMs}
              />

              {/* Decomposed */}
              {showDecomposeStep && (
                <PhaseRow
                  status="done"
                  Icon={Sparkles}
                  runningLabel=""
                  doneLabel={`Decomposed into ${turn.subQueries.length} sub-questions`}
                  rightTags={[<Tag key="n" color="info">{turn.subQueries.length}</Tag>]}
                />
              )}

              {/* Sub-query traces — open only during live streaming for single-Q;
                  always collapsed on history/eval/stopped turns. */}
              {turn.subqueries.map((sq) => (
                <SubqueryTrace
                  key={sq.index}
                  sq={sq}
                  now={now}
                  isStreaming={isStreaming}
                  defaultOpen={isStreaming && turn.subqueries.length === 1}
                  onChunkClick={onChunkClick}
                />
              ))}

              {/* Combining */}
              {turn.combiningStatus !== undefined && turn.subQueries.length > 1 && (
                <PhaseRow
                  status={turn.combiningStatus}
                  Icon={GitMerge}
                  runningLabel="Combining sub-answers"
                  doneLabel="Combined sub-answers"
                  elapsedMs={phaseElapsed(turn.combiningStartedAt, turn.combiningCompletedAt, isStreaming, now)}
                />
              )}

              {/* Final answer */}
              {turn.finalStatus !== undefined && (
                <PhaseRow
                  status={turn.finalStatus}
                  Icon={Zap}
                  runningLabel="Generating final answer"
                  doneLabel="Final answer ready"
                  elapsedMs={phaseElapsed(turn.finalStartedAt, turn.finalCompletedAt, isStreaming, now)}
                />
              )}

              {/* Interrupted */}
              {isStopped && (
                <div className="step-row px-2 cursor-default">
                  <OctagonX className="w-4 h-4 text-bad shrink-0" />
                  <span className="text-sm text-bad font-medium">Generation stopped — incomplete answer</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Resolve a synthesis-phase elapsed: frozen if completed, live while running. */
function phaseElapsed(
  startedAt: number | undefined,
  completedAt: number | undefined,
  isStreaming: boolean,
  now: number,
): number | undefined {
  if (startedAt === undefined) return undefined;
  if (completedAt !== undefined) return Math.max(0, completedAt - startedAt);
  return isStreaming ? Math.max(0, now - startedAt) : undefined;
}

/* ── Phase row ─────────────────────────────────────────────────────────────── */

interface PhaseRowProps {
  status: "running" | "done";
  Icon: React.ComponentType<{ className?: string }>;
  runningLabel: string;
  doneLabel: string;
  elapsedMs?: number;
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
  const showTime = elapsedMs !== undefined && (status === "done" || showElapsedWhileRunning);
  return (
    <div className="step-row px-2 cursor-default">
      {status === "running" ? (
        <Loader2 className="w-3.5 h-3.5 text-accent animate-spin shrink-0" />
      ) : (
        <Icon className="w-3.5 h-3.5 text-good shrink-0" />
      )}
      <span className="text-sm text-neutral-100 font-medium">
        {status === "running" ? runningLabel : doneLabel}
      </span>
      <div className="ml-auto flex items-center gap-1.5 shrink-0">
        {rightTags}
        {showTime && (
          <Tag color={status === "done" ? "good" : "warn"}>{ms(elapsedMs)}</Tag>
        )}
      </div>
    </div>
  );
}

/* ── Tag chip ─────────────────────────────────────────────────────────────── */

type TagColor = "good" | "info" | "warn" | "bad";

const TAG_COLOR: Record<TagColor, string> = {
  good: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  info: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  warn: "bg-amber-500/10 text-amber-200 border-amber-500/30",
  bad:  "bg-rose-500/10 text-rose-300 border-rose-500/30",
};

export function Tag({ children, color }: { children: React.ReactNode; color: TagColor }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px]
                  font-mono font-medium tracking-wide whitespace-nowrap border
                  ${TAG_COLOR[color]}`}
    >
      {children}
    </span>
  );
}
