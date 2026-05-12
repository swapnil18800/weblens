import { useEffect, useRef, useState } from "react";
import { Send, Square } from "lucide-react";
import { useChat } from "../state/chatStore";

export default function ChatInput() {
  const submit = useChat((s) => s.submitQuery);
  const stop = useChat((s) => s.stop);
  const isStreaming = useChat((s) => s.isStreaming);
  const pendingInput = useChat((s) => s.pendingInput);
  const setPendingInput = useChat((s) => s.setPendingInput);
  const [val, setVal] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    autosize(taRef.current);
  }, [val]);

  // Pick up text pushed from chips / examples dropdown
  useEffect(() => {
    if (!pendingInput) return;
    setVal(pendingInput);
    setPendingInput("");
    requestAnimationFrame(() => {
      const el = taRef.current;
      if (el) {
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      }
    });
  }, [pendingInput, setPendingInput]);

  const onSubmit = () => {
    const q = val.trim();
    if (!q || isStreaming) return;
    setVal("");
    void submit(q);
  };

  return (
    <div className="px-4 pb-4 pt-2 sticky bottom-0 bg-bg/95 backdrop-blur-sm">
      <div className="max-w-3xl mx-auto surface rounded-xl flex items-end gap-2 px-3 py-2 shadow-sm focus-within:border-accent/40 transition-colors">
        <textarea
          ref={taRef}
          data-chat-input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          placeholder="Ask WebLens"
          className="flex-1 bg-transparent outline-none resize-none py-1.5 text-[15px] text-neutral-100 placeholder:text-neutral-500 max-h-48 scroll-thin"
        />
        {isStreaming ? (
          <button
            onClick={stop}
            className="inline-flex items-center justify-center w-9 h-9 rounded-md
                       bg-white/[0.06] hover:bg-white/10 text-neutral-200
                       transition-colors shrink-0"
            title="Stop generation"
            aria-label="Stop generation"
          >
            <Square className="w-3.5 h-3.5" fill="currentColor" />
          </button>
        ) : (
          <button
            onClick={onSubmit}
            disabled={!val.trim()}
            className={`inline-flex items-center justify-center w-9 h-9 rounded-md
                        transition-colors shrink-0 disabled:cursor-not-allowed
                        ${val.trim()
                          ? "bg-accent/15 hover:bg-accent/25 text-accent"
                          : "bg-white/[0.04] text-neutral-500"}`}
            title="Send (Enter)"
            aria-label="Send"
          >
            <Send
              className="w-4 h-4 -translate-x-[1px]"
              fill={val.trim() ? "currentColor" : "none"}
              strokeWidth={val.trim() ? 1.5 : 1.8}
            />
          </button>
        )}
      </div>
      <div className="text-2xs text-neutral-500 text-center mt-2 whitespace-nowrap overflow-hidden text-ellipsis">
        WebLens can make mistakes. Verify important info. <span className="text-neutral-600">· Built by Swapnil Padhi · MIT License · © 2026</span>
      </div>
    </div>
  );
}

function autosize(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 192) + "px";
}
