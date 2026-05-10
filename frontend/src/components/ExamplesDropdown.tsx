import { useEffect, useRef, useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import { useChat } from "../state/chatStore";

const FALLBACK_EXAMPLES = [
  "What would happen if the US and China entered a full-scale AI cold war?",
  "Why are economists warning that AI could wipe out white-collar jobs faster than expected?",
  "How did NVIDIA become one of the most powerful companies in the world almost overnight?",
  "What are the strongest arguments for and against banning TikTok worldwide?",
  "How did inflation, layoffs, and AI hype completely reshape Big Tech from 2023–2026?",
  "What happened during the latest Israel–Iran tensions, and why is the world reacting differently?",
  "How have Spotify, TikTok, and YouTube completely changed how songs become globally viral?",
  "Why are modern movies and streaming shows increasingly criticized despite billion-dollar budgets?",
  "How did Real Madrid, Manchester City, and PSG spend differently over the last 5 years?",
  "Why are Gen Z users increasingly moving away from traditional social media platforms?",
  "Compare Drake, Taylor Swift, and BTS in streaming dominance, touring revenue, and cultural influence.",
  "How did OpenAI, Google, and Anthropic react after the latest major AI model releases?",
  "Why are billionaires building underground bunkers and preparing for global instability?",
  "Could AI make traditional college degrees significantly less valuable?",
  "How are football transfer fees, wages, and sponsorships changing the economics of top clubs?",
  "What are the biggest criticisms and defenses of Elon Musk’s leadership across Tesla, SpaceX, and X?"
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
