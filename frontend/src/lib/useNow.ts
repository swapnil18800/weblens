import { useEffect, useState } from "react";

/**
 * Returns Date.now(), refreshing every `intervalMs` while `active` is true.
 * Used to drive live-updating timestamps in the reasoning trace.
 */
export function useNow(active: boolean, intervalMs: number = 100): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [active, intervalMs]);
  return now;
}
