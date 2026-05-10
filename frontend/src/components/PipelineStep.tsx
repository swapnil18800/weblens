import { useState } from "react";
import { motion } from "framer-motion";
import {
  ChevronRight, Cpu, GitMerge, Globe, Layers, ListTree,
  Search, Sparkles, Wand2, Zap,
} from "lucide-react";
import type { ChunkDict, ReasoningStep } from "../lib/types";
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
  onChunkClick?: (chunk: ChunkDict) => void;
}

export default function PipelineStep({ step, onChunkClick }: Props) {
  const [open, setOpen] = useState(false);
  const Icon = ICONS[step.kind] || Sparkles;
  // Rerank step's payload is a `{chunks: []}` placeholder filled in later by
  // sub_answer_start; treat empty chunks as no-payload so the row isn't clickable.
  const hasPayload = !!step.payload && !(step.kind === "rerank" && (step.payload?.chunks?.length ?? 0) === 0);
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
          <PayloadView step={step} onChunkClick={onChunkClick} />
        </div>
      )}
    </div>
  );
}

function PayloadView({ step, onChunkClick }: { step: ReasoningStep; onChunkClick?: (chunk: ChunkDict) => void }) {
  const p = step.payload;
  if (step.kind === "search" && Array.isArray(p?.urls)) {
    return (
      <ul className="space-y-1 py-1">
        {p.urls.map((u: any, i: number) => (
          <li key={i} className="flex items-center gap-2">
            <span className="text-neutral-500 w-6 shrink-0 font-mono">{i + 1}.</span>
            <a
              href={u.url}
              target="_blank"
              rel="noreferrer"
              className="text-neutral-200 hover:text-accent truncate flex-1 min-w-0"
              title={u.url}
            >
              {u.title || shortHost(u.url)}
            </a>
            <span className="text-neutral-500 font-mono text-2xs shrink-0">
              ({shortHost(u.url)})
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (step.kind === "extract") {
    const pages = Array.isArray(p?.pages) ? p.pages : [];
    const enriched = !!p?.enriched;
    if (enriched) {
      // New per-sub-query shape: each row has { url, title, status, char_count }.
      // Backend already sorted them: successes by chars desc, failures at the bottom.
      return (
        <ul className="space-y-1 py-1">
          {pages.map((page: any, i: number) => (
            <li key={i} className="flex items-center gap-2">
              <span className="text-neutral-500 w-6 shrink-0 font-mono">{i + 1}.</span>
              <a
                href={page.url}
                target="_blank"
                rel="noreferrer"
                className="text-neutral-200 hover:text-accent truncate flex-1 min-w-0"
                title={page.url}
              >
                {page.title || shortHost(page.url)}
              </a>
              <ExtractStatusChip status={page.status} charCount={page.char_count} />
            </li>
          ))}
        </ul>
      );
    }
    // Legacy fallback (un-partitioned global event): old layout.
    const failures = Array.isArray(p?.failures) ? p.failures : [];
    return (
      <div className="space-y-1 py-1">
        <ul className="space-y-1">
          {pages.map((page: any, i: number) => (
            <li key={i} className="flex items-center gap-2">
              <span className="text-good w-6 shrink-0 font-mono">{i + 1}.</span>
              <span className="text-neutral-300 truncate flex-1 min-w-0">{shortHost(page.url)}</span>
              <span className="text-neutral-500">·</span>
              <span className="text-info">{chars(page.char_count)}</span>
              {page.from_cache && <span className="chip chip-info ml-1">cached</span>}
            </li>
          ))}
        </ul>
        {failures.length > 0 && (
          <details className="mt-1.5">
            <summary className="cursor-pointer text-neutral-400 hover:text-neutral-200 text-2xs">
              {failures.length} skipped
            </summary>
            <ul className="space-y-1 mt-1 pl-2">
              {failures.map((f: any, i: number) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="text-bad/70 w-6 shrink-0">×</span>
                  <span className="text-neutral-500 truncate flex-1 min-w-0">{shortHost(f.url)}</span>
                  <span className="text-neutral-600">·</span>
                  <span className="text-bad/80 font-mono text-2xs">{f.reason}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    );
  }
  if (step.kind === "rerank" && Array.isArray(p?.chunks)) {
    const chunks: ChunkDict[] = p.chunks;
    return (
      <ul className="space-y-1.5 py-1">
        {chunks.map((c, i) => (
          <li
            key={i}
            onClick={() => onChunkClick?.(c)}
            className={`text-2xs text-neutral-300 flex items-start gap-2 px-2 py-1.5 rounded-lg
                        bg-white/[0.025] transition-colors
                        ${onChunkClick ? "cursor-pointer hover:bg-white/[0.05]" : ""}`}
            role={onChunkClick ? "button" : undefined}
            tabIndex={onChunkClick ? 0 : undefined}
            onKeyDown={(e) => {
              if (onChunkClick && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onChunkClick(c);
              }
            }}
          >
            <span className="font-mono text-neutral-500 w-6 shrink-0">#{c.rank + 1}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-neutral-100 truncate">{c.title || shortHost(c.url)}</span>
                <span className="text-neutral-500 truncate">{shortHost(c.url)}</span>
              </div>
              {c.heading && <div className="font-mono text-neutral-500 truncate">{c.heading}</div>}
              <div className="mt-1 text-neutral-400 line-clamp-2">
                {c.chunk_text.slice(0, 220)}
                {c.chunk_text.length > 220 && "…"}
              </div>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return <pre className="font-mono whitespace-pre-wrap text-neutral-400 py-1">{JSON.stringify(p, null, 2)}</pre>;
}

const STATUS_CHIP_STYLES: Record<string, { label: string; cls: string }> = {
  extracted:   { label: "extracted",   cls: "bg-good/15 text-good border-good/25" },
  cached:      { label: "cached",      cls: "bg-info/15 text-info border-info/25" },
  http_error:  { label: "http error",  cls: "bg-bad/15 text-bad border-bad/25" },
  too_short:   { label: "too short",   cls: "bg-warn/15 text-warn border-warn/25" },
  parse_error: { label: "parse error", cls: "bg-bad/15 text-bad border-bad/25" },
};

function ExtractStatusChip({ status, charCount }: { status: string; charCount: number }) {
  const style = STATUS_CHIP_STYLES[status] || STATUS_CHIP_STYLES.http_error;
  const succeeded = status === "extracted" || status === "cached";
  return (
    <span
      className={`shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                  border text-2xs font-mono ${style.cls}`}
    >
      <span>{style.label}</span>
      {succeeded && charCount > 0 && (
        <>
          <span className="opacity-50">·</span>
          <span>{chars(charCount)}</span>
        </>
      )}
    </span>
  );
}
