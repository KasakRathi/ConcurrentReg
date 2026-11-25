import { Command } from "cmdk";
import { ArrowRight, Check, CornerDownLeft, Copy, FileJson, Search, Terminal } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useResults } from "@/hooks/results-store";
import { buildCommand, buildServerCommand, DEFAULT_CONFIG } from "@/lib/command";
import { PRESET_PATCHES } from "@/lib/landing-data";
import { DASHBOARD_LINKS, SECTION_LINKS } from "./nav-data";

interface PaletteCtx {
  open: boolean;
  setOpen: (v: boolean) => void;
  toggle: () => void;
}
const Ctx = createContext<PaletteCtx | null>(null);

export function usePalette(): PaletteCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePalette must be used inside <PaletteProvider>");
  return v;
}

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
};

/** Owns the open state and the global shortcuts: Ctrl/Cmd+K anywhere, "/" when not typing. */
export function PaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((o) => !o), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "/" && !isTyping(e.target) && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const value = useMemo(() => ({ open, setOpen, toggle }), [open, toggle]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <CommandPalette />
    </Ctx.Provider>
  );
}

const itemCls =
  "group flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] text-[#d3d8dc] outline-none transition-colors data-[selected=true]:bg-white/[0.08] data-[selected=true]:text-white";
const headingCls = "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.14em] [&_[cmdk-group-heading]]:text-[#6c6f70]";

function CommandPalette() {
  const { open, setOpen } = usePalette();
  const navigate = useNavigate();
  const { items } = useResults();
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setCopied(null);
    }
  }, [open]);

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  const copy = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setOpen(false), 650);
    } catch {
      setCopied("Clipboard is blocked in this browser");
    }
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Search the site, the dashboard and commands"
      overlayClassName="fixed inset-0 z-[90] bg-black/70 backdrop-blur-sm data-[state=open]:animate-fade-in"
      contentClassName="lp fixed left-1/2 top-[14vh] z-[100] w-[min(640px,calc(100vw-24px))] -translate-x-1/2 overflow-hidden rounded-[22px] border border-[var(--lp-line)] bg-[#0a0a0a]/95 shadow-[0_40px_120px_-20px_rgba(0,0,0,0.95)] backdrop-blur-2xl data-[state=open]:animate-open-in"
    >
      <div className="flex items-center gap-3 border-b border-[var(--lp-line-soft)] px-4">
        <Search className="size-[18px] shrink-0 text-[#6c6f70]" aria-hidden />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search pages, sections, experiments, commands…"
          className="h-14 flex-1 bg-transparent text-[16px] text-white placeholder:text-[#6c6f70] focus:outline-none"
        />
        <kbd className="rounded-md border border-[var(--lp-line-soft)] px-1.5 py-0.5 font-mono text-[11px] text-[#6c6f70]">esc</kbd>
      </div>

      <Command.List className={`max-h-[min(420px,56vh)] overflow-y-auto p-2 ${headingCls}`}>
        <Command.Empty className="px-4 py-10 text-center text-[14px] text-[#a1a4a5]">Nothing matches “{query}”.</Command.Empty>

        <Command.Group heading="On this site">
          {SECTION_LINKS.map((l) => (
            <Command.Item key={l.id} value={`${l.label} ${l.desc} section`} onSelect={() => go(l.to)} className={itemCls}>
              <l.Icon className="size-4 shrink-0 text-[#a1a4a5] group-data-[selected=true]:text-mint" aria-hidden />
              <span className="flex-1">{l.label}{" "}<span className="ml-2 hidden text-[12.5px] text-[#6c6f70] sm:inline">{l.desc}</span></span>
              <ArrowRight className="size-3.5 text-[#6c6f70] opacity-0 group-data-[selected=true]:opacity-100" aria-hidden />
            </Command.Item>
          ))}
        </Command.Group>

        <Command.Group heading="Dashboard">
          {DASHBOARD_LINKS.map((l) => (
            <Command.Item key={l.id} value={`${l.label} ${l.desc} dashboard`} onSelect={() => go(l.to)} className={itemCls}>
              <l.Icon className="size-4 shrink-0 text-[#a1a4a5] group-data-[selected=true]:text-mint" aria-hidden />
              <span className="flex-1">{l.label}{" "}<span className="ml-2 hidden text-[12.5px] text-[#6c6f70] sm:inline">{l.desc}</span></span>
              <ArrowRight className="size-3.5 text-[#6c6f70] opacity-0 group-data-[selected=true]:opacity-100" aria-hidden />
            </Command.Item>
          ))}
        </Command.Group>

        {items.length > 0 && (
          <Command.Group heading={`Imported experiments (${items.length})`}>
            {items.slice(0, 8).map(({ exp }) => (
              <Command.Item key={exp.experiment_id} value={`results ${exp.experiment_id} ${exp.config.pattern} ${exp.config.contention}`} onSelect={() => go(`/dashboard/results/${encodeURIComponent(exp.experiment_id)}`)} className={itemCls}>
                <FileJson className="size-4 shrink-0 text-sky" aria-hidden />
                <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{exp.experiment_id}</span>
                <span className="text-[12px] text-[#6c6f70]">{exp.summary.total_requests} requests</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        <Command.Group heading="Copy a command">
          <Command.Item value="copy reset the data seed" onSelect={() => copy("reset the data", ".venv/bin/python -m app.seed")} className={itemCls}>
            <Terminal className="size-4 shrink-0 text-[#a1a4a5]" aria-hidden /><span className="flex-1">Reset the data{" "}<span className="ml-2 font-mono text-[12px] text-[#6c6f70]">app.seed</span></span><Copy className="size-3.5 text-[#6c6f70]" aria-hidden />
          </Command.Item>
          <Command.Item value="copy start the server uvicorn defaults" onSelect={() => copy("start the server", buildServerCommand(16, 4, 2))} className={itemCls}>
            <Terminal className="size-4 shrink-0 text-[#a1a4a5]" aria-hidden /><span className="flex-1">Start the server{" "}<span className="ml-2 font-mono text-[12px] text-[#6c6f70]">16 · 4 · 2</span></span><Copy className="size-3.5 text-[#6c6f70]" aria-hidden />
          </Command.Item>
          {PRESET_PATCHES.map((p) => (
            <Command.Item key={p.id} value={`copy command workload ${p.label} ${p.patch.pattern ?? ""} ${p.patch.arrival_model ?? ""}`} onSelect={() => copy(`${p.label} workload`, buildCommand({ ...DEFAULT_CONFIG, ...p.patch }))} className={itemCls}>
              <Terminal className="size-4 shrink-0 text-[#a1a4a5]" aria-hidden /><span className="flex-1">{p.label} workload{" "}<span className="ml-2 text-[12.5px] text-[#6c6f70]">generator command</span></span><Copy className="size-3.5 text-[#6c6f70]" aria-hidden />
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>

      <div className="flex items-center justify-between gap-4 border-t border-[var(--lp-line-soft)] px-4 py-2.5 text-[12px] text-[#6c6f70]">
        <span className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1"><kbd className="rounded border border-[var(--lp-line-soft)] px-1 font-mono">↑↓</kbd> move</span>
          <span className="inline-flex items-center gap-1"><CornerDownLeft className="size-3" aria-hidden /> open</span>
        </span>
        <span aria-live="polite" className={copied ? "inline-flex items-center gap-1.5 text-mint" : ""}>{copied ? <><Check className="size-3.5" /> Copied: {copied}</> : "Commands are copied, never run"}</span>
      </div>
    </Command.Dialog>
  );
}
