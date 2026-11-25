import { Ban, Boxes, CheckCheck, Dices, Gauge, Inbox, Lock, ScanLine, ShieldCheck } from "lucide-react";
import { Reveal } from "@/components/ui/Reveal";

const ITEMS = [
  { Icon: Lock, t: "Row-level locking", d: "SELECT ... FOR UPDATE locks the section row before seats are counted, so two requests never see the last seat." },
  { Icon: CheckCheck, t: "One transaction, one commit", d: "The registration insert and the seat decrease commit together, or roll back together." },
  { Icon: Ban, t: "No duplicate registrations", d: "UNIQUE(student_id, section_id) stops a repeat even if the application check is bypassed." },
  { Icon: ShieldCheck, t: "Seats stay in range", d: "A CHECK constraint refuses a seat count below zero or above capacity." },
  { Icon: Inbox, t: "A bounded queue", d: "When the queue is full the next request is refused immediately instead of waiting without limit." },
  { Icon: Boxes, t: "A fixed worker pool", d: "Server threads take requests first in, first out. The workload generator's client threads are separate." },
  { Icon: Gauge, t: "A database semaphore", d: "Limits how many workers are inside the database at once. A tuning knob; correctness never depends on it." },
  { Icon: Dices, t: "Seeded workloads", d: "The same seed and settings give the same schedule, think times and request targets." },
  { Icon: ScanLine, t: "Honest validity", d: "An open-loop run is flagged invalid if any request was sent late or never sent, and the reasons are listed." },
];

export function GuaranteesSection() {
  return (
    <section id="guarantees" className="relative mx-auto max-w-[1280px] scroll-mt-20 px-0 py-10 sm:px-4 sm:py-16">
      <div className="relative rounded-t-[32px] border-t border-[var(--lp-line-soft)] bg-gradient-to-b from-white/[0.02] to-transparent px-6 pb-24 pt-24 sm:px-6">
        <div aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-32 w-80 -translate-x-1/2 bg-[radial-gradient(ellipse_at_50%_0%,rgba(255,255,255,0.12),transparent_70%)]" />
        <div className="mx-auto max-w-[1232px]">
          <Reveal><h2 className="lp-h2 max-w-[720px]"><span className="text-white">Correct by construction,</span><br /><span className="text-[#a1a4a5]">not by hope</span></h2></Reveal>
          <ul className="mt-16 grid gap-x-12 gap-y-16 sm:grid-cols-2 lg:grid-cols-3">
            {ITEMS.map(({ Icon, t, d }, i) => (
              <li key={t}>
                <Reveal delay={(i % 3) * 0.06}>
                  <Icon className="size-6 text-[#f0f0f0]" strokeWidth={1.5} />
                  <h3 className="mt-5 text-[20px] font-normal text-[#f0f0f0]">{t}</h3>
                  <p className="mt-3 max-w-[340px] text-[14.5px] leading-[22px] text-[#a1a4a5]">{d}</p>
                </Reveal>
              </li>
            ))}
          </ul>
          <p className="mt-16 max-w-[640px] text-[13px] leading-5 text-[#6c6f70]">What the project's tests establish: in bounded concurrent runs (up to 52 simultaneous requests, on MySQL/InnoDB) registrations never exceeded capacity and no duplicate rows were stored. This is not a claim about every workload or about university-scale traffic.</p>
        </div>
      </div>
    </section>
  );
}
