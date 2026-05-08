import type {
  ChunkDict,
  EvalQuestion,
  PipelineGlobals,
  ReasoningStep,
  SubqueryState,
  Turn,
  UrlInfo,
} from "./types";

function step(
  kind: ReasoningStep["kind"],
  label: string,
  detail: string,
  payload?: any,
  latencyMs?: number,
): ReasoningStep {
  return {
    id: `${kind}-${Math.random().toString(36).slice(2, 8)}`,
    kind,
    label,
    detail,
    status: "done",
    payload,
    latencyMs,
  };
}

/** Build a Turn from a persisted EvalQuestion so the same trace UI can render it. */
export function evalQuestionToTurn(q: EvalQuestion): Turn {
  const subQueries = q.pipeline?.sub_queries?.length ? q.pipeline.sub_queries : [q.question];
  const allUrls: UrlInfo[] = q.pipeline?.urls || [];
  const allChunks: ChunkDict[] = q.pipeline?.chunks || [];
  const breakdown = q.timing?.latency_breakdown || {};
  const totalMs =
    q.timing?.total_latency_ms ??
    (q.timing?.pipeline_s ? Math.round(q.timing.pipeline_s * 1000) : undefined);

  // Distribute chunks across sub-queries by index modulo (best effort — eval JSON
  // doesn't preserve per-Q split).
  const perSqChunks: ChunkDict[][] = subQueries.map(() => []);
  allChunks.forEach((c, i) => {
    perSqChunks[i % subQueries.length].push(c);
  });

  const subqueries: SubqueryState[] = subQueries.map((sq, idx) => {
    const myChunks = perSqChunks[idx];
    const steps: ReasoningStep[] = [];
    if (allUrls.length) {
      steps.push(step("search", "Search", `${allUrls.length} URLs`, { urls: allUrls, query: sq }, breakdown.search_ms));
    }
    if (typeof breakdown.extract_ms === "number") {
      steps.push(step("extract", "Extract", `${allUrls.length} pages`, null, breakdown.extract_ms));
    }
    if (typeof breakdown.chunk_ms === "number") {
      steps.push(step("chunk", "Chunk", `${allChunks.length} chunks`, null, breakdown.chunk_ms));
    }
    if (typeof breakdown.retrieve_ms === "number") {
      steps.push(step("rerank", "Cross-encoder rerank",
        `top ${myChunks.length}`,
        myChunks.length
          ? { candidates: allChunks.length, top_k: myChunks.length,
              max_score: Math.max(...myChunks.map((c) => c.score || 0)),
              min_score: Math.min(...myChunks.map((c) => c.score || 0)) }
          : null,
        Math.round((breakdown.retrieve_ms || 0) / Math.max(1, subQueries.length)),
      ));
    }
    steps.push(step("generate", "Generate",
      idx === 0 && q.pipeline?.answer ? `${q.pipeline.answer.split(/\s+/).length} words` : "complete",
      null,
      undefined,
    ));

    return {
      index: idx,
      query: sq,
      steps,
      tokens: idx === 0 ? (q.pipeline?.answer || "") : "",
      done: true,
      chunks: myChunks,
      urls: allUrls,
      citations: q.pipeline?.citations || [],
    };
  });

  const pipeline: PipelineGlobals = {
    decomposeMs: breakdown.decompose_ms,
    searchMs: breakdown.search_ms,
    extractMs: breakdown.extract_ms,
    chunkMs: breakdown.chunk_ms,
    retrieveMs: breakdown.retrieve_ms,
    totalChunks: allChunks.length,
  };

  return {
    id: `eval-${q.question.slice(0, 40)}`,
    question: q.question,
    status: "done",
    subQueries,
    subqueries,
    pipeline,
    synthesisMd: q.pipeline?.answer || "",
    synthesizing: false,
    citations: q.pipeline?.citations || [],
    totalLatencyMs: totalMs,
    createdAt: 0,
  };
}

/** M7 score → chip class. */
export function m7ChipClass(score: number | undefined): string {
  if (score === undefined) return "chip-info";
  if (score >= 0.9) return "chip-good";
  if (score >= 0.5) return "chip-warn";
  return "chip-bad";
}
