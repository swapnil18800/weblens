import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, Database } from "lucide-react";
import { api } from "../../lib/api";
import { evalQuestionToTurn, m7ChipClass } from "../../lib/eval-adapter";
import { ms } from "../../lib/format";
import type { CachedRow, Citation, EvalQuestion, EvalRunDetail } from "../../lib/types";
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
        {detail.cached_rows && detail.cached_rows.length > 0 && (
          <CachedRowsPanel rows={detail.cached_rows} />
        )}
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

// Order + friendly labels for every metric the evaluator may emit.
const METRIC_ORDER: { key: string; label: string; headline?: boolean }[] = [
  { key: "m1_factual_correctness", label: "M1 Factual",      headline: true },
  { key: "m3_retrieval_recall",    label: "M3 Retrieval",    headline: true },
  { key: "m7_judge_score",         label: "M7 Judge",        headline: true },
  { key: "aggregate",              label: "Aggregate",       headline: true },
  { key: "faithfulness",           label: "Faithfulness" },
  { key: "context_recall",         label: "Context recall" },
  { key: "context_precision",      label: "Context precision" },
  { key: "answer_correctness",     label: "Answer correctness" },
  { key: "answer_relevancy",       label: "Answer relevancy" },
  { key: "routing_decomposition",  label: "Routing/decompose" },
];

function metricChipClass(key: string, score: number): string {
  if (key === "m7_judge_score") return m7ChipClass(score);
  if (score >= 0.8) return "chip-good";
  if (score >= 0.5) return "chip-warn";
  return "chip-bad";
}

function QDetailBody({ q }: { q: EvalQuestion }) {
  const turn = useMemo(() => evalQuestionToTurn(q), [q]);
  const metrics = (q.metrics || {}) as Record<string, number | undefined>;
  const m7 = metrics.m7_judge_score;
  const totalMs = q.timing?.total_latency_ms ?? (q.timing?.pipeline_s ? Math.round(q.timing.pipeline_s * 1000) : undefined);
  const verdict = q.verdict;
  const chip =
    verdict === "pass" ? "chip-good" :
    verdict === "partial" ? "chip-warn" :
    verdict === "fail" ? "chip-bad" : "chip-info";

  // Build the visible metric chip list — known metrics in canonical order, then
  // any extras the JSON might add later.
  const knownKeys = new Set(METRIC_ORDER.map((m) => m.key));
  const extraKeys = Object.keys(metrics).filter(
    (k) => !knownKeys.has(k) && typeof metrics[k] === "number",
  );

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

      <div className="flex flex-wrap gap-2 mb-3 text-2xs">
        {verdict && <span className={`chip ${chip}`}>{verdict}</span>}
        {METRIC_ORDER.filter((m) => m.headline && typeof metrics[m.key] === "number").map((m) => (
          <span key={m.key} className={`chip ${metricChipClass(m.key, metrics[m.key]!)}`}>
            {m.label} {metrics[m.key]!.toFixed(2)}
          </span>
        ))}
        {totalMs !== undefined && <span className="chip chip-metric">{ms(totalMs)}</span>}
        <span className="chip chip-info">{turn.subqueries.reduce((n, s) => n + s.chunks.length, 0)} chunks</span>
        <span className="chip chip-info">{(q.pipeline?.urls?.length ?? 0)} sources</span>
      </div>

      {/* All metrics — component scores below the headline row */}
      <Section title="All metrics" defaultOpen>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-2xs">
          {METRIC_ORDER.filter((m) => typeof metrics[m.key] === "number").map((m) => (
            <MetricCell key={m.key} label={m.label} value={metrics[m.key]!} colorKey={m.key} />
          ))}
          {extraKeys.map((k) => (
            <MetricCell key={k} label={k.replace(/_/g, " ")} value={metrics[k]!} colorKey={k} />
          ))}
          {Object.keys(metrics).length === 0 && (
            <div className="col-span-full text-neutral-500 italic">No metrics recorded.</div>
          )}
        </div>
      </Section>

      {/* Metric details — judge/faithfulness reasoning, hit/miss facts, etc. */}
      {q.metric_details && Object.keys(q.metric_details).length > 0 && (
        <Section title="Metric details">
          <pre className="text-2xs text-neutral-300 whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">
            {JSON.stringify(q.metric_details, null, 2)}
          </pre>
        </Section>
      )}

      {/* Latency breakdown */}
      {q.timing?.latency_breakdown && Object.keys(q.timing.latency_breakdown).length > 0 && (
        <Section title="Latency breakdown">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-2xs">
            {Object.entries(q.timing.latency_breakdown).map(([k, v]) => (
              <MetricCell key={k} label={k.replace(/_ms$|_s$/, "").replace(/_/g, " ")} value={v} suffix="ms" plain />
            ))}
          </div>
        </Section>
      )}

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

function CachedRowsPanel({ rows }: { rows: CachedRow[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t hairline mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/[0.02]"
      >
        <Database className="w-3 h-3 text-accent shrink-0" />
        <span className="text-2xs text-neutral-400 font-semibold">
          {rows.length} row{rows.length !== 1 ? "s" : ""} cached this run
        </span>
        <ChevronRight className={`w-3 h-3 text-neutral-600 ml-auto transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <ul className="px-3 pb-3 space-y-2">
              {rows.map((r) => (
                <li key={r.query_hash} className="text-2xs space-y-0.5">
                  <div className="text-neutral-300 line-clamp-2">{r.query_text}</div>
                  <div className="text-neutral-600 font-mono flex gap-2">
                    <span className="chip chip-info">{r.mode}</span>
                    {r.hit_count > 0 && <span className="chip chip-good">{r.hit_count} hit{r.hit_count !== 1 ? "s" : ""}</span>}
                    {r.inserted_at && <span>{new Date(r.inserted_at).toLocaleTimeString()}</span>}
                  </div>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function MetricCell({
  label,
  value,
  colorKey,
  suffix,
  plain,
}: {
  label: string;
  value: number;
  colorKey?: string;
  suffix?: string;
  plain?: boolean;
}) {
  const display = suffix === "ms" ? `${Math.round(value)}` : value.toFixed(3);
  const cls = plain
    ? "text-neutral-300"
    : (() => {
        if (colorKey === "m7_judge_score") return "text-accent";
        if (value >= 0.8) return "text-emerald-300";
        if (value >= 0.5) return "text-amber-300";
        return "text-rose-300";
      })();
  return (
    <div className="surface rounded px-2 py-1.5 flex items-baseline gap-1.5">
      <span className="text-neutral-500 capitalize truncate">{label}</span>
      <span className={`ml-auto font-mono font-semibold ${cls}`}>
        {display}{suffix ? <span className="text-neutral-500 font-normal"> {suffix}</span> : null}
      </span>
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
