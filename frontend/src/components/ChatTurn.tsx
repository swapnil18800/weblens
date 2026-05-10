import { useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CornerDownRight,
  Copy, FileText, Layers, Loader2, Pencil, RotateCcw, ThumbsDown, ThumbsUp,
} from "lucide-react";
import type { ChunkDict, Citation, SubqueryState, Turn } from "../lib/types";
import { useChat } from "../state/chatStore";
import Answer from "./Answer";
import CitationPreview from "./CitationPreview";
import MiniTrackerRow from "./MiniTrackerRow";
import ReasoningTrace from "./ReasoningTrace";
import RetrievedDataPanel from "./RetrievedDataPanel";

interface Props { turn: Turn; }

export default function ChatTurn({ turn }: Props) {
  const reactions = useChat((s) => s.reactions);
  const setReaction = useChat((s) => s.setReaction);
  const retryTurn = useChat((s) => s.retryTurn);
  const editTurn = useChat((s) => s.editTurn);
  const setPendingInput = useChat((s) => s.setPendingInput);
  const allTurns = useChat((s) => s.turns);
  const selectedVersion = useChat((s) => s.selectedVersion);
  const selectVersion = useChat((s) => s.selectVersion);
  const isStreaming = useChat((s) => s.isStreaming);

  // Sibling versions of this turn (retries / edits share versionGroupId).
  const versions = useMemo(
    () => allTurns
      .filter((t) => t.versionGroupId === turn.versionGroupId)
      .slice()
      .sort((a, b) => a.versionIndex - b.versionIndex),
    [allTurns, turn.versionGroupId],
  );
  const currentVersionIdx = versions.findIndex((v) => v.id === turn.id);
  const onPickVersion = (idx: number) => {
    if (idx < 0 || idx >= versions.length) return;
    selectVersion(turn.versionGroupId, idx);
  };

  // Right-side panels: citations (post-answer) and retrieved-data (per-subquery chunks).
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelCiteNum, setPanelCiteNum] = useState<number | null>(null);
  const [retrievedOpen, setRetrievedOpen] = useState(false);
  const [retrievedPreselect, setRetrievedPreselect] = useState<{ sqIndex: number; rank: number } | null>(null);
  const [copied, setCopied] = useState(false);
  const [questionCopied, setQuestionCopied] = useState(false);

  const onCopyQuestion = () => {
    if (!turn.question) return;
    navigator.clipboard?.writeText(turn.question).then(() => {
      setQuestionCopied(true);
      setTimeout(() => setQuestionCopied(false), 1400);
    }).catch(() => {});
  };

  // Edit-question inline state
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(turn.question);

  const panelCitation = useMemo(
    () => (panelCiteNum !== null ? turn.citations.find((c) => c.num === panelCiteNum) ?? null : null),
    [panelCiteNum, turn.citations],
  );

  // All chunks across all sub-queries for this turn — CitationPreview builds the URL→chunk map from this.
  const allChunks = useMemo(
    () => turn.subqueries.flatMap((sq) => sq.chunks),
    [turn.subqueries],
  );

  // [N] click → open Citations panel pre-expanded on that citation.
  const onCiteClick = (num: number) => {
    setPanelCiteNum(num);
    setPanelOpen(true);
  };
  const onSubCiteClick = onCiteClick;

  // Top-passage click → open Retrieved-Data panel preselected to that chunk.
  const onChunkClick = (c: ChunkDict) => {
    let sqIndex = 0;
    for (const sq of turn.subqueries) {
      if (sq.chunks.some((x) => x.url === c.url && x.rank === c.rank)) {
        sqIndex = sq.index;
        break;
      }
    }
    setRetrievedPreselect({ sqIndex, rank: c.rank });
    setRetrievedOpen(true);
  };

  const onRetry = () => {
    if (isStreaming) return;
    void retryTurn(turn.id);
  };
  const onSaveEdit = () => {
    const q = editText.trim();
    if (!q || isStreaming) return;
    setEditing(false);
    // Edit creates a sibling under the same versionGroupId so the user can
    // navigate between the two question phrasings via the < n/N > selector.
    void editTurn(turn.id, q);
  };

  const answerRef = useRef<HTMLDivElement>(null);
  const showSynthesisSection = turn.subqueries.length > 1;
  const synthesisStarted = turn.synthesizing || turn.synthesisMd.length > 0;
  const finalAnswerReady = turn.finalStatus === "done";

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
    <article data-turn-id={turn.id} className="px-4 sm:px-6 pt-2 pb-6 border-b hairline" style={{ scrollMarginTop: "12px" }}>
      <div className="max-w-5xl mx-auto">
        {/* Question — right-aligned, with hover-revealed Edit/Retry on the bubble itself */}
        <div className="flex justify-end mb-6">
          {editing ? (
            <div
              className="rounded-2xl rounded-tr-sm px-4 py-3 bg-accent/[0.10] border border-accent/30
                         flex flex-col gap-2"
              style={{ maxWidth: "min(85%, 42rem)", width: "100%" }}
            >
              <textarea
                autoFocus
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    onSaveEdit();
                  }
                  if (e.key === "Escape") { setEditText(turn.question); setEditing(false); }
                }}
                rows={Math.min(6, Math.max(2, editText.split("\n").length))}
                className="w-full bg-transparent text-[15px] text-neutral-50 leading-relaxed
                           outline-none resize-none"
              />
              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={() => { setEditText(turn.question); setEditing(false); }}
                  className="text-2xs text-neutral-400 hover:text-neutral-100 px-2 py-1 rounded"
                >
                  Cancel
                </button>
                <button
                  onClick={onSaveEdit}
                  disabled={!editText.trim() || isStreaming}
                  className="text-2xs px-2.5 py-1 rounded-md bg-accent/30 text-accent
                             hover:bg-accent/40 disabled:opacity-40 disabled:cursor-not-allowed"
                  title="Send edited question (⌘/Ctrl+Enter)"
                >
                  Send
                </button>
              </div>
            </div>
          ) : (
            <div className="group flex flex-col items-end gap-1.5 max-w-full">
              {/* Inline Edit / Retry / Copy hover icons next to the bubble */}
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                {!isStreaming && (
                  <>
                    <button
                      onClick={() => { setEditText(turn.question); setEditing(true); }}
                      className="text-neutral-300 hover:text-white p-1 rounded hover:bg-white/[0.05] transition-colors"
                      title="Edit question"
                      aria-label="Edit question"
                    >
                      <Pencil className="w-4 h-4" strokeWidth={2.25} />
                    </button>
                    <button
                      onClick={onRetry}
                      className="text-neutral-300 hover:text-white p-1 rounded hover:bg-white/[0.05] transition-colors"
                      title="Retry — re-run this question"
                      aria-label="Retry"
                    >
                      <RotateCcw className="w-4 h-4" strokeWidth={2.25} />
                    </button>
                    <button
                      onClick={onCopyQuestion}
                      className="text-neutral-300 hover:text-white p-1 rounded hover:bg-white/[0.05] transition-colors"
                      title={questionCopied ? "Copied!" : "Copy question"}
                      aria-label="Copy question"
                    >
                      {questionCopied
                        ? <CheckCircle2 className="w-4 h-4 text-good" strokeWidth={2.25} />
                        : <Copy className="w-4 h-4" strokeWidth={2.25} />}
                    </button>
                  </>
                )}
              </div>
              <div
                className="rounded-2xl rounded-tr-sm px-4 py-3 text-[15px] text-neutral-50 leading-relaxed
                           break-words bg-accent/[0.10] border border-accent/30"
                style={{ maxWidth: "min(70%, 36rem)" }}
              >
                {turn.question}
              </div>
              {/* Version navigator: only when there's >1 sibling */}
              {versions.length > 1 && (
                <div className="flex items-center gap-1 text-sm font-medium text-neutral-300 font-mono">
                  <button
                    onClick={() => onPickVersion(currentVersionIdx - 1)}
                    disabled={currentVersionIdx <= 0}
                    className="p-1 rounded hover:bg-white/[0.05] disabled:opacity-30 disabled:cursor-not-allowed
                               text-neutral-300 hover:text-white transition-colors"
                    title="Previous version"
                    aria-label="Previous version"
                  >
                    <ChevronLeft className="w-4 h-4" strokeWidth={2.5} />
                  </button>
                  <span className="select-none">{currentVersionIdx + 1} / {versions.length}</span>
                  <button
                    onClick={() => onPickVersion(currentVersionIdx + 1)}
                    disabled={currentVersionIdx >= versions.length - 1}
                    className="p-1 rounded hover:bg-white/[0.05] disabled:opacity-30 disabled:cursor-not-allowed
                               text-neutral-300 hover:text-white transition-colors"
                    title="Next version"
                    aria-label="Next version"
                  >
                    <ChevronRight className="w-4 h-4" strokeWidth={2.5} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Answer area */}
        <div className="min-w-0">
          <ReasoningTrace turn={turn} defaultOpen onChunkClick={onChunkClick} />

          {/* Per-subquery answers (multi-Q) */}
          {showSynthesisSection && (
            <div className="mt-4 space-y-2">
              {turn.subqueries.map((sq) => (
                <SubAnswerCard
                  key={sq.index}
                  sq={sq}
                  finalReady={finalAnswerReady}
                  citations={turn.citations}
                  citationRemap={turn.citationRemap}
                  onCiteClick={onSubCiteClick}
                />
              ))}
            </div>
          )}

          {/* Final answer */}
          {(showSynthesisSection ? synthesisStarted : true) && (
            <div className="mt-5" ref={answerRef}>
              {showSynthesisSection && (
                <div className="text-2xs uppercase tracking-wider text-neutral-400 font-semibold mb-2">
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
                citationRemap={turn.citationRemap}
                onCiteClick={onCiteClick}
                isStreaming={
                  turn.status === "streaming" &&
                  !(showSynthesisSection ? turn.synthesisMd : turn.subqueries[0]?.done)
                }
              />
            </div>
          )}

          {turn.status === "error" && turn.errorMsg && (
            <div className="mt-3 px-3 py-2 rounded-lg bg-bad/10 border border-bad/20 text-xs text-bad">
              {turn.errorMsg}
            </div>
          )}

          {/* Toolbar */}
          {(turn.status === "done" || turn.status === "stopped" || turn.status === "error") && (
            <div className="mt-5 flex items-center gap-1 flex-wrap">
              <ToolbarButton
                title={copied ? "Copied!" : "Copy answer"}
                active={copied}
                onClick={onCopy}
              >
                {copied
                  ? <CheckCircle2 className="w-3.5 h-3.5 text-good" />
                  : <Copy className="w-3.5 h-3.5" />}
              </ToolbarButton>
              <ToolbarButton
                title="Like"
                active={reaction === "like"}
                onClick={() => setReaction(turn.id, reaction === "like" ? null : "like")}
              >
                <ThumbsUp className="w-3.5 h-3.5" />
              </ToolbarButton>
              <ToolbarButton
                title="Dislike"
                active={reaction === "dislike"}
                onClick={() => setReaction(turn.id, reaction === "dislike" ? null : "dislike")}
              >
                <ThumbsDown className="w-3.5 h-3.5" />
              </ToolbarButton>
              <ToolbarButton
                title="Retry — re-run this question"
                onClick={onRetry}
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </ToolbarButton>
              {allChunks.length > 0 && (
                <button
                  onClick={() => { setRetrievedPreselect(null); setRetrievedOpen(true); }}
                  className="ml-1.5 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full
                             surface text-2xs text-neutral-300 hover:text-neutral-100
                             hover:bg-white/[0.05] transition-colors"
                  title="View retrieved data"
                >
                  <Layers className="w-3.5 h-3.5 text-accent" />
                  Retrieved
                  <span className="font-mono text-accent">{allChunks.length}</span>
                </button>
              )}
              {turn.citations.length > 0 && (
                <button
                  onClick={() => { setPanelCiteNum(null); setPanelOpen(true); }}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full
                             surface text-2xs text-neutral-300 hover:text-neutral-100
                             hover:bg-white/[0.05] transition-colors"
                  title="View all citations"
                >
                  <FileText className="w-3.5 h-3.5 text-accent" />
                  Citations
                  <span className="font-mono text-accent">{turn.citations.length}</span>
                </button>
              )}
            </div>
          )}

          {/* Suggested follow-up questions — clickable chips below the toolbar.
              Click loads the question into the input bar; the user can hit
              Enter to dispatch it as a fresh turn. */}
          {turn.status === "done" && turn.followups && turn.followups.length > 0 && (
            <div className="mt-5">
              <div className="text-2xs uppercase tracking-wider text-neutral-400 font-semibold mb-2">
                Suggested follow-ups
              </div>
              <div>
                {turn.followups.slice(0, 3).map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setPendingInput(q)}
                    className="group w-full flex items-start gap-2.5 px-2 py-2.5 rounded
                               hover:bg-white/[0.04] transition-colors text-left
                               border-b border-dotted border-neutral-700/60"
                    title="Click to load into input"
                  >
                    <CornerDownRight
                      className="w-4 h-4 mt-0.5 text-neutral-500 group-hover:text-accent shrink-0 transition-colors"
                      strokeWidth={2}
                    />
                    <span className="text-sm text-neutral-300 group-hover:text-neutral-50 flex-1 leading-snug transition-colors">
                      {q}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Full citations panel (toolbar only) */}
        <CitationPreview
          open={panelOpen}
          citations={turn.citations}
          citation={panelCitation}
          allChunks={allChunks}
          citationRemap={turn.citationRemap}
          onClose={() => { setPanelOpen(false); setPanelCiteNum(null); }}
          onSelectCitation={(num) => setPanelCiteNum(num)}
          onBack={() => setPanelCiteNum(null)}
        />

        {/* Retrieved-Data panel — open from Top-Passage clicks or the toolbar. */}
        <RetrievedDataPanel
          open={retrievedOpen}
          subqueries={turn.subqueries}
          preselect={retrievedPreselect}
          onClose={() => { setRetrievedOpen(false); setRetrievedPreselect(null); }}
        />
      </div>
    </article>
  );
}

/* ── Sub-answer card ──────────────────────────────────────────────────────── */

interface SubAnswerCardProps {
  sq: SubqueryState;
  finalReady: boolean;
  citations: Citation[];
  citationRemap?: Record<number, number>;
  onCiteClick: (num: number) => void;
}

function SubAnswerCard({ sq, finalReady, citations, citationRemap, onCiteClick }: SubAnswerCardProps) {
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override === null ? !finalReady : override;

  const status: "running" | "done" | "failed" =
    sq.cancelled ? "failed" : sq.errorMsg ? "failed" : sq.done ? "done" : "running";

  return (
    <div className="rounded-xl border border-accent/25 bg-accent/[0.04] overflow-hidden">
      <button
        onClick={() => setOverride(!open)}
        className="w-full flex items-start gap-2.5 px-4 py-3 text-left hover:bg-accent/[0.06] transition-colors"
      >
        <span className="mt-0.5 shrink-0">
          {status === "running"
            ? <Loader2 className="w-4 h-4 text-accent animate-spin" />
            : status === "done"
              ? <CheckCircle2 className="w-4 h-4 text-good" />
              : <span className="block w-3.5 h-3.5 rounded-full bg-bad/30 border border-bad/60" />}
        </span>
        <span className="text-2xs font-mono text-accent/80 uppercase tracking-wider shrink-0 mt-0.5">
          Q{sq.index + 1}
        </span>
        <span className="text-sm text-neutral-100 flex-1 min-w-0 break-words">{sq.query}</span>
        <ChevronDown
          className={`w-4 h-4 text-neutral-400 transition-transform duration-200 shrink-0 mt-0.5 ${open ? "rotate-180" : ""}`}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-1 border-t border-accent/10 bg-bg/30">
              {sq.tokens.length === 0 && !sq.done ? (
                <MiniTrackerRow sq={sq} />
              ) : (
                <Answer
                  markdown={sq.tokens || (sq.done ? "(no answer)" : "…")}
                  citations={citations}
                  citationRemap={citationRemap}
                  onCiteClick={onCiteClick}
                  isStreaming={!sq.done}
                />
              )}
              {sq.cancelled && <div className="text-xs text-bad/80 mt-1">Stopped.</div>}
              {sq.errorMsg && <div className="text-xs text-bad mt-1">{sq.errorMsg}</div>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Toolbar button ───────────────────────────────────────────────────────── */

function ToolbarButton({
  title, onClick, active, children,
}: {
  title: string; onClick: () => void; active?: boolean; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`inline-flex items-center justify-center w-7 h-7 rounded-md transition-colors
                  ${active
                    ? "bg-accent/15 text-accent"
                    : "text-neutral-500 hover:text-neutral-200 hover:bg-white/[0.04]"}`}
    >
      {children}
    </button>
  );
}

