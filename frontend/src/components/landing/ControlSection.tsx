import { Activity, Boxes, Gauge, LineChart, SlidersHorizontal, FlaskConical, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Reveal } from "@/components/ui/Reveal";
import { Wordmark } from "@/components/ui/Logo";
import { cn } from "@/lib/cn";
import { AnalyticsPanel } from "./AnalyticsPanel";
import { ArchitecturePanel } from "./ArchitecturePanel";
import { PlaygroundPanel } from "./PlaygroundPanel";
import { SectionHead } from "./SectionHead";

const TABS: { id: string; label: string; Icon: LucideIcon; title: string }[] = [
  { id: "architecture", label: "Live architecture", Icon: Boxes, title: "Architecture" },
  { id: "playground", label: "Workload simulation", Icon: Activity, title: "Workloads" },
  { id: "analytics", label: "Run analytics", Icon: LineChart, title: "Experiments" },
];
const SIDE = [["Overview", "/dashboard", Gauge], ["Monitoring", "/dashboard/monitoring", Activity], ["Experiments", "/dashboard/experiments", FlaskConical], ["Workloads", "/dashboard/workloads", SlidersHorizontal], ["Architecture", "/dashboard/architecture", Boxes]] as const;

export function ControlSection() {
  const [tab, setTab] = useState("architecture");
  const t = TABS.find((x) => x.id === tab)!;
  return (
    <section id="control" className="lp-wrap scroll-mt-20 py-24 sm:py-36">
      <SectionHead tile="ring" tileLabel="A metal ring with three beads orbiting it, one lit green." title="Everything in your control">
        Explore the pipeline, simulate a workload, and read a recorded run, in the same place you will use to run the real experiments.
      </SectionHead>

      <Reveal className="mt-14">
        <div role="tablist" aria-label="Dashboard views" className="grid gap-4 md:grid-cols-3">
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={cn("lp-card relative flex items-center gap-4 !rounded-[20px] px-6 py-6 text-left transition", tab === id ? "!border-[var(--lp-line)]" : "opacity-80 hover:opacity-100")}>
              <span className={cn("grid size-10 place-items-center rounded-xl border", tab === id ? "border-mint/40 bg-mint/10 text-mint" : "border-[var(--lp-line-soft)] text-[#a1a4a5]")}><Icon className="size-[18px]" /></span>
              <span className="text-[16px] text-white">{label}</span>
              {tab === id && <span aria-hidden className="absolute inset-x-12 bottom-0 h-px bg-gradient-to-r from-transparent via-mint to-transparent" />}
            </button>
          ))}
        </div>

        <div className="lp-card mt-6 !rounded-[24px]">
          <div className="grid lg:grid-cols-[216px_minmax(0,1fr)]">
            <aside className="hidden border-r border-[var(--lp-line-soft)] p-4 lg:block" aria-label="Dashboard pages">
              <div className="mb-5 flex items-center gap-2 px-1 py-1"><Wordmark className="text-[14px]" /></div>
              <ul className="space-y-1">
                {SIDE.map(([l, to, Icon]) => (
                  <li key={l}><Link to={to} className={cn("flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition", l === t.title ? "bg-white/[0.07] text-white" : "text-[#a1a4a5] hover:text-white")}><Icon className="size-4" />{l}</Link></li>
                ))}
              </ul>
            </aside>
            <div className="min-w-0">
              <div className="flex items-center justify-between border-b border-[var(--lp-line-soft)] px-6 py-4"><h3 className="text-[18px] font-normal text-white">{t.title}</h3><Link to="/dashboard" className="text-[13px] text-[#a1a4a5] transition hover:text-white">Open dashboard</Link></div>
              {tab === "architecture" && <ArchitecturePanel />}
              {tab === "playground" && <PlaygroundPanel />}
              {tab === "analytics" && <AnalyticsPanel />}
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
