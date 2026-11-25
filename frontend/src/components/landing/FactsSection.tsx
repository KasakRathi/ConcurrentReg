import { Check, Minus } from "lucide-react";
import { SectionHead } from "./SectionHead";

/** Each statement is taken from the README or the code; `src` says where. "limit" cards say what is NOT claimed. */
const FACTS = [
  { kind: "claim", t: "Successful registrations for a section never exceed its capacity.", s: "tests/test_concurrency.py", n: "Established in bounded concurrent runs on MySQL/InnoDB, not for every workload." },
  { kind: "claim", t: "A student cannot hold two registrations for one section.", s: "app/models.py", n: "UNIQUE(student_id, section_id) is the last line of defence." },
  { kind: "claim", t: "Lateness is measured and never hidden.", s: "workload_generator.py", n: "Send-time and intended-arrival latency are both recorded." },
  { kind: "claim", t: "An invalid open-loop run says why.", s: "README · Day 2", n: "Late or undispatched requests are counted and listed in the result file." },
  { kind: "claim", t: "The same seed gives the same schedule and targets.", s: "README · Day 2", n: "Thread scheduling and server timing are not reproducible." },
  { kind: "limit", t: "SQLite ignores row locks.", s: "README · Run the tests", n: "Those tests are skipped there, never counted as passes." },
  { kind: "limit", t: "Workloads are synthetic.", s: "README · Day 2", n: "They do not represent real university traffic; defaults are demonstration values." },
  { kind: "limit", t: "Admission control is optional (IASL, off by default), rule-based and not shown to be better in general.", s: "README · IASL", n: "It moves one admission limit only; no learned policy, no classification, no resizing of the queue, workers or semaphore." },
  { kind: "limit", t: "The 503 for a full queue is provisional.", s: "README · Unresolved decisions", n: "The final response and fairness policy are still open." },
  { kind: "limit", t: "Lateness p95 and p99 need enough samples.", s: "workload_generator.py", n: "Below 20 and 100 samples they are not reported." },
];

function Card({ f }: { f: (typeof FACTS)[number] }) {
  const claim = f.kind === "claim";
  return (
    <li className="lp-card flex h-full w-[min(450px,82vw)] shrink-0 flex-col justify-between !rounded-[20px] bg-white/[0.02] p-8">
      <div>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] ${claim ? "border-mint/30 bg-mint/10 text-mint" : "border-amber/30 bg-amber/10 text-amber"}`}>{claim ? <Check className="size-3" /> : <Minus className="size-3" />}{claim ? "Established" : "Not claimed"}</span>
        <p className="mt-5 text-[17px] leading-[26px] text-[#f0f0f0]">{f.t}</p>
        <p className="mt-3 text-[14.5px] leading-[23px] text-[#a1a4a5]">{f.n}</p>
      </div>
      <p className="mt-8 font-mono text-[12px] text-[#6c6f70]">{f.s}</p>
    </li>
  );
}

export function FactsSection() {
  return (
    <section id="facts" className="scroll-mt-20 overflow-hidden py-24 sm:py-36">
      <div className="lp-wrap"><SectionHead title="Claims, with their limits">What the project establishes, what it deliberately does not, and the file each statement comes from.</SectionHead></div>
      <div className="marquee group mt-14 overflow-hidden" aria-label="Claims and limits">
        <div className="marquee-track items-stretch">
          {[0, 1].map((copy) => (
            <ul key={copy} aria-hidden={copy === 1} className="flex shrink-0 items-stretch gap-8 animate-marquee [animation-play-state:running] group-hover:[animation-play-state:paused]">
              {FACTS.map((f) => <Card key={f.t} f={f} />)}
            </ul>
          ))}
        </div>
      </div>
    </section>
  );
}
