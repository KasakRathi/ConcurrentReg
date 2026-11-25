import { AlertTriangle, Check, CircleDashed, Loader2, X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { DemoInfo, Invariant, LiveTest, SectionRow, VerifySnapshot } from "@/lib/demoApi";
import { groupByFile } from "@/lib/demoApi";
import { fmtMs } from "@/lib/format";
import { CATEGORY_STYLE } from "@/lib/theme";
import type { ExperimentResult } from "@/lib/types";

/** One numbered step of the guided demo. */
export function Step({ n, title, status, children, aside }: { n: number; title: string; status?: "idle" | "active" | "done"; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="relative pl-12 sm:pl-14" aria-labelledby={`step-${n}`}>
      <span aria-hidden className="absolute left-[17px] top-10 bottom-[-28px] w-px bg-ink-700 sm:left-[21px]" />
      <span className={cn("absolute left-0 top-0 grid size-9 place-items-center rounded-full border font-mono text-[13px] sm:size-11", status === "done" ? "border-mint/50 bg-mint/10 text-mint" : status === "active" ? "border-sky/50 bg-sky/10 text-sky" : "border-ink-600 text-ink-300")}>
        {status === "done" ? <Check className="size-4" /> : n}
      </span>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 pt-1.5">
        <h2 id={`step-${n}`} className="text-[18px] font-medium text-ink-50">{title}</h2>
        {aside}
      </div>
      <div className="mb-14">{children}</div>
    </section>
  );
}

/** Which database the server is REALLY using, with what that means for the evidence. */
export function DbBadge({ db }: { db: DemoInfo["database"] }) {
  const real = db.row_locks;
  return (
    <div className={cn("rounded-xl border px-4 py-3", real ? "border-mint/30 bg-mint/[0.05]" : "border-amber/40 bg-amber/[0.06]")}>
      <p className={cn("flex items-center gap-2 text-[15px] font-medium", real ? "text-mint" : "text-amber")}>
        {real ? <Check className="size-4" /> : <AlertTriangle className="size-4" />}
        {db.dialect === "mysql" ? "MySQL" : db.dialect} {db.version} {db.name ? <span className="font-mono text-[12px] text-ink-300">· {db.name}</span> : null}
      </p>
      <p className="mt-1 text-[13px] leading-5 text-ink-200">
        {real
          ? "Real InnoDB row-level locking: the seat check and the seat decrease are protected by SELECT ... FOR UPDATE, so the correctness results below are meaningful."
          : "This database has no row-level locks (SQLite ignores FOR UPDATE). Concurrent requests can overwrite each other here, so correctness results from this database are not evidence about the MySQL design. Use MySQL for a real demonstration."}
      </p>
    </div>
  );
}

export function SeatRow({ s }: { s: SectionRow }) {
  return (
    <div className="panel p-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[15px] font-medium text-ink-50">{s.course_code} <span className="ml-1 text-[12.5px] font-normal text-ink-300">{s.course_name.replace(" (test data)", "")}</span></p>
        <p className="tabular font-mono text-[13px] text-ink-200"><span className="text-mint">{s.registered}</span> / {s.capacity} registered · {s.available_seats} left</p>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5" role="img" aria-label={`${s.registered} of ${s.capacity} seats taken`}>
        {Array.from({ length: s.capacity }).map((_, i) => (
          <span key={i} className={cn("size-6 rounded-md border transition-all duration-300", i < s.registered ? "border-mint bg-mint shadow-[0_0_12px_-2px_#6ee7b7]" : "border-ink-500 bg-transparent")} />
        ))}
      </div>
    </div>
  );
}

export function InvariantList({ items, stale }: { items: Invariant[]; stale?: boolean }) {
  return (
    <ul className={cn("space-y-2", stale && "opacity-60")} aria-label="Correctness checks, computed by SQL on the live database">
      {items.map((i) => (
        <li key={i.id} className="flex items-start gap-3 rounded-xl border border-ink-700 px-3.5 py-2.5">
          <span className={cn("mt-0.5 grid size-5 shrink-0 place-items-center rounded-full", i.ok ? "bg-mint/15 text-mint" : "bg-rose/15 text-rose")}>{i.ok ? <Check className="size-3.5" /> : <X className="size-3.5" />}</span>
          <span className="min-w-0 text-[13.5px]"><span className="text-ink-50">{i.label}</span><span className="block text-[12.5px] text-ink-300">{i.detail}</span></span>
        </li>
      ))}
    </ul>
  );
}

/** Every request as a dot, in the order the server answered it. Shows who got the seats. */
export function OutcomeTimeline({ exp }: { exp: ExperimentResult }) {
  const rows = [...exp.results].filter((r) => r.category !== "NOT_DISPATCHED").sort((a, b) => (a.end_offset_s ?? 0) - (b.end_offset_s ?? 0));
  const shown = rows.slice(0, 600);
  return (
    <div>
      <div className="flex flex-wrap gap-1.5" role="img" aria-label={`${rows.length} requests in the order they were answered`}>
        {shown.map((r, i) => (
          <span key={r.request_id} title={`#${i + 1} answered · ${r.student_id} → section ${r.section_id} · ${CATEGORY_STYLE[r.category].label}${r.latency_ms != null ? ` · ${fmtMs(r.latency_ms)}` : ""}`} className={cn("size-3.5 rounded-full ring-1 ring-black/40", r.category === "SUCCESS" && "size-[18px] shadow-[0_0_10px_-1px_#6ee7b7]")} style={{ background: CATEGORY_STYLE[r.category].color }} />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-300">
        {(["SUCCESS", "COURSE_FULL", "DUPLICATE", "QUEUE_FULL"] as const).map((c) => (
          <li key={c} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: CATEGORY_STYLE[c].color }} />{CATEGORY_STYLE[c].label}</li>
        ))}
      </ul>
      {rows.length > shown.length && <p className="mt-2 text-xs text-ink-400">Showing the first {shown.length} of {rows.length} answers.</p>}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  PASSED: "text-mint border-mint/30 bg-mint/10", FAILED: "text-rose border-rose/40 bg-rose/10", ERROR: "text-rose border-rose/40 bg-rose/10",
  SKIPPED: "text-amber border-amber/30 bg-amber/10", XFAIL: "text-amber border-amber/30 bg-amber/10", XPASS: "text-mint border-mint/30 bg-mint/10",
};

function TestLine({ t }: { t: LiveTest }) {
  return (
    <li className="flex items-baseline gap-3 py-1 font-mono text-[12px]">
      <span className={cn("w-[68px] shrink-0 rounded border px-1.5 py-px text-center text-[10px] uppercase tracking-wider", STATUS_STYLE[t.status])}>{t.status}</span>
      <span className="min-w-0 truncate text-ink-200"><span className="text-ink-400">{t.file.replace("tests/", "")}::</span>{t.name}</span>
      {t.reason && <span className="ml-auto hidden max-w-[40%] truncate text-ink-400 lg:block" title={t.reason}>{t.reason}</span>}
    </li>
  );
}

export function TestStream({ snap }: { snap: VerifySnapshot }) {
  const counts = snap.report ? { passed: snap.report.counts.passed, failed: snap.report.counts.failed, skipped: snap.report.counts.skipped, error: snap.report.counts.error } : snap.live_counts ?? { passed: 0, failed: 0, skipped: 0, error: 0 };
  const total = snap.report?.counts.total;
  const running = snap.status === "running";
  const byFile = snap.report ? groupByFile(snap.report.tests) : [];
  const skipped = snap.report?.tests.filter((t) => t.status === "SKIPPED") ?? [];
  const failed = snap.report?.tests.filter((t) => t.status === "FAILED" || t.status === "ERROR") ?? [];
  return (
    <div className="space-y-4">
      <div className="panel p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px]">
          <span className="flex items-center gap-2 text-ink-50">{running ? <Loader2 className="size-4 animate-spin text-sky" /> : snap.status === "done" && !failed.length ? <Check className="size-4 text-mint" /> : <AlertTriangle className="size-4 text-rose" />}{running ? "Running the project's test suite…" : snap.status === "done" ? (failed.length ? "Finished with failures" : "Finished") : "Failed to run"}</span>
          <span className="tabular font-mono"><span className="text-mint">{counts.passed} passed</span> · <span className={counts.failed + counts.error ? "text-rose" : "text-ink-300"}>{counts.failed + counts.error} failed</span> · <span className="text-amber">{counts.skipped} skipped</span>{total ? <span className="text-ink-300"> · {total} total</span> : null}</span>
          <span className="ml-auto flex items-center gap-3 font-mono text-[12px] text-ink-300"><span className="rounded border border-ink-600 px-1.5 py-0.5 uppercase">{snap.dialect}</span>{snap.elapsed_s?.toFixed(1)} s</span>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink-700"><div className={cn("h-full rounded-full transition-all duration-300", failed.length ? "bg-rose" : "bg-mint")} style={{ width: `${snap.percent ?? 0}%` }} /></div>
      </div>

      {running && snap.recent && snap.recent.length > 0 && (
        <ul className="panel max-h-[340px] divide-y divide-ink-800 overflow-hidden px-4 py-2" aria-live="polite" aria-label="Most recent tests">{snap.recent.slice(-14).map((t, i) => <TestLine key={`${t.file}${t.name}${i}`} t={t} />)}</ul>
      )}

      {snap.status === "done" && snap.report && (
        <>
          <div className="panel scroll-x">
            <table className="w-full min-w-[520px] text-left text-[13px]">
              <thead><tr className="border-b border-ink-700 text-ink-300"><th className="px-4 py-2.5 font-medium">Test file</th><th className="px-3 py-2.5 text-right font-medium">Passed</th><th className="px-3 py-2.5 text-right font-medium">Failed</th><th className="px-3 py-2.5 text-right font-medium">Skipped</th><th className="px-4 py-2.5 text-right font-medium">Total</th></tr></thead>
              <tbody>{byFile.map((f) => <tr key={f.file} className="border-b border-ink-800 last:border-0"><td className="px-4 py-2 font-mono text-[12px] text-ink-100">{f.file}</td><td className="tabular px-3 py-2 text-right font-mono text-mint">{f.passed}</td><td className={cn("tabular px-3 py-2 text-right font-mono", f.failed + f.error ? "text-rose" : "text-ink-400")}>{f.failed + f.error}</td><td className={cn("tabular px-3 py-2 text-right font-mono", f.skipped ? "text-amber" : "text-ink-400")}>{f.skipped}</td><td className="tabular px-4 py-2 text-right font-mono text-ink-100">{f.total}</td></tr>)}</tbody>
            </table>
          </div>
          {failed.length > 0 && <ul className="panel divide-y divide-ink-800 px-4 py-2">{failed.map((t, i) => <TestLine key={i} t={{ ...t, percent: null }} />)}</ul>}
          {skipped.length > 0 ? (
            <details className="panel px-4 py-3 text-[13px]"><summary className="cursor-pointer text-amber">{skipped.length} skipped, with the reason for each</summary><ul className="mt-2 divide-y divide-ink-800">{skipped.map((t, i) => <TestLine key={i} t={{ ...t, percent: null }} />)}</ul></details>
          ) : (
            <p className="flex items-center gap-2 text-[13px] text-ink-300"><CircleDashed className="size-4" /> Nothing was skipped: every test, including the row-locking ones, ran on {snap.dialect}.</p>
          )}
        </>
      )}
      {snap.error && snap.status !== "running" && <p className="text-[13px] text-rose">{snap.error}</p>}
    </div>
  );
}
