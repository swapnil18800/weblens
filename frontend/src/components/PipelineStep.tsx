import { useState } from "react";
import { motion } from "framer-motion";
import {
  ChevronRight, Cpu, GitMerge, Globe, Layers, ListTree,
  Search, Sparkles, Wand2, Zap,
} from "lucide-react";
import type { ReasoningStep } from "../lib/types";
import { chars, ms, shortHost } from "../lib/format";
import { Tag } from "./ReasoningTrace";

const ICONS = {
  decompose: Sparkles,
  search: Search,
  extract: Globe,
  chunk: Layers,
  embed: Cpu,
  bm25: ListTree,
  dense: ListTree,
  rrf: GitMerge,
  rerank: Wand2,
  generate: Zap,
} as const;

interface Props {
  step: ReasoningStep;
}

export default function PipelineStep({ step }: Props) {
  const [open, setOpen] = useState(false);
  const Icon = ICONS[step.kind] || Sparkles;
  const hasPayload = !!step.payload;
  const running = step.status === "running";
  const failed = step.status === "failed";

  const iconCls =
    failed ? "text-bad" :
    running ? "text-accent" :
    "text-neutral-400";

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => hasPayload && setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (hasPayload && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        className={`step-row px-2 ${hasPayload ? "" : "cursor-default"}`}
      >
        <motion.span
          className={`shrink-0 ${iconCls}`}
          animate={running ? { rotate: 360 } : { rotate: 0 }}
          transition={running ? { repeat: Infinity, duration: 1.6, ease: "linear" } : { duration: 0 }}
        >
          <Icon className="w-3.5 h-3.5" />
        </motion.span>
        <span className={`text-sm font-medium shrink-0 ${failed ? "text-bad" : "text-neutral-100"}`}>
          {step.label}
        </span>
        <span className="text-xs text-neutral-400 truncate flex-1 min-w-0">
          {step.detail && <>— {step.detail}</>}
        </span>

        {/* latency on the right — green for completed steps, no text while running */}
        {step.latencyMs !== undefined && (
          <Tag color={failed ? "bad" : "good"}>{ms(step.latencyMs)}</Tag>
        )}

        {hasPayload && (
          <ChevronRight
            className={`w-3 h-3 text-neutral-500 transition-transform shrink-0 ${open ? "rotate-90" : ""}`}
          />
        )}
      </div>

      {open && hasPayload && (
        <div className="mt-1 ml-6 pl-3 border-l hairline text-2xs text-neutral-500">
          <PayloadView step={step} />
        </div>
      )}
    </div>
  );
}

function PayloadView({ step }: { step: ReasoningStep }) {
  const p = step.payload;
  if (step.kind === "search" && Array.isArray(p?.urls)) {
    return (
      <ul className="space-y-1 py-1">
        {p.query && (
          <li className="font-mono text-neutral-400 mb-1 truncate">query: {p.query}</li>
        )}
        {p.urls.map((u: any, i: number) => (
          <li key={i} className="flex items-center gap-2">
            <span className="text-neutral-400 w-6 shrink-0">{i + 1}.</span>
            <a
              href={u.url}
              target="_blank"
              rel="noreferrer"
              className="text-neutral-400 hover:text-accent truncate"
              title={u.url}
            >
              {shortHost(u.url)}
            </a>
            {u.title && <span className="text-neutral-400 truncate">— {u.title}</span>}
          </li>
        ))}
      </ul>
    );
  }
  if (step.kind === "extract" && Array.isArray(p?.pages)) {
    return (
      <ul className="space-y-1 py-1">
        {p.pages.map((page: any, i: number) => (
          <li key={i} className="flex items-center gap-2">
            <span className="text-neutral-400 w-6 shrink-0">{i + 1}.</span>
            <span className="text-neutral-400 truncate">{shortHost(page.url)}</span>
            <span className="text-neutral-400">·</span>
            <span className="text-info">{chars(page.char_count)}</span>
            {page.from_cache && <span className="chip chip-info ml-1">cached</span>}
          </li>
        ))}
      </ul>
    );
  }
  if (step.kind === "chunk" && Array.isArray(p?.perPage)) {
    return (
      <ul className="space-y-1 py-1">
        {p.perPage.map((row: any, i: number) => (
          <li key={i} className="flex items-center gap-2">
            <span className="text-neutral-400 w-6 shrink-0">{i + 1}.</span>
            <span className="text-neutral-400 truncate">{shortHost(row.url)}</span>
            <span className="text-neutral-400">·</span>
            <span className="text-info">{row.chunk_count} chunks</span>
          </li>
        ))}
      </ul>
    );
  }
  if (step.kind === "rerank" && p) {
    return (
      <div className="font-mono py-1">
        candidates: {p.candidates} · top: {p.top_k} · score: {p.min_score?.toFixed?.(3)}–{p.max_score?.toFixed?.(3)}
      </div>
    );
  }
  return <pre className="font-mono whitespace-pre-wrap text-neutral-400 py-1">{JSON.stringify(p, null, 2)}</pre>;
}
