import { useState } from "react";
import Header from "../components/Header";
import RunList from "../components/eval/RunList";
import QuestionDetail from "../components/eval/QuestionDetail";

export default function EvalPage() {
  const [runId, setRunId] = useState<string | null>(null);

  return (
    <div className="h-full flex flex-col">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <aside className="w-72 border-r hairline bg-surface flex flex-col shrink-0">
          <RunList selected={runId} onSelect={setRunId} />
        </aside>
        <main className="flex-1 flex flex-col overflow-hidden">
          <QuestionDetail runId={runId} />
        </main>
      </div>
    </div>
  );
}
