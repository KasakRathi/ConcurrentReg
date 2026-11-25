import { ArrowRight, CircleCheck, CircleDashed } from "lucide-react";
import { useState } from "react";
import { useMonitor } from "@/hooks/monitor";
import { PageHeader } from "@/components/dashboard/parts";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { LAYER_LABEL, readPath, STAGES, type Layer } from "@/lib/architecture";
import { fmtInt, fmtNum } from "@/lib/format";

const LAYERS: Layer[] = ["client", "os", "dbms"];

export default function Architecture() {
  const [active, setActive] = useState("semaphore");
  const { status, error } = useMonitor();
  const stage = STAGES.find((s) => s.id === active)!;

  return (
    <>
      <PageHeader title="Architecture" description="The request lifecycle as it exists in the code. Select a stage to see its job, its parameters and, when the API is running, its live counters. Dashed stages are planned and do not exist yet." actions={<SourceBadge source={status ? "live" : "unavailable"} label={status ? "Live counters" : "API offline: no live counters"} />} />

      <div className="grid gap-4 lg:grid-cols-3">
        {LAYERS.map((layer) => (
          <section key={layer} className="panel p-4" aria-label={LAYER_LABEL[layer]}>
            <p className="eyebrow mb-3">{LAYER_LABEL[layer]}</p>
            <ol className="space-y-2">
              {STAGES.filter((s) => s.layer === layer).map((s, i, list) => (
                <li key={s.id}>
                  <button onClick={() => setActive(s.id)} aria-pressed={active === s.id} className={cn("w-full rounded-lg border p-3 text-left transition", active === s.id ? "border-mint/50 bg-mint/[0.06]" : "border-ink-700 hover:border-ink-500", s.status === "planned" && "border-dashed")}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-ink-50">{s.name}</span>
                      {s.status === "planned" ? <CircleDashed className="size-4 text-amber" aria-label="planned" /> : <CircleCheck className="size-4 text-mint" aria-label="implemented" />}
                    </span>
                    <span className="mt-1 block font-mono text-[11px] text-ink-400">{s.source}</span>
                  </button>
                  {i < list.length - 1 && <div className="flex justify-center py-1 text-ink-500"><ArrowRight className="size-3.5 rotate-90" aria-hidden /></div>}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>

      <section className="panel mt-4 overflow-hidden" aria-live="polite">
        <div className="grid gap-px bg-ink-700 lg:grid-cols-[1.2fr_1fr]">
          <div className="bg-ink-900 p-6">
            <div className="flex flex-wrap items-center gap-2"><span className="eyebrow">{LAYER_LABEL[stage.layer]}</span><span className={cn("rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider", stage.status === "planned" ? "border-amber/30 text-amber" : "border-mint/30 text-mint")}>{stage.status === "planned" ? "planned, not implemented" : "implemented"}</span></div>
            <h2 className="mt-3 text-xl font-light text-ink-50">{stage.name}</h2>
            <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-ink-200">{stage.responsibility}</p>
            {stage.guarantees && <ul className="mt-4 space-y-1.5 text-[13px] text-ink-200">{stage.guarantees.map((g) => <li key={g} className="flex gap-2"><CircleCheck className="mt-0.5 size-3.5 shrink-0 text-mint" />{g}</li>)}</ul>}
            {stage.limits && <p className="mt-4 border-l-2 border-amber/40 pl-3 text-[13px] leading-relaxed text-ink-300">{stage.limits.join(" ")}</p>}
            <p className="eyebrow mt-6">Parameters</p>
            {stage.parameters.length === 0 ? <p className="mt-2 text-[13px] text-ink-400">None.</p> : <dl className="mt-2 space-y-2.5">{stage.parameters.map((p) => <div key={p.name}><dt className="font-mono text-[13px] text-ink-50">{p.name} <span className="text-mint">{p.value}</span></dt>{p.note && <dd className="text-xs leading-relaxed text-ink-400">{p.note}</dd>}</div>)}</dl>}
          </div>
          <div className="bg-ink-900 p-6">
            <p className="eyebrow">Metrics</p>
            <ul className="mt-3 divide-y divide-ink-800">
              {stage.metrics.map((m) => {
                const value = m.path && status ? readPath(status, m.path) : null;
                return (
                  <li key={m.label} className="flex items-baseline justify-between gap-3 py-2.5 text-[13px]">
                    <span className="text-ink-100">{m.label}{m.path && <code className="ml-2 text-[11px] text-ink-500">{m.path}</code>}</span>
                    {m.path ? (
                      value !== null ? <span className="tabular font-mono text-ink-50">{m.path.endsWith("_s") ? `${fmtNum(value, 3)} s` : fmtInt(value)}</span>
                        : <span className="text-xs text-ink-500">{error ? "API offline" : m.path === "queue_wait.average_s" && status ? "no jobs yet" : status ? "n/a" : "waiting…"}</span>
                    ) : <span className="max-w-[16rem] text-right text-xs text-ink-500">{m.note ?? "Not exposed"}</span>}
                  </li>
                );
              })}
            </ul>
            {stage.id === "api" && status && <div className="mt-3 rounded-lg border border-ink-700 p-3 font-mono text-[12px] text-ink-200">queue_capacity {status.config.queue_capacity} · worker_count {status.config.worker_count} · db_semaphore_permits {status.config.db_semaphore_permits}</div>}
          </div>
        </div>
      </section>
    </>
  );
}
