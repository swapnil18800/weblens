import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { api } from "../../lib/api";
import { evalQuestionToTurn, m7ChipClass } from "../../lib/eval-adapter";
import { ms } from "../../lib/format";
import type { Citation, EvalQuestion, EvalRunDetail } from "../../lib/types";
import Answer from "../Answer";
import CitationList from "../CitationList";
import CitationPreview from "../CitationPreview";
import ReasoningTrace from "../ReasoningTrace";

interface Props {
  runId: string | null;
}

export default function QuestionDetail({ runId }: Props) {
  const [detail, setDetail] = useState<EvalRunDetail | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!runId) { setDetail(null); return; }
    setLoading(true);
    api.evalRunDetail(runId)
      .then((d) => { setDetail(d); setSelectedIdx(0); })
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [runId]);

  if (!runId) {
    return (
      <div className="flex-1 flex items-center justify-center text-2xs text-neutral-500">
        Select a run on the left to view question details.
      </div>
    );
  }
  if (loading) {
    return <div className="px-4 py-6 text-2xs text-neutral-500">Loading run…</div>;
  }
  if (!detail) {
    return <div className="px-4 py-6 text-2xs text-neutral-500">Failed to load run.</div>;
  }

  const q = detail.questions[selectedIdx];
  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="w-72 border-r hairline overflow-y-auto scroll-thin shrink-0">
        <div className="px-3 py-2 text-2xs uppercase tracking-wider text-neutral-300 font-semibold sticky top-0 bg-surface border-b hairline">
          {detail.questions.length} questions
        </div>
        <ul>
          {detail.questions.map((qq, i) => (
            <QListRow key={i} q={qq} idx={i} selected={i === selectedIdx} onClick={() => setSelectedIdx(i)} />
          ))}
        </ul>
      </div>
      <div className="flex-1 overflow-y-auto scroll-thin">
        {q && <QDetailBody q={q} />}
      </div>
    </div>
  );
}

function QListRow({ q, idx, selected, onClick }: { q: EvalQuestion; idx: number; selected: boolean; onClick: () => void }) {
  const m7 = q.metrics?.m7_judge_score;
  const verdict = q.verdict;
  const chip =
    verdict === "pass" ? "chip-good" :
    verdict === "partial" ? "chip-warn" :
    verdict === "fail" ? "chip-bad" : "chip-info";
  return (
    <li
      onClick={onClick}
      className={`group px-3 py-2.5 cursor-pointer border-b hairline transition-colors ${
        selected ? "bg-white/[0.04] border-l-2 border-l-accent" : "hover:bg-white/[0.02]"
      }`}
    >
      <div className="flex items-start gap-2">
        <span className="font-mono text-2xs text-neutral-600 mt-0.5 shrink-0">{(idx + 1).toString().padStart(2, "0")}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-neutral-200 line-clamp-2">{q.question}</div>
          <div className="mt-1 flex items-center gap-1.5 text-2xs text-neutral-500 flex-wrap">
            {q.category && <span className="font-mono text-neutral-600">{q.category}</span>}
            {verdict && <span className={`chip ${chip}`}>{verdict}</span>}
            {m7 !== undefined && <span>M7: <span className="text-neutral-300">{m7.toFixed(2)}</span></span>}
          </div>
        </div>
      </div>
    </li>
  );
}

function QDetailBody({ q }: { q: EvalQuestion }) {
  const turn = useMemo(() => evalQuestionToTurn(q), [q]);
  const m1 = q.metrics?.m1_factual_correctness;
  const m3 = q.metrics?.m3_retrieval_recall;
  const m7 = q.metrics?.m7_judge_score;
  const totalMs = q.timing?.total_latency_ms ?? (q.timing?.pipeline_s ? Math.round(q.timing.pipeline_s * 1000) : undefined);
  const verdict = q.verdict;
  const chip =
    verdict === "pass" ? "chip-good" :
    verdict === "partial" ? "chip-warn" :
    verdict === "fail" ? "chip-bad" : "chip-info";

  const citations = q.pipeline?.citations || [];

  // Citation preview state — same UX as chat
  const [previewNum, setPreviewNum] = useState<number | null>(null);
  const previewCitation: Citation | null =
    previewNum !== null ? (citations.find((c) => c.num === previewNum) || null) : null;
  const allChunks = useMemo(
    () => turn.subqueries.flatMap((sq) => sq.chunks),
    [turn.subqueries],
  );

  const onCiteClick = (num: number) => setPreviewNum(num);

  return (
    <div className="px-4 sm:px-6 py-6 max-w-4xl mx-auto">
      <div className="text-2xs uppercase tracking-wider text-neutral-300 font-semibold mb-1">Question</div>
      <h2 className="text-base text-neutral-100 mb-4">{q.question}</h2>

      <div className="flex flex-wrap gap-2 mb-5 text-2xs">
        {verdict && <span className={`chip ${chip}`}>{verdict}</span>}
        {m1 !== undefined && <span className="chip chip-info">M1 {m1.toFixed(2)}</span>}
        {m3 !== undefined && <span className="chip chip-info">M3 {m3.toFixed(2)}</span>}
        {m7 !== undefined && <span className={`chip ${m7ChipClass(m7)}`}>M7 {m7.toFixed(2)}</span>}
        {totalMs !== undefined && <span className="chip chip-metric">{ms(totalMs)}</span>}
        <span className="chip chip-info">{turn.subqueries.reduce((n, s) => n + s.chunks.length, 0)} chunks</span>
        <span className="chip chip-info">{(q.pipeline?.urls?.length ?? 0)} sources</span>
      </div>

      {/* Final answer */}
      <Section title="Final answer" defaultOpen rightChip={totalMs !== undefined ? `${ms(totalMs)}` : undefined}>
        {q.pipeline?.answer ? (
          <Answer markdown={q.pipeline.answer} citations={citations} onCiteClick={onCiteClick} />
        ) : (
          <div className="text-2xs text-neutral-300 italic">No answer (error: {q.pipeline?.error || "unknown"}).</div>
        )}
      </Section>

      {/* Reasoning trace — same component as chat */}
      <div className="mb-4">
        <ReasoningTrace turn={turn} defaultOpen />
      </div>

      {/* Citations — clickable rows that open the preview */}
      <CitationList citations={citations} onCiteClick={onCiteClick} anchorId={`eval-${q.question.slice(0,20)}`} />

      <CitationPreview
        open={previewNum !== null}
        citations={citations}
        citation={previewCitation}
        allChunks={allChunks}
        onClose={() => setPreviewNum(null)}
        onSelectCitation={(num) => setPreviewNum(num)}
        onBack={() => setPreviewNum(null)}
      />


      {/* Ground truth */}
      {q.ground_truth && (
        <Section title="Ground truth">
          <div className="text-sm text-neutral-300 whitespace-pre-wrap">{q.ground_truth}</div>
        </Section>
      )}
      {Array.isArray(q.key_facts) && q.key_facts.length > 0 && (
        <Section title={`Key facts (${q.key_facts.length})`}>
          <ul className="list-disc pl-5 space-y-1 text-sm text-neutral-300">
            {q.key_facts.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </Section>
      )}

      {/* Judge */}
      {q.judge_reasoning && (
        <Section
          title="Judge reasoning"
          rightChip={m7 !== undefined ? `M7 ${m7.toFixed(2)}` : undefined}
          rightChipClass={m7 !== undefined ? m7ChipClass(m7) : undefined}
        >
          <div className="text-sm text-neutral-300 whitespace-pre-wrap">{q.judge_reasoning}</div>
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  defaultOpen = false,
  children,
  rightChip,
  rightChipClass = "chip-metric",
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  rightChip?: string;
  rightChipClass?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="surface rounded-lg overflow-hidden mb-4">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/[0.02]"
      >
        <ChevronRight className={`w-3.5 h-3.5 text-neutral-500 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="text-2xs uppercase tracking-wider text-neutral-300 font-semibold">{title}</span>
        {rightChip && <span className={`chip ${rightChipClass} font-mono ml-auto`}>{rightChip}</span>}
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
            <div className="px-3 pb-3 pt-1 border-t hairline">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
