import { AlertTriangle, ChevronDown, Clock, FlaskConical, Play, Radar } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Reveal } from "@/components/ui/Reveal";
import { cn } from "@/lib/cn";
import { SectionHeadLeft } from "./SectionHead";

/** The registration API contract, exactly as in the README table. Nothing is sent when you press Send. */
const OUTCOMES = [
  { id: "ok", label: "Registered", status: 201, success: true, message: "Registration successful", tone: "text-mint bg-mint/10" },
  { id: "dup", label: "Already registered", status: 409, success: false, message: "Student is already registered for this course section", tone: "text-violet bg-violet/10" },
  { id: "full", label: "Course full", status: 409, success: false, message: "Course section is full", tone: "text-amber bg-amber/10" },
  { id: "q", label: "Queue full", status: 503, success: false, message: "Request queue is full", tone: "text-rose bg-rose/10" },
  { id: "nf", label: "Unknown student", status: 404, success: false, message: "Student does not exist", tone: "text-sky bg-sky/10" },
] as const;

interface Line { key: number; status: number; success: boolean; message: string }
let seq = 0;
const seed = (o: (typeof OUTCOMES)[number]): Line => ({ key: seq++, status: o.status, success: o.success, message: o.message });

function SimulationCard() {
  const reduce = useReducedMotion();
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]["id"]>("ok");
  const [lines, setLines] = useState<Line[]>(() => [OUTCOMES[2], OUTCOMES[0], OUTCOMES[1], OUTCOMES[0], OUTCOMES[3], OUTCOMES[0]].map(seed));
  const current = OUTCOMES.find((o) => o.id === outcome)!;
  const select = useRef<HTMLSelectElement>(null);
  return (
    <article className="lp-card flex h-full min-h-[690px] flex-col">
      <div className="relative flex-1 px-4 pt-14 sm:px-8">
        <span className="absolute right-5 top-5 rounded-full border border-violet/30 bg-violet/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-violet">Simulation · nothing is sent</span>
        <div className="mx-auto flex max-w-[410px] items-center gap-2 rounded-2xl border border-[var(--lp-line-soft)] bg-white/[0.03] p-1.5">
          <span className={cn("rounded-lg px-2.5 py-1 text-[12px] font-medium", current.tone)}>{current.status}</span>
          <label className="relative flex min-w-0 flex-1 items-center">
            <span className="sr-only">Outcome to simulate</span>
            <select ref={select} value={outcome} onChange={(e) => setOutcome(e.target.value as typeof outcome)} className="w-full appearance-none truncate bg-transparent py-1 pr-6 text-[14px] text-white focus:outline-none">
              {OUTCOMES.map((o) => <option key={o.id} value={o.id} className="bg-black">{o.label}</option>)}
            </select>
            <ChevronDown className="pointer-events-none absolute right-0 size-4 text-[#a1a4a5]" />
          </label>
          <button onClick={() => setLines((l) => [seed(current), ...l].slice(0, 9))} className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--lp-line)] bg-white/[0.05] px-3 py-1.5 text-[14px] font-medium text-white transition hover:bg-white hover:text-black">
            <Play className="size-3.5" /> Send
          </button>
        </div>
        <ul className="relative mt-10 space-y-2.5 font-mono text-[13px] [mask-image:linear-gradient(to_bottom,#000_35%,transparent)]" aria-live="polite" aria-label="Simulated responses">
          <AnimatePresence initial={false}>
            {lines.map((l) => (
              <motion.li key={l.key} layout={!reduce} initial={reduce ? false : { opacity: 0, y: -14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }} className="overflow-hidden text-ellipsis whitespace-nowrap text-[#6c6f70]">
                <span className="text-[#a1a4a5]">HTTP {l.status}:</span> {"{"} <span className="text-[#6c6f70]">"success"</span>: {String(l.success)}, <span className="text-[#6c6f70]">"message"</span>: <span className="text-[#c9c9a6]">"{l.message}"</span> {"}"}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </div>
      <div className="px-8 pb-8 pt-4">
        <FlaskConical className="size-5 text-[#f0f0f0]" />
        <h3 className="mt-4 text-[20px] font-normal text-[#f0f0f0]">Simulation mode</h3>
        <p className="mt-3 max-w-[330px] text-[14px] leading-[22px] text-[#a1a4a5]">Try every answer the registration API can give, using the real messages, without touching a database.</p>
        <Link to="/dashboard/architecture" className="mt-4 inline-block text-[14px] font-medium text-white underline-offset-4 hover:underline">Learn more</Link>
      </div>
    </article>
  );
}

const EVENTS = [
  { Icon: AlertTriangle, tag: "Queue full", tone: "border-rose/30 bg-rose/10 text-rose", t: "09:36:30", a: "request", b: "STU007 · section 1", c: "refused at once", d: "queue at capacity" },
  { Icon: Clock, tag: "Course full", tone: "border-amber/30 bg-amber/10 text-amber", t: "09:36:14", a: "request", b: "STU004 · section 1", c: "waited 12 ms", d: "for a permit" },
  { Icon: Radar, tag: "Registered", tone: "border-mint/30 bg-mint/10 text-mint", t: "09:36:09", a: "request", b: "STU002 · section 2", c: "committed", d: "one seat taken" },
  { Icon: Clock, tag: "Duplicate", tone: "border-violet/30 bg-violet/10 text-violet", t: "09:36:02", a: "request", b: "STU002 · section 2", c: "UNIQUE", d: "held the line" },
];

function EventsCard() {
  return (
    <article className="lp-card flex h-full min-h-[690px] flex-col">
      <div className="relative flex-1 overflow-hidden px-6 pt-10 sm:px-9">
        <span className="absolute right-5 top-5 rounded-full border border-ink-500/50 bg-white/[0.03] px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-[#a1a4a5]">Sample events</span>
        <ol className="relative space-y-7 [mask-image:linear-gradient(to_bottom,#000_60%,transparent)]">
          <span aria-hidden className="absolute bottom-0 left-[17px] top-4 w-px bg-white/10" />
          {EVENTS.map((e) => (
            <li key={e.tag} className="relative flex gap-5">
              <span className={cn("z-10 grid size-9 shrink-0 place-items-center rounded-xl border bg-black", e.tone)}><e.Icon className="size-[18px]" /></span>
              <div>
                <p className="flex flex-wrap items-center gap-3"><span className={cn("rounded-md border px-2.5 py-1 text-[13px]", e.tone)}>{e.tag}</span><span className="inline-flex items-center gap-1.5 text-[13px] text-[#a1a4a5]"><Clock className="size-3.5" /> Oct 19 {e.t}</span></p>
                <p className="mt-4 flex flex-wrap items-center gap-2 text-[14px] text-[#a1a4a5]">{e.a} <code className="rounded-md border border-[var(--lp-line-soft)] bg-white/[0.04] px-2 py-0.5 text-[13px] text-white">{e.b}</code> {e.c} <code className="rounded-md border border-[var(--lp-line-soft)] bg-white/[0.04] px-2 py-0.5 text-[13px] text-white">{e.d}</code></p>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <div className="px-8 pb-8 pt-4">
        <Radar className="size-5 text-[#f0f0f0]" />
        <h3 className="mt-4 text-[20px] font-normal text-[#f0f0f0]">Observable by design</h3>
        <p className="mt-3 max-w-[360px] text-[14px] leading-[22px] text-[#a1a4a5]">Every queue refusal, permit wait and outcome is counted. The server exposes its live counters; each request also logs one line.</p>
        <Link to="/dashboard/monitoring" className="mt-4 inline-block text-[14px] font-medium text-white underline-offset-4 hover:underline">Learn more</Link>
      </div>
    </article>
  );
}

export function ExperienceSection() {
  return (
    <section id="experience" className="lp-wrap scroll-mt-20 py-24 sm:py-32">
      <SectionHeadLeft title={<>First-class<br />experiment experience</>}>
        A small, readable codebase built to be explained: seeded workloads, counters for every stage, and honest labels.
        <br />
        The goal is a study that <em className="not-italic text-[#f0f0f0] [font-style:italic]">just works</em>, and says so plainly when it does not.
      </SectionHeadLeft>
      <div className="mt-12 grid gap-8 lg:grid-cols-2">
        <Reveal className="h-full"><SimulationCard /></Reveal>
        <Reveal delay={0.08} className="h-full"><EventsCard /></Reveal>
      </div>
    </section>
  );
}
