import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { Reveal } from "@/components/ui/Reveal";
import { useBackendStatus } from "@/hooks/backend-status";

const COLUMNS: { title: string; links: [string, string][] }[] = [
  { title: "Product", links: [["Run an experiment", "/#run"], ["Configure workloads", "/#workloads"], ["Read the results", "/#results"], ["Guarantees", "/#guarantees"]] },
  { title: "Dashboard", links: [["Overview", "/dashboard"], ["Monitoring", "/dashboard/monitoring"], ["Experiments", "/dashboard/experiments"], ["Workloads", "/dashboard/workloads"], ["Architecture", "/dashboard/architecture"]] },
  { title: "Research", links: [["Reproducibility", "/#reproduce"], ["Architecture and measurement", "/#control"], ["Claims and limits", "/#facts"]] },
];

export function FooterSection() {
  const { online } = useBackendStatus();
  return (
    <footer className="relative isolate overflow-hidden">
      <div className="lp-wrap pb-24 pt-24 text-center sm:pt-40">
        <Reveal>
          <h2 className="lp-h1 grad-text mx-auto max-w-[1000px]">Concurrency, reimagined.<br />Available in your terminal.</h2>
          <Link to="/dashboard/demo" className="lp-btn mt-10">Launch experiment <ChevronRight className="size-4" /></Link>
        </Reveal>
      </div>

      <div aria-hidden className="pointer-events-none relative mx-auto h-[150px] max-w-[1232px] select-none overflow-hidden px-6 min-[1360px]:px-0 sm:h-[170px] lg:h-[190px]">
        <p className="font-serif-display text-[clamp(3.5rem,13.4vw,12.5rem)] leading-[0.9] tracking-[-0.03em] text-white/[0.05]" style={{ fontFamily: "var(--font-serif-display)" }}>ConcurrentReg</p>
      </div>

      <div className="relative border-t border-[var(--lp-line-soft)]">
        <div className="lp-wrap grid gap-12 py-16 md:grid-cols-[1.2fr_repeat(3,1fr)]">
          <div className="text-[13px] leading-5 text-[#a1a4a5]">
            <p className="text-white">Vornics</p>
            <p>An OS and DBMS framework for high-volume</p>
            <p>university course registration.</p>
            <p className="mt-1">A research prototype, not a production system.</p>
            <p className="mt-8 inline-flex items-center gap-2 rounded-full border border-[var(--lp-line-soft)] bg-white/[0.03] px-3 py-2 text-[12.5px] text-white" role="status">
              <span className={`size-2 rounded-full ${online ? "bg-mint animate-pulse-dot" : online === false ? "bg-[#6c6f70]" : "bg-[#464a4d]"}`} />
              {online ? "Backend online: live counters available" : online === false ? "Backend not running" : "Checking backend"}
            </p>
          </div>
          {COLUMNS.map((c) => (
            <nav key={c.title} aria-label={c.title}>
              <p className="text-[15px] text-white">{c.title}</p>
              <ul className="mt-6 space-y-4">
                {c.links.map(([l, to]) => (
                  <li key={l}>{to.startsWith("/#") ? <a href={to.slice(1)} className="text-[15px] text-[#a1a4a5] transition hover:text-white">{l}</a> : <Link to={to} className="text-[15px] text-[#a1a4a5] transition hover:text-white">{l}</Link>}</li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="border-t border-[var(--lp-line-soft)]"><p className="lp-wrap py-6 text-[12.5px] text-[#6c6f70]">© {new Date().getFullYear()} Vornics · Synthetic workloads, no real student data · Visual design inspired by modern developer-product sites; all code, text and media are original.</p></div>
      </div>
    </footer>
  );
}
