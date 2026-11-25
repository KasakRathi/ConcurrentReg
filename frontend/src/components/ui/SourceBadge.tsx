import { cn } from "@/lib/cn";
import { Tooltip } from "./Tooltip";

/**
 * Every panel that shows numbers says where they come from.
 *   live        : polled from the running API by this browser
 *   file        : read from a workload-generator result file you imported
 *   simulation  : generated in the browser to explain a mechanism; NOT a measurement
 *   schematic   : an illustration or a preview computed from configuration; NOT a measurement
 *   unavailable : the backend does not expose this yet
 */
export type Source = "live" | "file" | "simulation" | "schematic" | "unavailable";

const META: Record<Source, { label: string; dot: string; text: string; ring: string; help: string }> = {
  live: { label: "Live API", dot: "bg-mint animate-pulse-dot", text: "text-mint", ring: "border-mint/25 bg-mint/[0.06]", help: "Polled from GET /os-layer/status by this browser." },
  file: { label: "Result file", dot: "bg-sky", text: "text-sky", ring: "border-sky/25 bg-sky/[0.06]", help: "Computed from a workload-generator result file you imported. Real measurements of that past run." },
  simulation: { label: "Simulation", dot: "bg-violet", text: "text-violet", ring: "border-violet/25 bg-violet/[0.06]", help: "Generated in your browser to illustrate a mechanism. Not a measurement of the real system." },
  schematic: { label: "Schematic", dot: "bg-ink-300", text: "text-ink-200", ring: "border-ink-500/50 bg-white/[0.03]", help: "An illustration or a preview computed from settings. Not measured data." },
  unavailable: { label: "Not exposed", dot: "bg-ink-500", text: "text-ink-300", ring: "border-ink-600 bg-white/[0.02]", help: "The backend does not provide this metric today." },
};

export function SourceBadge({ source, label, className }: { source: Source; label?: string; className?: string }) {
  const m = META[source];
  return (
    <Tooltip content={m.help}>
      <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em]", m.ring, m.text, className)}>
        <span className={cn("size-1.5 rounded-full", m.dot)} />
        {label ?? m.label}
      </span>
    </Tooltip>
  );
}
