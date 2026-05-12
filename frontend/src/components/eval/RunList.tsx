import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { api } from "../../lib/api";
import { ms } from "../../lib/format";
import type { EvalRunSummary } from "../../lib/types";

interface Props {
  selected: string | null;
  onSelect: (runId: string) => void;
}

export default function RunList({ selected, onSelect }: Props) {
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.evalRuns()
      .then((r) => {
        if (!alive) return;
        setRuns(r);
        // Auto-select the most recent run on first load so the detail pane
        // shows the latest metrics immediately. Backend already returns
        // newest-first (sorted by timestamp).
        if (!selected && r.length > 0) onSelect(r[0].run_id);
      })
      .catch(() => alive && setRuns([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="overflow-y-auto scroll-thin">
      <div className="px-3 py-2.5 text-xs uppercase tracking-wider text-neutral-200 font-semibold sticky top-0 bg-surface border-b hairline">
        Eval runs
      </div>
      {loading && <div className="px-3 py-3 text-2xs text-neutral-500">Loading runs…</div>}
      {!loading && runs.length === 0 && (
        <div className="px-3 py-3 text-2xs text-neutral-500">
          No eval runs yet. Run <code className="font-mono text-neutral-400">python evals/run_eval.py --v6-smoke</code>.
        </div>
      )}
      <ul>
        {runs.map((r) => {
          const s = r.summary || {};
          const avgM7 = typeof s.avg_m7 === "number" ? s.avg_m7 :
                        typeof s.avg_m7_judge === "number" ? s.avg_m7_judge :
                        typeof s.avg?.m7 === "number" ? s.avg.m7 : null;
          const verdicts = s.verdicts || {};
          return (
            <li
              key={r.run_id}
              onClick={() => onSelect(r.run_id)}
              className={`group px-3 py-2.5 cursor-pointer border-b hairline transition-colors ${
                selected === r.run_id ? "bg-white/[0.04] border-l-2 border-l-accent" : "hover:bg-white/[0.02]"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-neutral-100 truncate flex-1">{r.run_id}</span>
                <ChevronRight className={`w-4 h-4 text-neutral-400 ${selected === r.run_id ? "rotate-90" : ""} transition-transform`} />
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-2xs text-neutral-300">
                {avgM7 !== null && <span>avg M7: <span className="text-neutral-100 font-medium">{avgM7.toFixed(2)}</span></span>}
                {verdicts.pass !== undefined && <span className="chip chip-good">{verdicts.pass} pass</span>}
                {verdicts.partial !== undefined && <span className="chip chip-warn">{verdicts.partial}</span>}
                {verdicts.fail !== undefined && <span className="chip chip-bad">{verdicts.fail}</span>}
                {typeof s.avg_latency_ms === "number" && (
                  <span className="ml-auto font-mono">{ms(s.avg_latency_ms)}</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
