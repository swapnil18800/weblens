import { Loader2 } from "lucide-react";
import type { SubqueryState } from "../lib/types";

interface Props { sq: SubqueryState; }

export default function MiniTrackerRow({ sq }: Props) {
  if (sq.tokens.length > 0) return null;

  // Find the most recent step — prefer running, fall back to last completed.
  const steps = sq.steps;
  if (!steps.length) {
    return (
      <div className="flex items-center gap-2 text-2xs text-neutral-400 italic py-1">
        <Loader2 className="w-3 h-3 animate-spin text-accent" />
        Preparing…
      </div>
    );
  }
  const running = [...steps].reverse().find((s) => s.status === "running");
  const latest = running || steps[steps.length - 1];
  const verb = labelToVerb(latest.label);

  return (
    <div className="flex items-center gap-2 text-2xs text-neutral-400 italic py-1">
      <Loader2 className="w-3 h-3 animate-spin text-accent" />
      <span>{verb}</span>
      {latest.detail && <span className="text-neutral-600 truncate">— {latest.detail}</span>}
    </div>
  );
}

function labelToVerb(label: string): string {
  const map: Record<string, string> = {
    "Search":               "searching the web…",
    "Extract":              "extracting page content…",
    "Chunk":                "chunking pages…",
    "Embed":                "embedding chunks…",
    "BM25 candidates":      "running BM25…",
    "Dense candidates":     "running dense retrieval…",
    "RRF fuse":             "fusing rankings…",
    "Cross-encoder rerank": "reranking…",
    "Generate":             "drafting answer…",
  };
  return map[label] || `${label.toLowerCase()}…`;
}
