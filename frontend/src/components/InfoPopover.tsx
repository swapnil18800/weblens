import { useEffect } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import { X } from "lucide-react";
import Logo from "./Logo";

const WEBLENS_URL = "https://github.com/swapnil18800/web-search-rag";
const LINKEDIN_URL = "https://www.linkedin.com/in/swapnil18800/";
const AUTHOR_NAME = "Swapnil Padhi";

interface Props {
  onClose: () => void;
}

/**
 * Centered modal portaled to <body> so the backdrop blur covers the entire viewport
 * (not just the header). Click outside or Esc to close.
 */
export default function InfoModal({ onClose }: Props) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", esc);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const node = (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="fixed inset-0 z-[100] flex items-center justify-center
                 bg-black/45 backdrop-blur-md px-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.96 }}
        animate={{ opacity: 1, y: 0,  scale: 1 }}
        exit={{ opacity: 0, y: 12, scale: 0.96 }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-xl surface rounded-2xl shadow-2xl
                   p-7 border-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-3 right-3 icon-btn !w-8 !h-8"
          aria-label="Close"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <Logo size="md" />
        </div>

        <div className="text-[15px] text-neutral-200 leading-relaxed mb-5 space-y-3">
          <p>
            <span className="font-semibold text-neutral-50">WebLens</span> is a grounded
            RAG-based web research assistant designed to make AI answers verifiable
            instead of vibes-based.
          </p>
          <p>
            The system decomposes complex queries, performs parallel web retrieval,
            processes and chunks live webpages, and combines sparse retrieval, dense
            embeddings, and reranking pipelines to surface the most relevant evidence
            before generating responses.
          </p>
          <p>
            I built this because I was frustrated by how confidently modern LLMs
            hallucinate. The idea behind WebLens was simple: if an AI gives an answer,
            it should also show the receipts.
          </p>
          <p>
            So instead of hiding retrieval behind the scenes, WebLens exposes the full
            research flow — sources, reasoning traces, retrieval steps, and citations
            — allowing users to validate claims, inspect evidence, and trust the
            output with far more confidence.
          </p>
        </div>

        <div className="border-t hairline pt-4">
          <div className="text-2xs uppercase tracking-wider text-neutral-400 font-semibold mb-2">
            Built &amp; maintained by
          </div>
          <div className="flex items-center justify-between gap-3">
            <div className="text-base font-semibold text-neutral-100">{AUTHOR_NAME}</div>
            <div className="flex items-center gap-2">
              <a
                href={LINKEDIN_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center w-10 h-10 rounded-md
                           bg-white/[0.06] hover:bg-accent/20 text-neutral-100 hover:text-accent
                           transition-colors"
                title="LinkedIn"
                aria-label="LinkedIn"
              >
                <SolidLinkedIn />
              </a>
              <a
                href={WEBLENS_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center w-10 h-10 rounded-md
                           bg-white/[0.06] hover:bg-accent/20 text-neutral-100 hover:text-accent
                           transition-colors"
                title="GitHub"
                aria-label="GitHub"
              >
                <SolidGithub />
              </a>
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );

  return createPortal(node, document.body);
}

function SolidGithub() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.27-.01-1-.02-1.96-3.2.69-3.87-1.54-3.87-1.54-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.68 1.24 3.34.95.1-.74.4-1.25.73-1.54-2.55-.29-5.23-1.28-5.23-5.7 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.16 1.18a10.94 10.94 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.62 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.43-2.69 5.41-5.25 5.69.41.36.78 1.06.78 2.14 0 1.55-.01 2.79-.01 3.17 0 .31.21.68.8.56C20.21 21.39 23.5 17.07 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}

function SolidLinkedIn() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.13 1.45-2.13 2.94v5.67H9.37V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.38-1.85 3.61 0 4.28 2.38 4.28 5.47v6.27zM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

export { WEBLENS_URL, LINKEDIN_URL };
