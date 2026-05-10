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
  const breakdown: Record<string, any> = q.timing?.latency_breakdown || {};
  const totalMs =
    q.timing?.total_latency_ms ??
    (q.timing?.pipeline_s ? Math.round(q.timing.pipeline_s * 1000) : undefined);

  // Distribute chunks across sub-queries by index modulo (best effort — eval JSON
  // doesn't preserve per-Q split).
  const perSqChunks: ChunkDict[][] = subQueries.map(() => []);
  allChunks.forEach((c, i) => {
    perSqChunks[i % subQueries.length].push(c);
  });

  // Match the live trace exactly: Search → Read pages → Split → Indexed → Picked best → Drafted answer.
  const pageCount = breakdown.pages_count ?? allUrls.length;
  const passageCount = breakdown.chunks_count ?? allChunks.length;
  const answer = q.pipeline?.answer || "";
  const wc = answer.trim() ? answer.trim().split(/\s+/).length : 0;

  const subqueries: SubqueryState[] = subQueries.map((sq, idx) => {
    const myChunks = perSqChunks[idx];
    const steps: ReasoningStep[] = [];
    const subTotalMs = totalMs ? Math.round(totalMs / Math.max(1, subQueries.length)) : 0;

    if (allUrls.length) {
      steps.push(step("search", "Searched the web",
        `Found ${allUrls.length} source${allUrls.length === 1 ? "" : "s"}`,
        { urls: allUrls, query: sq }, breakdown.search_ms));
    }
    if (pageCount > 0) {
      steps.push(step("extract", "Read pages",
        `Read ${pageCount} page${pageCount === 1 ? "" : "s"}`,
        null, breakdown.extract_ms));
    }
    if (passageCount > 0) {
      steps.push(step("chunk", "Split into passages",
        `Built ${passageCount} passage${passageCount === 1 ? "" : "s"}`,
        null, breakdown.chunk_ms));
      steps.push(step("embed", "Indexed passages",
        `${passageCount} passage${passageCount === 1 ? "" : "s"} ready for ranking`,
        null, breakdown.embed_ms ?? breakdown.retrieve_ms));
    }
    if (myChunks.length) {
      steps.push(step("rerank", "Picked best evidence",
        `Selected top ${myChunks.length} passage${myChunks.length === 1 ? "" : "s"}`,
        { candidates: allChunks.length, top_k: myChunks.length,
          max_score: Math.max(...myChunks.map((c) => c.score || 0)),
          min_score: Math.min(...myChunks.map((c) => c.score || 0)) },
        breakdown.rerank_ms ?? breakdown.retrieve_ms,
      ));
    }
    steps.push(step("generate", "Drafted answer",
      idx === 0 && wc ? `${wc} word${wc === 1 ? "" : "s"}` : "complete",
      null, subTotalMs,
    ));

    return {
      index: idx,
      query: sq,
      steps,
      tokens: idx === 0 ? answer : "",
      done: true,
      chunks: myChunks,
      urls: allUrls,
      citations: q.pipeline?.citations || [],
      startedAt: 0,
      completedAt: subTotalMs,
    };
  });

  const pipeline: PipelineGlobals = {
    decomposeMs: breakdown.decompose_ms,
    decomposeMode: breakdown.decompose_mode,
    searchMs: breakdown.search_ms,
    extractMs: breakdown.extract_ms,
    chunkMs: breakdown.chunk_ms,
    embedMs: breakdown.embed_ms ?? breakdown.retrieve_ms,
    embedDevice: breakdown.embed_device,
    retrieveMs: breakdown.retrieve_ms,
    rerankMs: breakdown.rerank_ms ?? breakdown.retrieve_ms,
    totalChunks: passageCount,
  };

  return {
    id: `eval-${q.question.slice(0, 40)}`,
    versionGroupId: `eval-grp-${q.question.slice(0, 40)}`,
    versionIndex: 0,
    question: q.question,
    status: "done",
    subQueries,
    subqueries,
    pipeline,
    synthesisMd: answer,
    synthesizing: false,
    citations: q.pipeline?.citations || [],
    totalLatencyMs: totalMs,
    createdAt: 0,
    // Render synthesis-phase rows so eval traces match the live trace structure.
    combiningStatus: "done",
    finalStatus: "done",
    combiningStartedAt: 0,
    combiningCompletedAt: 0,
    finalStartedAt: 0,
    finalCompletedAt: breakdown.synthesis_ms || 0,
  };
}

/** M7 score → chip class. */
export function m7ChipClass(score: number | undefined): string {
  if (score === undefined) return "chip-info";
  if (score >= 0.9) return "chip-good";
  if (score >= 0.5) return "chip-warn";
  return "chip-bad";
}
