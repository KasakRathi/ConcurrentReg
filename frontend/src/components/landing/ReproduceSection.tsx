import { FileCode2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Reveal } from "@/components/ui/Reveal";
import { CODE_FILES } from "@/lib/landing-data";
import { cn } from "@/lib/cn";
import { CodeLines } from "./CodeWindow";
import { SectionHead } from "./SectionHead";

export function ReproduceSection() {
  const [id, setId] = useState(CODE_FILES[0].id);
  const file = CODE_FILES.find((f) => f.id === id)!;
  return (
    <section id="reproduce" className="lp-wrap scroll-mt-20 py-24 sm:py-36">
      <SectionHead tile="seed" tileLabel="A dark die with glowing cyan pips, slowly turning." title="Reproduce every run">
        Seeds fix the schedule and the targets. Small, readable files do the rest, and each has a plain-English note beside it.
      </SectionHead>
      <Reveal className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link to="/dashboard/workloads" className="lp-btn">Open the workload builder</Link>
        <a href="#facts" className="lp-btn lp-btn-ghost">Read the limits</a>
      </Reveal>

      <Reveal className="mt-16">
        <div className="lp-card !rounded-[28px]">
          <div className="flex items-center gap-2 border-b border-[var(--lp-line-soft)] px-5 py-3.5" aria-hidden>
            <span className="size-3 rounded-full bg-[#ff5f57]" /><span className="size-3 rounded-full bg-[#febc2e]" /><span className="size-3 rounded-full bg-[#28c840]" />
          </div>
          <div className="grid lg:grid-cols-[236px_minmax(0,1.35fr)_minmax(0,0.8fr)]">
            <div role="tablist" aria-label="Source files" className="flex gap-1 overflow-x-auto border-b border-[var(--lp-line-soft)] p-3 lg:flex-col lg:border-b-0 lg:border-r">
              {CODE_FILES.map((f) => (
                <button key={f.id} role="tab" aria-selected={id === f.id} onClick={() => setId(f.id)} className={cn("flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-3 text-left text-[14px] transition", id === f.id ? "bg-white/[0.06] text-sky" : "text-[#a1a4a5] hover:text-white")}>
                  <FileCode2 className="size-4 shrink-0" /> {f.name}
                </button>
              ))}
            </div>
            <div className="min-w-0 border-b border-[var(--lp-line-soft)] p-5 lg:min-h-[560px] lg:border-b-0 lg:border-r">
              <p className="mb-4 font-mono text-[11px] text-[#6c6f70]">{file.path}</p>
              <CodeLines code={file.code} lineHeight={20} className="text-[12px]" />
            </div>
            <div className="relative overflow-hidden p-8">
              <div aria-hidden className="absolute inset-x-0 top-0 h-48 bg-[radial-gradient(ellipse_at_50%_0%,rgba(110,220,255,0.18),transparent_70%)]" />
              <span className="relative mx-auto mt-2 grid size-20 place-items-center rounded-full bg-gradient-to-br from-sky to-[#0aa5d6] shadow-[0_0_60px_-10px_#7dd3fc]"><span className="size-6 rounded-full bg-white/90 ring-8 ring-white/30" /></span>
              <h3 className="relative mt-8 text-center text-[24px] font-normal text-white">{file.title}</h3>
              <p className="relative mt-4 text-[14.5px] leading-[24px] text-[#d3d8dc]">{file.note}</p>
              <ul className="relative mt-5 space-y-2.5 text-[14px] leading-[22px] text-[#a1a4a5]">{file.points.map((p) => <li key={p} className="flex gap-2.5"><span className="mt-2 size-1 shrink-0 rounded-full bg-sky" />{p}</li>)}</ul>
              <p className="relative mt-6 text-[12px] text-[#6c6f70]">Excerpt copied from the repository file shown; a test fails if it ever drifts.</p>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
