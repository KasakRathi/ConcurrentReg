import { Link } from "react-router-dom";
import { useResults } from "@/hooks/results-store";
import { LatencyHistogramChart, RatesChart } from "@/components/charts/ResultCharts";
import { latencies } from "@/lib/results";

export function AnalyticsPanel() {
  const { items, ready } = useResults();
  const exp = items[0]?.exp;
  if (!exp) {
    return (
      <div className="grid place-items-center p-10 text-center">
        <div className="max-w-md">
          <svg viewBox="0 0 400 140" className="w-full" role="img" aria-label="Schematic of a rate chart with an offered-rate line and a completed-rate line. It contains no data.">
            <g stroke="#1b2024" strokeDasharray="2 4">{[25, 55, 85, 115].map((y) => <line key={y} x1="0" x2="400" y1={y} y2={y} />)}</g>
            <path d="M0 110 H110 V35 H190 V110 H400" fill="none" stroke="#7dd3fc" strokeDasharray="4 3" strokeWidth="1.5" />
            <path d="M0 112 H115 C 130 112 140 45 195 45 C 225 45 235 100 275 110 H400" fill="none" stroke="#6ee7b7" strokeWidth="2" />
          </svg>
          <p className="mt-4 text-[14px] font-medium text-white">No result file imported in this browser</p>
          <p className="mt-2 text-[13px] leading-5 text-[#a1a4a5]">{ready ? "This is a schematic of the charts, not data. " : ""}Run the generator and import its JSON file to see your own rates, latency distribution and validity here.</p>
          <Link to="/dashboard/experiments" className="mt-4 inline-block text-[13px] text-white underline-offset-4 hover:underline">Import a result file</Link>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-6 p-5 sm:p-8 lg:grid-cols-2">
      <div><p className="text-[14px] text-white">Requests per second</p><p className="mb-3 font-mono text-[11px] text-[#6c6f70]">{exp.experiment_id}</p><RatesChart exp={exp} /></div>
      <div><p className="text-[14px] text-white">Latency distribution (ms)</p><p className="mb-3 text-[11px] text-[#6c6f70]">Requests that received an HTTP response.</p><LatencyHistogramChart values={latencies(exp)} p50={exp.summary.latency_ms?.p50} p95={exp.summary.latency_ms?.p95} p99={exp.summary.latency_ms?.p99} /></div>
      <p className="text-[12px] text-[#6c6f70] lg:col-span-2">Computed from your latest imported result file: a real recorded run.</p>
    </div>
  );
}
