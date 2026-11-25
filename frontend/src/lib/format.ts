export const fmtInt = (n: number | null | undefined) =>
  n == null || !Number.isFinite(n) ? "n/a" : Math.round(n).toLocaleString("en-US");

export function fmtNum(n: number | null | undefined, digits = 1) {
  if (n == null || !Number.isFinite(n)) return "n/a";
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMs(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n)) return "n/a";
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(2)} s`;
  if (Math.abs(n) >= 100) return `${n.toFixed(0)} ms`;
  return `${n.toFixed(1)} ms`;
}

export function fmtSeconds(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n)) return "n/a";
  return n < 1 ? `${(n * 1000).toFixed(0)} ms` : `${n.toFixed(2)} s`;
}

export const fmtRate = (n: number | null | undefined) =>
  n == null || !Number.isFinite(n) ? "n/a" : `${fmtNum(n, n >= 100 ? 0 : 1)} /s`;

export const fmtPct = (n: number | null | undefined, digits = 1) =>
  n == null || !Number.isFinite(n) ? "n/a" : `${(n * 100).toFixed(digits)}%`;

export function fmtDateTime(iso: string | undefined | null) {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "medium" });
}

export function fmtClock(ms: number) {
  return new Date(ms).toLocaleTimeString("en-GB", { hour12: false });
}
