import { CheckCircle2, FileJson, Trash2, TriangleAlert, Upload, XCircle } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useEffect } from "react";
import { Download } from "lucide-react";
import { useDemoInfo } from "@/hooks/demo";
import { getServerResult, listServerResults, type ServerResultItem } from "@/lib/demoApi";
import { parseExperiment } from "@/lib/results";
import { useResults, type ImportReport } from "@/hooks/results-store";
import { CompareTable } from "@/components/dashboard/CompareTable";
import { PageHeader, Section } from "@/components/dashboard/parts";
import { Button } from "@/components/ui/Button";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { EmptyState } from "@/components/ui/States";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { fmtDateTime, fmtInt, fmtMs } from "@/lib/format";

function ServerResults() {
  const { info } = useDemoInfo();
  const { items, addExperiment } = useResults();
  const [list, setList] = useState<ServerResultItem[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (!info?.controls_enabled) return;
    listServerResults().then((r) => setList(r.items), () => setList(null));
  }, [info?.controls_enabled]);
  if (!info?.controls_enabled) return null;
  const have = new Set(items.map((i) => i.exp.experiment_id));
  const load = async (id: string) => {
    setBusy(id);
    setMessage(null);
    try {
      const exp = parseExperiment(JSON.stringify(await getServerResult(id)));
      await addExperiment(exp, `${id}.json (from the server)`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not load that result");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Section title="Result files on the server" source="file" sourceLabel="Server folder" note={`Every run of the generator writes a file in ${info.results_dir}. Load them here instead of choosing files by hand.`}>
      {list === null ? <p className="text-[13px] text-ink-400">Reading the server's results folder…</p> : list.length === 0 ? <EmptyState title="No result files on the server yet">Run a scenario in the Live demo, or run the generator from a terminal.</EmptyState> : (
        <div className="panel scroll-x">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <tbody>{list.map((r) => (
              <tr key={r.experiment_id} className="border-b border-ink-800 last:border-0">
                <td className="px-4 py-2.5 font-mono text-[12px] text-ink-50">{r.experiment_id}</td>
                <td className="px-3 py-2.5 text-ink-300">{r.arrival_model} · {r.pattern} · {r.contention}</td>
                <td className="tabular px-3 py-2.5 font-mono text-ink-200">{r.successful_requests} / {r.total_requests}</td>
                <td className="px-3 py-2.5 text-[12px] text-ink-400">{r.has_server_context ? "has server settings" : ""}</td>
                <td className="px-4 py-2.5 text-right">{have.has(r.experiment_id) ? <span className="text-[12px] text-mint">loaded</span> : <Button size="sm" variant="secondary" disabled={busy === r.experiment_id} onClick={() => void load(r.experiment_id)}><Download className="size-3.5" /> Load</Button>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {message && <p className="mt-2 text-[13px] text-rose">{message}</p>}
    </Section>
  );
}

export default function Experiments() {
  const { items, ready, persisted, importFiles, remove, clear } = useResults();
  const [reports, setReports] = useState<ImportReport[]>([]);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [baseId, setBaseId] = useState<string>("");
  const [candId, setCandId] = useState<string>("");

  const handle = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (list.length) setReports(await importFiles(list));
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    void handle(e.dataTransfer.files);
  };

  const base = items.find((i) => i.exp.experiment_id === (baseId || items[1]?.exp.experiment_id))?.exp;
  const cand = items.find((i) => i.exp.experiment_id === (candId || items[0]?.exp.experiment_id))?.exp;

  return (
    <>
      <PageHeader title="Experiments" description="The server keeps no experiment history. Every run of the workload generator writes one JSON file to results/. Import those files here to inspect and compare them." />

      <ServerResults />

      <Section title="Import result files" source="file">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={cn("flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center transition", drag ? "border-mint bg-mint/[0.05]" : "border-ink-600 bg-white/[0.015]")}
        >
          <Upload className="size-6 text-ink-300" />
          <p className="text-sm font-medium text-ink-50">Drop result files here</p>
          <p className="max-w-md text-[13px] text-ink-300">Files stay in your browser (IndexedDB). They are not uploaded anywhere. Files are checked before they are accepted; anything that is not a generator result is rejected with the reason.</p>
          <input ref={input} type="file" accept=".json,application/json" multiple className="sr-only" onChange={(e) => { if (e.target.files) void handle(e.target.files); e.target.value = ""; }} aria-label="Choose result files" />
          <Button variant="secondary" size="sm" onClick={() => input.current?.click()}><FileJson className="size-3.5" /> Choose files</Button>
        </div>
        {reports.length > 0 && (
          <ul className="mt-3 space-y-1.5" aria-live="polite">
            {reports.map((r, i) => (
              <li key={i} className={cn("flex items-start gap-2 text-[13px]", r.ok ? "text-ink-100" : "text-rose")}>
                {r.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-mint" /> : <XCircle className="mt-0.5 size-4 shrink-0" />}
                <span><span className="font-mono">{r.fileName}</span>: {r.ok ? `imported, ${r.message}` : r.message}</span>
              </li>
            ))}
          </ul>
        )}
        {!persisted && <p className="mt-3 flex items-center gap-2 text-[13px] text-amber"><TriangleAlert className="size-4" /> This browser refused to save the files (private window or blocked storage). They will be gone when you reload.</p>}
        <CodeBlock className="mt-4" title="make a result file" code={`.venv/bin/python -m app.seed\n.venv/bin/python -m workload.workload_generator --pattern burst --contention hot --requests 20 --seed 42\n# writes results/<experiment-id>.json`} />
      </Section>

      <Section title={`Experiment history${items.length ? ` (${items.length})` : ""}`} source="file">
        {!ready ? null : items.length === 0 ? (
          <EmptyState title="No experiments imported">Nothing is listed until you import a result file. No sample data is shown in its place.</EmptyState>
        ) : (
          <>
            <div className="panel scroll-x">
              <table className="w-full min-w-[880px] text-left text-[13px]">
                <thead><tr className="border-b border-ink-700 text-ink-300">
                  {["Experiment", "Started", "Model · pattern", "Requests", "Registered", "p95", "Valid", ""].map((h) => <th key={h} className="px-4 py-3 font-medium">{h}</th>)}
                </tr></thead>
                <tbody>
                  {items.map(({ exp, importedAt }) => {
                    const ol = exp.summary.open_loop;
                    return (
                      <tr key={exp.experiment_id} className="border-b border-ink-800 last:border-0 hover:bg-white/[0.02]">
                        <td className="px-4 py-3"><Link to={`/dashboard/results/${encodeURIComponent(exp.experiment_id)}`} className="font-mono text-[12px] text-ink-50 hover:text-mint">{exp.experiment_id}</Link><p className="text-[11px] text-ink-400">seed {exp.config.seed} · imported {fmtDateTime(importedAt)}</p></td>
                        <td className="px-4 py-3 text-ink-200">{fmtDateTime(exp.run?.run_started_at)}</td>
                        <td className="px-4 py-3 text-ink-200">{exp.config.arrival_model} · {exp.config.arrival_model === "closed" ? `${exp.config.virtual_users} users` : exp.config.pattern}</td>
                        <td className="tabular px-4 py-3 font-mono text-ink-100">{fmtInt(exp.summary.total_requests)}</td>
                        <td className="tabular px-4 py-3 font-mono text-mint">{fmtInt(exp.summary.successful_requests)}</td>
                        <td className="tabular px-4 py-3 font-mono text-ink-100">{fmtMs(exp.summary.latency_ms?.p95)}</td>
                        <td className="px-4 py-3">{ol ? (ol.valid_open_loop ? <span className="text-mint">valid</span> : <span className="text-rose">invalid</span>) : <span className="text-ink-400">n/a (closed loop)</span>}</td>
                        <td className="px-4 py-3 text-right"><button onClick={() => remove(exp.experiment_id)} className="rounded p-1.5 text-ink-400 hover:bg-white/[0.06] hover:text-rose" aria-label={`Remove ${exp.experiment_id}`}><Trash2 className="size-4" /></button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-2 text-right"><button onClick={clear} className="text-xs text-ink-400 hover:text-rose">Remove all imported files from this browser</button></div>
          </>
        )}
      </Section>

      <Section title="Baseline versus candidate" source="file" note="Choose two imported runs. For a fair comparison keep the seed, pattern and request count the same and change one server setting between them. The server settings are not stored in result files, so note them yourself.">
        {items.length < 2 ? (
          <EmptyState title="Import at least two result files to compare them" />
        ) : (
          <div className="panel p-5">
            <div className="mb-4 grid gap-3 sm:grid-cols-2">
              {([["Baseline", base, setBaseId], ["Candidate", cand, setCandId]] as const).map(([label, current, set]) => (
                <label key={label} className="block text-xs text-ink-300">{label}
                  <select value={current?.experiment_id ?? ""} onChange={(e) => set(e.target.value)} className="mt-1 w-full rounded-md border border-ink-600 bg-ink-900 px-2.5 py-2 font-mono text-[12px] text-ink-50">
                    {items.map((i) => <option key={i.exp.experiment_id} value={i.exp.experiment_id}>{i.exp.experiment_id}</option>)}
                  </select>
                </label>
              ))}
            </div>
            {base && cand && (base.experiment_id === cand.experiment_id ? <p className="text-[13px] text-amber">Pick two different runs.</p> : <CompareTable baseline={base} candidate={cand} />)}
          </div>
        )}
        <div className="mt-3"><SourceBadge source="unavailable" label="Fixed vs adaptive: no comparison view here (IASL is optional; see docs/iasl/IASL_EXPERIMENTS.md)" /></div>
      </Section>
    </>
  );
}
