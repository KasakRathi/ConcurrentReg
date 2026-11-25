import { Pause, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { PipelineCanvas } from "@/components/visuals/PipelineCanvas";
import { PipelineSim, type SimParams } from "@/lib/pipelineSim";
import { arrivalOffsets, scheduleRateBins } from "@/lib/schedule";
import { COLORS } from "@/lib/theme";
import { cn } from "@/lib/cn";

const base = { ramp_stages: 3, request_count: 0, rate: 1, phases: [] as [number, number][] };
const PROFILES = [
  { id: "steady", name: "Steady", blurb: "Arrivals at a fixed rate, spread over three sections. The queue stays short and seats go quietly.", flags: "--pattern steady --contention independent", offsets: arrivalOffsets({ ...base, pattern: "steady", request_count: 18, rate: 3 }), hot: 0.34 },
  { id: "burst", name: "Burst", blurb: "Every request arrives at the same instant, spread over three sections. The queue fills and overflow is refused.", flags: "--pattern burst --contention independent", offsets: arrivalOffsets({ ...base, pattern: "burst", request_count: 26 }), hot: 0.34 },
  { id: "hotspot", name: "Hotspot", blurb: "A burst where everyone wants the same section. One row lock serialises them; the others sit idle.", flags: "--pattern burst --contention hot", offsets: arrivalOffsets({ ...base, pattern: "burst", request_count: 26 }), hot: 1 },
  { id: "recovery", name: "Recovery", blurb: "Calm, a spike, then calm again. Watch the queue drain after the spike ends.", flags: '--phases "3:3,18:2,3:5" --contention hot', offsets: arrivalOffsets({ ...base, pattern: "phases", phases: [[3, 3], [18, 2], [3, 5]] }), hot: 1 },
];

function Slider({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (n: number) => void }) {
  return (
    <label className="block"><span className="flex items-baseline justify-between text-[12px] text-[#a1a4a5]"><span>{label}</span><span className="tabular font-mono text-white">{value}</span></span>
      <input type="range" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 h-1 w-full cursor-pointer appearance-none rounded-full bg-white/15 accent-[#6ee7b7]" /></label>
  );
}

export function PlaygroundPanel() {
  const [pid, setPid] = useState("hotspot");
  const [q, setQ] = useState(6);
  const [w, setW] = useState(4);
  const [p, setP] = useState(2);
  const [running, setRunning] = useState(true);
  const [run, setRun] = useState(0);
  const [counts, setCounts] = useState({ offered: 0, registered: 0, full: 0, refused: 0, peak: 0 });
  const paint = useRef(0);
  const profile = PROFILES.find((x) => x.id === pid)!;
  const sim = useMemo(() => {
    const params: SimParams = { queueCapacity: q, workers: w, permits: p, sections: 3, seatsPerSection: 4, lockSeconds: 0.3 };
    const s = new PipelineSim(params, 11);
    s.hotShare = profile.hot;
    s.loadSchedule(profile.offsets, 0);
    return s;
    // `run` is an explicit restart trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, w, p, profile, run]);
  useEffect(() => setCounts({ offered: 0, registered: 0, full: 0, refused: 0, peak: 0 }), [sim]);
  const onFrame = useCallback((dt: number) => {
    paint.current += dt;
    if (paint.current > 0.12) { paint.current = 0; setCounts({ ...sim.counters, peak: sim.maxQueueDepth }); }
  }, [sim]);
  const bins = useMemo(() => scheduleRateBins(profile.offsets, 0.5).map((b) => ({ ...b, label: `${b.t}s` })), [profile]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--lp-line-soft)] px-4 py-3">
        <div role="tablist" aria-label="Workload pattern" className="flex flex-wrap gap-1">
          {PROFILES.map((x) => <button key={x.id} role="tab" aria-selected={pid === x.id} onClick={() => { setPid(x.id); setRunning(true); }} className={cn("rounded-lg px-3.5 py-1.5 text-[14px] transition", pid === x.id ? "bg-white text-black" : "text-[#a1a4a5] hover:text-white")}>{x.name}</button>)}
        </div>
        <span className="rounded-full border border-violet/30 bg-violet/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-violet">Simulation</span>
      </div>
      <div className="grid lg:grid-cols-[1fr_270px]">
        <div className="min-w-0 lg:border-r lg:border-[var(--lp-line-soft)]">
          <PipelineCanvas sim={sim} running={running} onFrame={onFrame} className="w-full" ariaLabel={`Simulated ${profile.name} workload: requests enter a bounded queue, workers take them, pass a semaphore and compete for three section row locks.`} />
          <dl className="grid grid-cols-2 gap-px border-t border-[var(--lp-line-soft)] bg-white/[0.06] sm:grid-cols-5">
            {[["Offered", counts.offered, "text-white"], ["Registered", `${counts.registered} / 12`, "text-mint"], ["Course full", counts.full, "text-amber"], ["Refused", counts.refused, "text-rose"], ["Queue peak", `${counts.peak} / ${q}`, "text-violet"]].map(([l, v, t]) => (
              <div key={l as string} className="bg-black px-4 py-3"><dt className="eyebrow">{l}</dt><dd className={`tabular mt-1 font-mono text-lg ${t}`}>{v}</dd></div>
            ))}
          </dl>
          <p className="border-t border-[var(--lp-line-soft)] px-5 py-4 text-[12.5px] leading-5 text-[#a1a4a5]">Twelve seats in total (four per section). In this simulation, as in the real transaction, the lock and the seat check are one step, so the seats taken never exceed twelve.</p>
        </div>
        <div className="flex flex-col gap-5 p-5">
          <p className="text-[13px] leading-5 text-[#a1a4a5]">{profile.blurb}</p>
          <div className="space-y-4"><Slider label="Queue capacity" value={q} min={1} max={12} onChange={setQ} /><Slider label="Worker threads" value={w} min={1} max={6} onChange={setW} /><Slider label="DB semaphore permits" value={p} min={1} max={6} onChange={setP} /></div>
          <div className="flex gap-2">
            <button onClick={() => { setRun((n) => n + 1); setRunning(true); }} className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-[13px] font-medium text-black"><RotateCcw className="size-3.5" /> Rerun</button>
            <button onClick={() => setRunning((r) => !r)} aria-pressed={!running} className="inline-flex items-center gap-1.5 rounded-full border border-[var(--lp-line)] px-4 py-2 text-[13px] text-white">{running ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{running ? "Pause" : "Play"}</button>
          </div>
          <div>
            <p className="eyebrow">Intended arrival rate</p>
            {bins.length === 1 ? <p className="mt-2 rounded-md border border-[var(--lp-line-soft)] px-3 py-4 text-center font-mono text-[12px] text-[#d3d8dc]">{profile.offsets.length} requests, all due at t = 0 s</p> : (
              <div className="mt-2 h-20" aria-hidden><ResponsiveContainer width="100%" height="100%"><BarChart data={bins} margin={{ top: 2, right: 0, left: 0, bottom: 0 }} barCategoryGap={1}><XAxis dataKey="label" hide /><YAxis hide /><Bar dataKey="rate" fill={COLORS.sky} radius={[2, 2, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div>
            )}
            <p className="mt-2 text-[11px] leading-4 text-[#6c6f70]">Computed with the generator's arrival rules, scaled for display.</p>
          </div>
          <div className="mt-auto rounded-xl border border-[var(--lp-line-soft)] p-3"><p className="eyebrow">Generator equivalent</p><code className="mt-1.5 block break-words text-[11.5px] leading-5 text-[#d3d8dc]">{profile.flags}</code></div>
        </div>
      </div>
    </div>
  );
}
