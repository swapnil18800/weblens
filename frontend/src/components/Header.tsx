import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { FlaskConical, Info, Menu } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useChat } from "../state/chatStore";
import ExamplesDropdown from "./ExamplesDropdown";
import InfoModal from "./InfoPopover";
import Logo from "./Logo";

export default function Header() {
  const startNewChat = useChat((s) => s.startNewChat);
  const devMode = useChat((s) => s.devMode);
  const sidebarOpen = useChat((s) => s.sidebarOpen);
  const setSidebarOpen = useChat((s) => s.setSidebarOpen);
  const loc = useLocation();
  const nav = useNavigate();
  const [infoOpen, setInfoOpen] = useState(false);

  return (
    <header className="h-12 px-3 sm:px-4 flex items-center justify-between border-b hairline bg-bg/95 backdrop-blur-sm sticky top-0 z-30">
      <div className="flex items-center gap-2 min-w-0">
        {!sidebarOpen && (
          <button
            className="icon-btn !w-8 !h-8 md:!hidden"
            onClick={() => setSidebarOpen(true)}
            title="Open sidebar"
          >
            <Menu className="w-4 h-4" />
          </button>
        )}
        <button
          className="cursor-pointer select-none truncate"
          onClick={() => {
            startNewChat();
            nav("/");
          }}
          title="New chat"
        >
          <Logo size="sm" />
        </button>
      </div>
      <nav className="flex items-center gap-1">
        {loc.pathname === "/" && <ExamplesDropdown />}
        {devMode && (
          <Link
            to={loc.pathname === "/eval" ? "/" : "/eval"}
            className={`btn ${loc.pathname === "/eval" ? "text-accent" : ""}`}
            title="Evaluation runs (dev only)"
          >
            <FlaskConical className="w-4 h-4" />
            <span className="hidden sm:inline">{loc.pathname === "/eval" ? "Chat" : "Eval"}</span>
          </Link>
        )}
        <button
          className="icon-btn !w-10 !h-10"
          onClick={() => setInfoOpen(true)}
          title="About"
          aria-haspopup="dialog"
        >
          <Info className="w-[20px] h-[20px]" />
        </button>
        <a
          className="icon-btn !w-9 !h-9"
          href="https://github.com/swapnil18800/weblens"
          target="_blank"
          rel="noreferrer"
          title="WebLens on GitHub"
        >
          <SolidGithub />
        </a>
        <AnimatePresence>
          {infoOpen && <InfoModal onClose={() => setInfoOpen(false)} />}
        </AnimatePresence>
      </nav>
    </header>
  );
}

// Filled, bold GitHub mark — lucide's outline glyph reads thin in a small icon-btn.
function SolidGithub() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.27-.01-1-.02-1.96-3.2.69-3.87-1.54-3.87-1.54-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.68 1.24 3.34.95.1-.74.4-1.25.73-1.54-2.55-.29-5.23-1.28-5.23-5.7 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.16 1.18a10.94 10.94 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.62 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.43-2.69 5.41-5.25 5.69.41.36.78 1.06.78 2.14 0 1.55-.01 2.79-.01 3.17 0 .31.21.68.8.56C20.21 21.39 23.5 17.07 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}
