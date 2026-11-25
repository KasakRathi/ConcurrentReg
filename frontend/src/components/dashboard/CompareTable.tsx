import { compareRows, comparabilityWarnings, type CompareRow } from "@/lib/results";
import { fmtInt, fmtMs, fmtNum } from "@/lib/format";
import type { ExperimentResult } from "@/lib/types";
import { cn } from "@/lib/cn";

function fmt(row: CompareRow, v: number | null) {
  if (v == null) return "n/a";
  switch (row.unit) {
    case "ms": return fmtMs(v);
    case "/s": return `${fmtNum(v, v >= 100 ? 0 : 2)} /s`;
    case "s": return `${fmtNum(v, 2)} s`;
    case "ratio": return fmtNum(v, 3);
    default: return fmtInt(v);
  }
}

export function CompareTable({ baseline, candidate }: { baseline: ExperimentResult; candidate: ExperimentResult }) {
  const rows = compareRows(baseline, candidate);
  const warnings = comparabilityWarnings(baseline, candidate);
  return (
    <div>
      {warnings.length > 0 && (
        <ul className="mb-4 space-y-1 rounded-lg border border-amber/30 bg-amber/[0.05] px-4 py-3 text-[13px] text-ink-100">
          {warnings.map((w) => <li key={w}>⚠ {w}</li>)}
          <li className="text-ink-300">These differences do not stop the comparison, but they limit what it can show.</li>
        </ul>
      )}
      <div className="scroll-x">
        <table className="w-full min-w-[560px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-ink-700 text-ink-300">
              <th className="py-2 pr-4 font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium">Baseline</th>
              <th className="px-3 py-2 text-right font-medium">Candidate</th>
              <th className="py-2 pl-3 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const delta = r.baseline != null && r.candidate != null ? r.candidate - r.baseline : null;
              const pct = delta != null && r.baseline ? delta / Math.abs(r.baseline) : null;
              const better = delta == null || delta === 0 || r.higherIsBetter == null ? null : (delta > 0) === r.higherIsBetter;
              return (
                <tr key={r.label} className="border-b border-ink-800">
                  <td className="py-2.5 pr-4 text-ink-100">{r.label}</td>
                  <td className="tabular px-3 py-2.5 text-right font-mono text-ink-200">{fmt(r, r.baseline)}</td>
                  <td className="tabular px-3 py-2.5 text-right font-mono text-ink-50">{fmt(r, r.candidate)}</td>
                  <td className={cn("tabular py-2.5 pl-3 text-right font-mono", better === true && "text-mint", better === false && "text-rose", better === null && "text-ink-400")}>
                    {delta == null ? "n/a" : `${delta > 0 ? "+" : ""}${pct != null ? (pct * 100).toFixed(1) + "%" : fmt(r, delta)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-ink-400">Green and red only mark the direction that is better for that metric. Single runs vary with thread scheduling and server timing; one pair of runs is not evidence of a difference.</p>
    </div>
  );
}
