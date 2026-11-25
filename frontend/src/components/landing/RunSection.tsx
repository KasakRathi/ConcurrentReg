import { Activity, Copy, Dice5, Flame, Gauge, Layers, Repeat, Shuffle, Split, Timer, TrendingUp, Zap, type LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Reveal } from "@/components/ui/Reveal";
import { buildCommand, buildServerCommand, DEFAULT_CONFIG } from "@/lib/command";
import { cn } from "@/lib/cn";
import { PRESET_PATCHES, SERVER_VARIANTS } from "@/lib/landing-data";
import { CodeLines, CopyButton } from "./CodeWindow";
import { SectionHead } from "./SectionHead";

const ICONS: Record<string, LucideIcon> = { steady: Activity, burst: Zap, ramp: TrendingUp, phases: Layers, closed: Repeat, hotspot: Flame, spread: Split, mixed: Shuffle, dupes: Copy, seed: Dice5, timeout: Timer, cap: Gauge };
const PRESETS = PRESET_PATCHES.map((p) => ({ ...p, Icon: ICONS[p.id] }));

export function RunSection() {
  const [preset, setPreset] = useState("phases");
  const [server, setServer] = useState("default");
  const p = PRESETS.find((x) => x.id === preset)!;
  const sv = SERVER_VARIANTS.find((x) => x.id === server)!;
  const code = useMemo(() => {
    const cfg = { ...DEFAULT_CONFIG, ...p.patch };
    return ["# 1. reset the data", ".venv/bin/python -m app.seed", "", "# 2. start the server", buildServerCommand(sv.q, sv.w, sv.p), "", "# 3. run the workload", buildCommand(cfg)].join("\n");
  }, [p, sv]);

  return (
    <section id="run" className="lp-wrap scroll-mt-20 py-24 sm:py-36">
      <SectionHead tile="cli" tileLabel="A dark terminal plate with command lines and an amber blinking cursor block." title={<>Run an experiment <span className="bg-gradient-to-r from-[#ffff92] to-[#ee8912] bg-clip-text text-transparent">this morning</span></>}>
        A seeded workload generator and three server settings. Pick a pattern, copy the command, and read the result file in the dashboard.
      </SectionHead>

      <Reveal className="mx-auto mt-12 max-w-[1024px]">
        <div role="tablist" aria-label="Workload pattern" className="flex flex-wrap justify-center gap-x-4 gap-y-6">
          {PRESETS.map(({ id, label, Icon }) => (
            <button key={id} role="tab" aria-selected={preset === id} onClick={() => setPreset(id)} className="group flex w-[60px] flex-col items-center gap-3 text-[14px]">
              <span className={cn("grid size-[60px] place-items-center rounded-2xl border transition", preset === id ? "border-[#ffff92]/60 bg-[#ffff92]/[0.06] text-[#ffff92] shadow-[0_0_30px_-8px_#ffff92]" : "border-[var(--lp-line-soft)] bg-white/[0.02] text-[#a1a4a5] group-hover:border-[var(--lp-line)] group-hover:text-white")}><Icon className="size-[22px]" /></span>
              <span className={cn("w-[84px] text-center leading-tight", preset === id ? "text-white" : "text-[#a1a4a5]")}>{label}</span>
            </button>
          ))}
        </div>

        <div className="lp-card mt-12 !rounded-[28px]">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--lp-line-soft)] px-4 py-3">
            <div role="tablist" aria-label="Server settings" className="flex flex-wrap gap-1">
              {SERVER_VARIANTS.map((v) => (
                <button key={v.id} role="tab" aria-selected={server === v.id} onClick={() => setServer(v.id)} className={cn("rounded-lg px-3 py-1.5 text-[14px] transition", server === v.id ? "bg-white/10 text-white ring-1 ring-white/10" : "text-[#a1a4a5] hover:text-white")}>
                  {v.label} <span className="ml-1 font-mono text-[11px] text-[#6c6f70]">{v.q}·{v.w}·{v.p}</span>
                </button>
              ))}
            </div>
            <CopyButton text={code} label="Copy the commands" />
          </div>
          <div className="px-5 pb-6 pt-5 sm:px-6"><CodeLines code={code} /></div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-[var(--lp-line-soft)] px-5 py-4 text-[13px] text-[#a1a4a5]">
            <Link to="/dashboard/workloads" className="transition hover:text-white">Open the workload builder</Link>
            <span className="text-[#6c6f70]">Queue · workers · permits are experimental parameters, not recommendations.</span>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
