import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../lib/types";

interface Props {
  markdown: string;
  citations: Citation[];
  onCiteClick: (num: number) => void;
  isStreaming?: boolean;
}

export default function Answer({ markdown, citations, onCiteClick, isStreaming = false }: Props) {
  // Replace [N] markers in the markdown with click-handler links.
  // We use react-markdown's components.a override + a regex pre-pass that converts
  // bare [N] to [N](#cite-N) so the renderer treats them as links.
  const cited = expandInlineCitations(markdown, citations.length);

  return (
    <div className={`answer-md ${isStreaming ? "streaming-cursor" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...rest }) => {
            const m = /^#cite-(\d+)$/.exec(href || "");
            if (m) {
              const num = parseInt(m[1], 10);
              return (
                <a
                  className="cite"
                  onClick={(e) => {
                    e.preventDefault();
                    onCiteClick(num);
                  }}
                  href={href}
                  {...rest}
                >
                  {num}
                </a>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" {...rest}>
                {children}
              </a>
            );
          },
        }}
      >
        {cited}
      </ReactMarkdown>
    </div>
  );
}

function expandInlineCitations(md: string, max: number): string {
  if (!md) return md;
  // Match bare [N] or [N, M] etc. Convert each N to its own link.
  return md.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (whole, group: string) => {
    const nums = group.split(/\s*,\s*/).map((x) => parseInt(x, 10)).filter((n) => Number.isFinite(n));
    if (nums.length === 0) return whole;
    return nums
      .map((n) => (max > 0 && n > max ? `[${n}]` : `[${n}](#cite-${n})`))
      .join("");
  });
}
