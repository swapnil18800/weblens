import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { useChat } from "../state/chatStore";
import Logo from "./Logo";

// Emergency fallback only — real chips come from /question_examples.json
const FALLBACK_CHIPS = [
  "What is the current population of Brazil?",
  "Who won the FIFA World Cup in 2022?",
  "Compare GPT-4o, Claude Opus, and Gemini 2.5 Pro.",
  "What are the most recent advances in mixture-of-experts models?",
  "How have NVIDIA's data center revenues changed over the last 3 years?",
  "What is the current status of the Russia-Ukraine conflict?",
  "What's the latest Anthropic Claude model as of mid-2026?",
  "How do US, EU, and China approach AI regulation?",
];

export default function Hero() {
  const setPendingInput = useChat((s) => s.setPendingInput);
  const [chips, setChips] = useState<string[] | null>(null);

  useEffect(() => {
    fetch("/question_examples.json")
      .then((res) => res.json())
      .then((data) => {
        let questions: string[] = [];
        if (data && data.examples && Array.isArray(data.examples.questions)) {
          questions = data.examples.questions;
        }

        if (questions.length >= 8) {
          const shuffled = questions.slice().sort(() => Math.random() - 0.5);
          setChips(shuffled.slice(0, 8));
        } else {
          setChips(FALLBACK_CHIPS);
        }
      })
      .catch(() => setChips(FALLBACK_CHIPS));
  }, []);

  return (
    <div className="flex-1 overflow-y-auto scroll-fat relative">
      {/* Subtle radial gradient backdrop */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-0"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 18%, rgba(91,140,255,0.10) 0%, rgba(91,140,255,0.0) 70%)",
        }}
      />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.22 }}
        className="relative px-4 sm:px-6 pt-14 sm:pt-20 pb-8 max-w-3xl w-full mx-auto"
      >
        <div className="text-center mb-10">
          <div className="inline-block">
            <Logo size="lg" animate />
          </div>
          <p className="mt-4 text-base sm:text-lg text-neutral-200">
            Hi — what would you like to look up today?
          </p>
          <p className="mt-1.5 text-2xs sm:text-xs text-neutral-400 max-w-md mx-auto">
            Grounded answers, with the receipts. Ask anything; WebLens decomposes,
            searches, retrieves, ranks, and cites — all visible in the trace.
          </p>
        </div>

        <div className="w-full">
          <div className="text-2xs uppercase tracking-wider text-neutral-300 font-semibold mb-2 px-1">
            Try one of these
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {chips === null
              ? Array.from({ length: 8 }).map((_, i) => (
                  <div
                    key={i}
                    className="surface rounded-lg min-h-[68px] px-4 py-3 animate-pulse
                               flex flex-col gap-2"
                  >
                    <div className="h-3 bg-white/10 rounded-full w-5/6" />
                    <div className="h-3 bg-white/5 rounded-full w-3/5" />
                  </div>
                ))
              : chips.slice(0, 8).map((q, i) => (
                  <motion.button
                    key={i}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.04 * i, duration: 0.18 }}
                    onClick={() => setPendingInput(q)}
                    className="group text-left text-sm px-4 py-3 surface rounded-lg
                               hover:bg-white/[0.05] hover:border-accent/30
                               transition-colors min-h-[68px] leading-snug
                               flex items-start justify-between gap-2"
                  >
                    <span className="text-neutral-200 group-hover:text-neutral-100 flex-1">{q}</span>
                    <ArrowUpRight className="w-3.5 h-3.5 text-neutral-500 group-hover:text-accent shrink-0 mt-0.5" />
                  </motion.button>
                ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
