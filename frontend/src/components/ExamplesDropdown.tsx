import { useEffect, useRef, useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useChat } from "../state/chatStore";

const FALLBACK_EXAMPLES = [
  "Apple vs Microsoft operating margin FY2024",
  "How does RAG work?",
  "NVIDIA data center revenue trend FY2022–FY2025",
  "What is pgvector used for?",
  "AMD vs Intel vs NVIDIA data center revenue + risk factors FY2023–FY2026",
  "Compare BM25 and dense retrieval",
  "Tesla FSD progress in FY2023 10-K",
  "AWS vs Azure vs GCP cloud market share",
];

interface Props {
  onPick?: (q: string) => void;
}

export default function ExamplesDropdown({ onPick }: Props) {
  const setPendingInput = useChat((s) => s.setPendingInput);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<string[]>(FALLBACK_EXAMPLES);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    api
      .evalQuestions("v6")
      .then((data) => {
        if (!alive) return;
        const collected: string[] = [];
        if (Array.isArray(data)) {
          for (const entry of data) {
            if (entry && typeof entry === "object" && Array.isArray(entry.questions)) {
              for (const q of entry.questions) {
                if (typeof q === "string") collected.push(q);
                else if (q && typeof q.question === "string") collected.push(q.question);
              }
            }
          }
        } else if (data && typeof data === "object") {
          // Object with category keys
          for (const k of Object.keys(data)) {
            const v = (data as any)[k];
            if (Array.isArray(v?.questions)) {
              for (const q of v.questions) if (typeof q === "string") collected.push(q);
            } else if (Array.isArray(v)) {
              for (const q of v) if (typeof q === "string") collected.push(q);
            }
          }
        }
        if (collected.length) setItems(collected.slice(0, 12));
      })
      .catch(() => {/* fallback used */});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const pick = (q: string) => {
    setOpen(false);
    if (onPick) onPick(q);
    else setPendingInput(q);
  };

  return (
    <div className="relative" ref={ref}>
      <button className="btn" onClick={() => setOpen((v) => !v)}>
        <Sparkles className="w-4 h-4" />
        <span className="hidden sm:inline">Examples</span>
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-[22rem] max-w-[90vw] surface rounded-md shadow-lg z-40 max-h-[60vh] overflow-y-auto scroll-thin animate-slide-down">
          <ul className="py-1">
            {items.map((q, i) => (
              <li key={i}>
                <button
                  onClick={() => pick(q)}
                  className="w-full text-left text-sm px-3 py-2 hover:bg-white/5 text-neutral-200"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
