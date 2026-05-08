import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2, ChevronDown, Copy, FileText, Loader2, ThumbsDown, ThumbsUp,
} from "lucide-react";
import type { ChunkDict, Citation, SubqueryState, Turn } from "../lib/types";
import { useChat } from "../state/chatStore";
import Answer from "./Answer";
import CitationPreview from "./CitationPreview";
import MiniTrackerRow from "./MiniTrackerRow";
import ReasoningTrace from "./ReasoningTrace";

interface Props { turn: Turn; }

export default function ChatTurn({ turn }: Props) {
  const reactions = useChat((s) => s.reactions);
  const setReaction = useChat((s) => s.setReaction);
  const [previewNum, setPreviewNum] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const { citation, chunk } = useMemo(() => resolvePreview(previewNum, turn), [previewNum, turn]);
  const onCiteClick = (num: number) => { setPreviewNum(num); setPanelOpen(true); };
  const onChunkClick = (c: ChunkDict) => {
    const cite = turn.citations.find((x) => x.url === c.url);
    if (cite) { setPreviewNum(cite.num); setPanelOpen(true); }
  };

  const finalAnswerRef = useRef<HTMLDivElement>(null);
  const finalAnswerReady = turn.finalStatus === "done";
  const lastFinalReady = useRef(false);
  useEffect(() => {
    if (finalAnswerReady && !lastFinalReady.current) {
      lastFinalReady.current = true;
      requestAnimationFrame(() => {
        finalAnswerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [finalAnswerReady]);

  const showSynthesisSection = turn.subqueries.length > 1;
  const synthesisStarted = turn.synthesizing || turn.synthesisMd.length > 0;

  const onCopy = () => {
    const md = showSynthesisSection ? turn.synthesisMd : (turn.subqueries[0]?.tokens || "");
    if (!md) return;
    navigator.clipboard?.writeText(md).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    }).catch(() => {});
  };

  const reaction = reactions[turn.id];

  return (
    <article data-turn-id={turn.id} className="px-4 sm:px-6 py-6 border-b hairline">
      <div className="max-w-5xl mx-auto">
        {/* Question — right-aligned, capped width, no avatar */}
        <div className="flex justify-end mb-6">
          <div
            className="rounded-2xl rounded-tr-sm px-4 py-3 text-[15px] text-neutral-50 leading-relaxed
                       break-words bg-accent/[0.10] border border-accent/30"
            style={{ maxWidth: "min(70%, 36rem)" }}
          >
            {turn.question}
          </div>
        </div>

        {/* Answer — full width, no glyph */}
        <div className="min-w-0">
          <ReasoningTrace turn={turn} defaultOpen onChunkClick={onChunkClick} />

          {/* Per-subquery answers — for multi-Q only */}
          {showSynthesisSection && (
            <div className="mt-4 space-y-2">
              {turn.subqueries.map((sq) => (
                <SubAnswerCard
                  key={sq.index}
                  sq={sq}
                  finalReady={finalAnswerReady}
                  citations={turn.citations}
                  onCiteClick={onCiteClick}
                />
              ))}
            </div>
          )}

          {/* Final answer */}
          {(showSynthesisSection ? synthesisStarted : true) && (
            <div className="mt-5" ref={finalAnswerRef}>
              {showSynthesisSection && (
                <div className="text-2xs uppercase tracking-wider text-neutral-200 font-semibold mb-2">
                  Final answer
                </div>
              )}
              <Answer
                markdown={
                  showSynthesisSection
                    ? turn.synthesisMd
                    : (turn.subqueries[0]?.tokens || "")
                }
                citations={turn.citations}
                onCiteClick={onCiteClick}
                isStreaming={turn.status === "streaming" && !(showSynthesisSection ? turn.synthesisMd : turn.subqueries[0]?.done)}
              />
            </div>
          )}

          {turn.status === "error" && turn.errorMsg && (
            <div className="mt-3 px-3 py-2 rounded-md bg-bad/10 border border-bad/20 text-xs text-bad">
              {turn.errorMsg}
            </div>
          )}

          {/* Below-answer toolbar: copy / like / dislike / citations */}
          {(turn.status === "done" || turn.status === "stopped") && (
            <div className="mt-6 flex items-center gap-1.5">
              <ToolbarButton
                title={copied ? "Copied!" : "Copy answer"}
                active={copied}
                onClick={onCopy}
              >
                {copied ? <CheckCircle2 className="w-4 h-4 text-good" /> : <Copy className="w-4 h-4" />}
              </ToolbarButton>
              <ToolbarButton
                title="Like"
                active={reaction === "like"}
                onClick={() => setReaction(turn.id, reaction === "like" ? null : "like")}
              >
                <ThumbsUp className="w-4 h-4" />
              </ToolbarButton>
              <ToolbarButton
                title="Dislike"
                active={reaction === "dislike"}
                onClick={() => setReaction(turn.id, reaction === "dislike" ? null : "dislike")}
              >
                <ThumbsDown className="w-4 h-4" />
              </ToolbarButton>
              {turn.citations.length > 0 && (
                <button
                  onClick={() => { setPreviewNum(null); setPanelOpen(true); }}
                  className="ml-1 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full
                             surface text-2xs text-neutral-100 hover:bg-white/[0.05]
                             transition-colors"
                  title="View citations"
                >
                  <FileText className="w-3.5 h-3.5 text-accent" />
                  Citations
                  <span className="font-mono text-accent">{turn.citations.length}</span>
                </button>
              )}
            </div>
          )}
        </div>

        <CitationPreview
          open={panelOpen}
          citations={turn.citations}
          citation={citation}
          chunk={chunk}
          onClose={() => { setPanelOpen(false); setPreviewNum(null); }}
          onSelectCitation={(num) => setPreviewNum(num)}
          onBack={() => setPreviewNum(null)}
        />
      </div>
    </article>
  );
}

function ToolbarButton({
  title, onClick, active, children,
}: { title: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`inline-flex items-center justify-center w-8 h-8 rounded-md
                  transition-colors
                  ${active ? "bg-accent/15 text-accent" : "text-neutral-300 hover:text-neutral-50 hover:bg-white/5"}`}
    >
      {children}
    </button>
  );
}

interface SubAnswerCardProps {
  sq: SubqueryState;
  finalReady: boolean;
  citations: Citation[];
  onCiteClick: (num: number) => void;
}

function SubAnswerCard({ sq, finalReady, citations, onCiteClick }: SubAnswerCardProps) {
  const [override, setOverride] = useState<boolean | null>(null);
  const auto = !finalReady;
  const open = override === null ? auto : override;

  const status: "running" | "done" | "failed" =
    sq.cancelled ? "failed" :
    sq.errorMsg ? "failed" :
    sq.done ? "done" :
    "running";

  return (
    <div className="rounded-xl border border-accent/30 bg-accent/[0.04] overflow-hidden">
      <button
        onClick={() => setOverride(!open)}
        className="w-full flex items-start gap-2 px-4 py-3 text-left hover:bg-accent/[0.07]"
      >
        <span className="mt-0.5 shrink-0">
          {status === "running"
            ? <Loader2 className="w-4 h-4 text-accent animate-spin" />
            : status === "done"
              ? <CheckCircle2 className="w-4 h-4 text-good" />
              : <span className="block w-3.5 h-3.5 rounded-full bg-bad/30 border border-bad/60" />}
        </span>
        <span className="text-2xs font-mono text-accent uppercase tracking-wider shrink-0 mt-0.5">
          Sub-answer Q{sq.index + 1}
        </span>
        <span className="text-sm text-neutral-50 flex-1 min-w-0 break-words font-medium">{sq.query}</span>
        <ChevronDown className={`w-4 h-4 text-neutral-200 transition-transform shrink-0 mt-0.5 ${open ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-1 border-t border-accent/15 bg-bg/40">
              {sq.tokens.length === 0 && !sq.done ? (
                <MiniTrackerRow sq={sq} />
              ) : (
                <Answer
                  markdown={sq.tokens || (sq.done ? "(no answer)" : "…")}
                  citations={citations}
                  onCiteClick={onCiteClick}
                  isStreaming={!sq.done}
                />
              )}
              {sq.cancelled && <div className="text-xs text-bad mt-1">Stopped.</div>}
              {sq.errorMsg && <div className="text-xs text-bad mt-1">{sq.errorMsg}</div>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function resolvePreview(num: number | null, turn: Turn): { citation: Citation | null; chunk: ChunkDict | null } {
  if (num === null) return { citation: null, chunk: null };
  const c = turn.citations.find((x) => x.num === num) || null;
  if (!c) return { citation: null, chunk: null };
  let best: ChunkDict | null = null;
  for (const sq of turn.subqueries) {
    for (const ch of sq.chunks) {
      if (ch.url === c.url) {
        if (!best || ch.score > best.score) best = ch;
      }
    }
  }
  return { citation: c, chunk: best };
}
