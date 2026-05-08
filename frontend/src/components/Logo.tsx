import { motion } from "framer-motion";

interface Props {
  size?: "sm" | "md" | "lg";
  animate?: boolean;
  className?: string;
}

const SIZES = {
  sm: { glyph: 28, text: "text-lg",   gap: "gap-2" },
  md: { glyph: 36, text: "text-xl",   gap: "gap-2.5" },
  lg: { glyph: 56, text: "text-4xl",  gap: "gap-3" },
} as const;

export default function Logo({ size = "md", animate = false, className = "" }: Props) {
  const cfg = SIZES[size];

  const inner = (
    <div className={`inline-flex items-center ${cfg.gap} select-none ${className}`}>
      <Glyph size={cfg.glyph} />
      <span className={`${cfg.text} font-semibold tracking-tight text-neutral-100`}>
        Web<span className="text-accent">Lens</span>
      </span>
    </div>
  );

  if (!animate) return inner;
  return (
    <motion.div
      initial={{ scale: 0.85, opacity: 0, y: 6 }}
      animate={{ scale: 1, opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
    >
      {inner}
    </motion.div>
  );
}

function Glyph({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <defs>
        <linearGradient id="wl-grad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#7aa1ff" />
          <stop offset="1" stopColor="#5b8cff" />
        </linearGradient>
      </defs>
      <circle cx="13" cy="13" r="9.25" stroke="url(#wl-grad)" strokeWidth="2" fill="none" />
      <path d="M9 13 L12 16 L17 9" stroke="url(#wl-grad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <line x1="20" y1="20" x2="27" y2="27" stroke="url(#wl-grad)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
