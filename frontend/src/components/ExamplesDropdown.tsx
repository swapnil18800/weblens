import { useEffect, useRef, useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import { useChat } from "../state/chatStore";

// Emergency fallback only — the real list comes from /question_examples.json
const FALLBACK_EXAMPLES = [
  "What is the current population of Brazil?",
  "Compare GPT-4o, Claude Opus, and Gemini 2.5 Pro.",
  "What are the most recent advances in mixture-of-experts models?",
  "How have NVIDIA's data center revenues changed over the last 3 years?",
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
    fetch("/question_examples.json")
      .then((res) => res.json())
      .then((data) => {
        let questions: string[] = [];
        if (data && data.examples && Array.isArray(data.examples.questions)) {
          questions = data.examples.questions;
        }
        setItems(questions.length ? questions : FALLBACK_EXAMPLES);
      })
      .catch(() => {/* fallback used */});
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
