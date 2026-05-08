import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { api } from "../lib/api";
import { useChat } from "../state/chatStore";
import Logo from "./Logo";

const FALLBACK_CHIPS = [
  "Apple vs Microsoft operating margin FY2024",
  "How does RAG work?",
  "NVIDIA data center revenue trend FY2022–FY2025",
  "What is pgvector used for?",
  "AMD vs Intel vs NVIDIA data center revenue + risk factors FY2023–FY2026",
  "AWS vs Azure vs GCP cloud market share",
  "Compare BM25 and dense retrieval",
  "Tesla FSD progress in FY2023 10-K",
];

export default function Hero() {
  const setPendingInput = useChat((s) => s.setPendingInput);
  const [chips, setChips] = useState<string[]>(FALLBACK_CHIPS);

  useEffect(() => {
    let alive = true;
    api.evalQuestions("v6")
      .then((data) => {
        if (!alive) return;
        const collected: string[] = [];
        if (data && typeof data === "object" && !Array.isArray(data)) {
          for (const k of Object.keys(data)) {
            const v = (data as any)[k];
            if (Array.isArray(v?.questions)) {
              for (const q of v.questions) if (typeof q === "string") collected.push(q);
            }
          }
        }
        if (collected.length) setChips(collected.slice(0, 8));
      })
      .catch(() => { /* fallback used */ });
    return () => { alive = false; };
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
            {chips.slice(0, 8).map((q, i) => (
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
