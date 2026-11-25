import { CircleCheck, CircleDashed } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { LAYER_LABEL, STAGES } from "@/lib/architecture";
import { cn } from "@/lib/cn";

export function ArchitecturePanel() {
  const [active, setActive] = useState("queue");
  const stage = STAGES.find((s) => s.id === active)!;
  return (
    <div className="p-5 sm:p-8">
      <div className="scroll-x -mx-1 px-1 pb-1">
        <ol className="flex min-w-max gap-2" aria-label="Request lifecycle stages">
          {STAGES.map((s, i) => (
            <li key={s.id}>
              <button onClick={() => setActive(s.id)} aria-pressed={active === s.id} className={cn("rounded-xl border px-3.5 py-2.5 text-left transition", active === s.id ? "border-mint/50 bg-mint/[0.07]" : "border-[var(--lp-line-soft)] hover:border-[var(--lp-line)]", s.status === "planned" && "border-dashed")}>
                <span className="eyebrow block">{String(i + 1).padStart(2, "0")}</span>
                <span className="mt-0.5 block text-[14px] text-white">{s.short}</span>
                <span className={cn("block font-mono text-[10px] uppercase tracking-wider", s.status === "planned" ? "text-amber" : "text-[#6c6f70]")}>{s.status === "planned" ? "not built" : s.layer === "dbms" ? "DBMS" : s.layer === "os" ? "OS layer" : "client"}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>
      <div className="mt-6 grid gap-8 lg:grid-cols-[1.3fr_1fr]" aria-live="polite">
        <div>
          <div className="flex flex-wrap items-center gap-2"><span className="eyebrow">{LAYER_LABEL[stage.layer]}</span>
            <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider", stage.status === "planned" ? "border-amber/30 text-amber" : "border-mint/30 text-mint")}>{stage.status === "planned" ? <CircleDashed className="size-3" /> : <CircleCheck className="size-3" />}{stage.status === "planned" ? "planned, not implemented" : "implemented"}</span></div>
          <h3 className="mt-3 text-[24px] font-normal text-white">{stage.name}</h3>
          <p className="mt-3 max-w-xl text-[15px] leading-[24px] text-[#a1a4a5]">{stage.responsibility}</p>
          <p className="mt-3 font-mono text-[12px] text-[#6c6f70]">{stage.source}</p>
          {stage.limits && <p className="mt-4 border-l-2 border-amber/40 pl-3 text-[13px] leading-5 text-[#a1a4a5]">{stage.limits.join(" ")}</p>}
        </div>
        <div>
          <p className="eyebrow">Parameters</p>
          {stage.parameters.length === 0 ? <p className="mt-2 text-[13px] text-[#6c6f70]">None: nothing is implemented here.</p> : (
            <dl className="mt-2 space-y-2.5">{stage.parameters.map((p) => <div key={p.name}><dt className="font-mono text-[13px] text-white">{p.name} <span className="text-mint">{p.value}</span></dt>{p.note && <dd className="text-[12px] leading-[18px] text-[#6c6f70]">{p.note}</dd>}</div>)}</dl>
          )}
          <p className="eyebrow mt-5">Metrics the API exposes</p>
          <ul className="mt-2 space-y-1.5 text-[13px]">{stage.metrics.map((m) => <li key={m.label} className="flex items-baseline gap-2 text-[#d3d8dc]"><span className={cn("size-1.5 shrink-0 rounded-full", m.path ? "bg-mint" : "bg-[#464a4d]")} />{m.label}{m.path && <code className="ml-auto text-[11px] text-[#6c6f70]">{m.path}</code>}</li>)}</ul>
          <Link to="/dashboard/architecture" className="mt-5 inline-block text-[13px] text-white underline-offset-4 hover:underline">Open with live counters</Link>
        </div>
      </div>
    </div>
  );
}
