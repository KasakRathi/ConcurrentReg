import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { LoopVideo } from "./VideoTile";

// Real dependencies of this repository (requirements.txt and frontend/package.json), set as plain wordmarks.
const STACK_TOP = [
  { n: "FastAPI", c: "font-semibold tracking-tight" },
  { n: "Python", c: "font-medium" },
  { n: "SQLAlchemy", c: "font-semibold tracking-tight" },
  { n: "Pydantic", c: "font-medium" },
  { n: "uvicorn", c: "font-mono font-medium" },
  { n: "MySQL", c: "font-bold tracking-tight" },
];
const STACK_BOTTOM = [
  { n: "InnoDB", c: "font-bold tracking-wide" },
  { n: "React", c: "font-medium" },
  { n: "Vite", c: "font-bold" },
  { n: "Tailwind", c: "font-medium tracking-tight" },
  { n: "Recharts", c: "font-semibold" },
  { n: "pytest", c: "font-mono font-medium" },
];

export function Hero() {
  return (
    <section id="top" className="relative isolate overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[1000px] [mask-image:linear-gradient(to_bottom,#000_55%,transparent)]">
        <img src="/media/floor.jpg" alt="" className="absolute inset-0 size-full object-cover object-top opacity-90" />
        <img src="/media/rays.jpg" alt="" className="absolute inset-0 size-full object-cover opacity-70 mix-blend-screen" />
      </div>
      <div className="mx-auto grid min-h-[820px] max-w-[1104px] items-center gap-6 px-6 pb-16 pt-28 max-lg:text-center lg:min-h-[900px] lg:grid-cols-2 lg:pb-0 lg:pt-16 min-[1360px]:px-0">
        <div className="max-lg:order-2">
          <div className="animate-hero-text max-lg:flex max-lg:justify-center">
            <a href="#facts" className="rainbow-border text-sm" aria-label="What this prototype claims and what it does not">
              <span>Vornics · research prototype <ChevronRight className="size-3.5" /></span>
            </a>
          </div>
          <h1 className="lp-h1 grad-text mt-8 animate-hero-text [animation-delay:0.1s]">
            Concurrency,
            <br />
            Under Control.
          </h1>
          <p className="lp-p mt-6 max-w-[480px] animate-hero-text [animation-delay:0.2s] max-lg:mx-auto">
            Explore how high-volume course-registration requests move through admission, queues, worker pools and database transactions, with measurable performance and correctness.
          </p>
          <div className="mt-8 flex animate-hero-text flex-col gap-3 [animation-delay:0.3s] sm:flex-row max-lg:items-stretch max-lg:justify-center">
            <a href="#control" className="lp-btn">Explore the system</a>
            <Link to="/dashboard/demo" className="lp-btn lp-btn-ghost">Launch experiment</Link>
          </div>
        </div>
        <div className="relative mx-auto aspect-square w-[min(440px,72vw)] animate-visual-in max-lg:order-1 lg:w-full lg:max-w-[520px] lg:justify-self-end">
          <LoopVideo
            name="hero"
            label="A rotating lattice of dark glass cells. One cell after another lights up green, like seats being committed one at a time."
            className="size-full [mask-image:radial-gradient(closest-side,#000_62%,transparent)]"
          />
        </div>
      </div>

      <div className="lp-wrap pb-10 pt-6 text-center">
        <p className="lp-p mx-auto max-w-[360px] text-[18px] text-[#a1a4a5]/90">Built on proven open-source infrastructure, and nothing exotic.</p>
        <div className="mx-auto mt-14 grid max-w-[1024px] grid-cols-2 gap-x-6 gap-y-10 sm:grid-cols-3 lg:grid-cols-6">
          {[...STACK_TOP, ...STACK_BOTTOM].map((s) => (
            <span key={s.n} className={`text-[26px] leading-none text-white ${s.c}`}>{s.n}</span>
          ))}
        </div>
        <a href="#control" className="mt-14 inline-flex items-center gap-1.5 text-[16px] font-semibold text-[#a1a4a5] transition hover:text-white">
          Explore the architecture <ChevronRight className="size-4" />
        </a>
      </div>
    </section>
  );
}
