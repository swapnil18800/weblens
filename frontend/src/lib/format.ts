// Tiny formatters used across components

export function ms(n?: number): string {
  if (n === undefined || n === null) return "—";
  if (n < 1000) return `${n}ms`;
  return `${(n / 1000).toFixed(2)}s`;
}

export function num(n?: number): string {
  if (n === undefined || n === null) return "—";
  return new Intl.NumberFormat().format(n);
}

export function chars(n?: number): string {
  if (n === undefined || n === null) return "—";
  if (n < 1000) return `${n} chars`;
  return `${(n / 1000).toFixed(1)}k chars`;
}

export function shortHost(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function humanizeQuery(q: string): string {
  // Trim trailing punctuation, capitalize first char
  const s = q.trim().replace(/[?.!,;:]+$/, "");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const now = Date.now();
  const diff = now - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function bucketTime(iso: string | null): string {
  if (!iso) return "Older";
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yest = today - 86_400_000;
  const week = today - 7 * 86_400_000;
  const t = d.getTime();
  if (t >= today) return "Today";
  if (t >= yest) return "Yesterday";
  if (t >= week) return "Last 7 days";
  return "Older";
}
