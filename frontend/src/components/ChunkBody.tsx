import { useState } from "react";
import { motion } from "framer-motion";
import { ChevronsDown } from "lucide-react";

const CHUNK_COLLAPSED_PX = 140;

interface Props {
  text: string;
  defaultOpen?: boolean;
}

/**
 * Truncated chunk preview with bottom-edge fade and an expand chevron.
 * Used by both CitationPreview and RetrievedDataPanel — keep them visually identical.
 */
export default function ChunkBody({ text, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [overflows, setOverflows] = useState(false);

  const innerRef = (el: HTMLDivElement | null) => {
    if (!el) return;
    setOverflows(el.scrollHeight > CHUNK_COLLAPSED_PX + 4);
  };

  return (
    <div className="relative">
      <motion.div
        animate={{ maxHeight: open ? 4000 : CHUNK_COLLAPSED_PX }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="rounded-lg px-3.5 py-3 text-[14px] text-neutral-100 leading-7
                   whitespace-pre-wrap border border-white/[0.06] overflow-hidden"
        style={{
          backgroundImage:
            "linear-gradient(135deg, rgba(91,140,255,0.06) 0%, rgba(139,92,246,0.06) 100%)",
        }}
      >
        <div ref={innerRef}>{text}</div>
      </motion.div>

      {overflows && !open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Expand full chunk"
          title="Expand"
          className="absolute inset-x-0 bottom-0 flex items-end justify-center pb-1.5
                     rounded-b-lg cursor-pointer group"
          style={{
            height: 56,
            backgroundImage:
              "linear-gradient(to bottom, rgba(10,12,16,0) 0%, rgba(10,12,16,0.85) 70%, rgba(10,12,16,0.95) 100%)",
            backdropFilter: "blur(1px)",
          }}
        >
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-full
                           bg-white/[0.06] border border-white/10 text-neutral-200
                           group-hover:bg-accent/15 group-hover:text-accent
                           transition-colors">
            <ChevronsDown className="w-4 h-4" />
          </span>
        </button>
      )}

      {overflows && open && (
        <div className="mt-2 flex justify-center">
          <button
            onClick={() => setOpen(false)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-2xs
                       bg-white/[0.04] hover:bg-white/[0.08] text-neutral-300
                       hover:text-neutral-100 transition-colors"
          >
            <ChevronsDown className="w-3 h-3 rotate-180" />
            Collapse
          </button>
        </div>
      )}
    </div>
  );
}
