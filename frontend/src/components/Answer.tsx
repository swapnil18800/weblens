import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../lib/types";

interface Props {
  markdown: string;
  citations: Citation[];
  /** Original-num → display-num map. When set, [N] markers in the rendered text
   *  use the display number; click handlers still receive the *original* num so
   *  they can look up the citation by its stable identity. */
  citationRemap?: Record<number, number>;
  onCiteClick: (num: number) => void;
  isStreaming?: boolean;
}

export default function Answer({ markdown, citations, citationRemap, onCiteClick, isStreaming = false }: Props) {
  // Replace [N] markers in the markdown with click-handler links.
  // The href encodes BOTH the display number (visible label) and original number
  // (stable identity for click handlers and panel lookup) as #cite-<orig>-<display>.
  const cited = expandInlineCitations(markdown, citations, citationRemap);

  return (
    <div className={`answer-md ${isStreaming ? "streaming-cursor" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...rest }) => {
            const m = /^#cite-(\d+)(?:-(\d+))?$/.exec(href || "");
            if (m) {
              const origNum = parseInt(m[1], 10);
              const displayNum = m[2] ? parseInt(m[2], 10) : origNum;
              return (
                <a
                  className="cite"
                  onClick={(e) => {
                    e.preventDefault();
                    onCiteClick(origNum);
                  }}
                  href={href}
                  {...rest}
                >
                  {displayNum}
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

function expandInlineCitations(
  md: string,
  citations: Citation[],
  remap?: Record<number, number>,
): string {
  if (!md) return md;
  const validNums = new Set(citations.map((c) => c.num));
  return md.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (whole, group: string) => {
    const nums = group.split(/\s*,\s*/).map((x) => parseInt(x, 10)).filter((n) => Number.isFinite(n));
    if (nums.length === 0) return whole;
    return nums
      .map((n) => {
        if (validNums.size > 0 && !validNums.has(n)) return `[${n}]`;
        const display = remap?.[n] ?? n;
        return `[${display}](#cite-${n}-${display})`;
      })
      .join("");
  });
}
