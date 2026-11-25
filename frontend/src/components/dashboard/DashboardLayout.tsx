import * as Dialog from "@radix-ui/react-dialog";
import { Activity, Boxes, PlayCircle, ChevronsLeft, ChevronsRight, FlaskConical, Gauge, Home, Menu, Search, SlidersHorizontal, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { MonitorProvider, useMonitor } from "@/hooks/monitor";
import { DemoProvider } from "@/hooks/demo";
import { looksOffline } from "@/lib/api";
import { useResults } from "@/hooks/results-store";
import { cn } from "@/lib/cn";
import { fmtClock } from "@/lib/format";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { LogoMark, Wordmark } from "@/components/ui/Logo";
import { Tooltip } from "@/components/ui/Tooltip";
import { usePalette } from "@/components/nav/palette";

const NAV = [
  { to: "/dashboard/demo", label: "Live demo", icon: PlayCircle },
  { to: "/dashboard", label: "Overview", icon: Gauge, end: true },
  { to: "/dashboard/monitoring", label: "Monitoring", icon: Activity },
  { to: "/dashboard/experiments", label: "Experiments", icon: FlaskConical },
  { to: "/dashboard/workloads", label: "Workloads", icon: SlidersHorizontal },
  { to: "/dashboard/architecture", label: "Architecture", icon: Boxes },
];

const CRUMBS: Record<string, string> = { demo: "Live demo", monitoring: "Monitoring", experiments: "Experiments", workloads: "Workloads", architecture: "Architecture", results: "Results" };

function SearchButton() {
  const palette = usePalette();
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  return (
    <button onClick={palette.toggle} aria-label={`Search ${mac ? "⌘K" : "Ctrl K"}`} aria-keyshortcuts="Control+K Meta+K" className="flex h-8 items-center gap-2 rounded-lg border border-ink-600 bg-white/[0.03] px-2.5 text-[12.5px] text-ink-300 transition hover:border-ink-400 hover:text-ink-50">
      <Search className="size-3.5" aria-hidden />
      <span className="hidden xl:inline">Search</span>
      <kbd className="hidden rounded border border-ink-600 px-1 font-mono text-[10px] text-ink-400 xl:inline">{mac ? "⌘K" : "Ctrl K"}</kbd>
    </button>
  );
}

function SystemStatus() {
  const { status, error, paused, lastOkAt, intervalMs } = useMonitor();
  let tone = "bg-ink-500";
  let label = "Connecting";
  let detail = "Waiting for the first answer from GET /os-layer/status.";
  if (paused) { label = "Paused"; detail = "Polling is paused. The numbers shown are the last ones received."; }
  else if (error) { tone = "bg-rose"; label = looksOffline(error) ? "API offline" : "API error"; detail = error.message; }
  else if (status) { tone = "bg-mint animate-pulse-dot"; label = "API online"; detail = `Polled every ${intervalMs / 1000} s. Last answer at ${lastOkAt ? fmtClock(lastOkAt) : "n/a"}.`; }
  return (
    <Tooltip content={detail} side="bottom">
      <div className="inline-flex items-center gap-2 rounded-full border border-ink-600 px-3 py-1.5 text-[12.5px] text-ink-100" role="status" aria-live="polite">
        <span className={cn("size-2 rounded-full", tone)} />
        {label}
      </div>
    </Tooltip>
  );
}

function ExperimentSelector() {
  const { items, selectedId, select } = useResults();
  const navigate = useNavigate();
  const location = useLocation();
  if (items.length === 0) return <span className="hidden text-xs text-ink-400 lg:inline">No experiment loaded</span>;
  return (
    <label className="hidden items-center gap-2 lg:flex">
      <span className="eyebrow">Experiment</span>
      <select
        value={selectedId ?? ""}
        onChange={(e) => {
          select(e.target.value);
          if (location.pathname.startsWith("/dashboard/results/")) navigate(`/dashboard/results/${encodeURIComponent(e.target.value)}`);
        }}
        className="max-w-[260px] truncate rounded-md border border-ink-600 bg-ink-900 px-2.5 py-1.5 font-mono text-[12px] text-ink-50 focus:border-mint"
        aria-label="Selected experiment"
      >
        {items.map((i) => <option key={i.exp.experiment_id} value={i.exp.experiment_id}>{i.exp.experiment_id}</option>)}
      </select>
    </label>
  );
}

const WINDOWS: [string, number][] = [["1 min", 60_000], ["5 min", 300_000], ["15 min", 900_000], ["All", 0]];

function TimeRange() {
  const { windowMs, setWindowMs } = useMonitor();
  return (
    <div className="hidden items-center gap-2 md:flex" role="group" aria-label="Time range of live samples">
      <span className="eyebrow">Window</span>
      <div className="flex rounded-md border border-ink-600 p-0.5">
        {WINDOWS.map(([l, v]) => (
          <button key={l} onClick={() => setWindowMs(v)} aria-pressed={windowMs === v} className={cn("rounded px-2 py-1 text-[12px] transition", windowMs === v ? "bg-ink-600 text-ink-50" : "text-ink-300 hover:text-ink-50")}>{l}</button>
        ))}
      </div>
    </div>
  );
}

function Breadcrumb() {
  const { pathname } = useLocation();
  const parts = pathname.replace(/^\/dashboard\/?/, "").split("/").filter(Boolean);
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px] text-ink-300">
      <Link to="/dashboard" className="hover:text-ink-50">Dashboard</Link>
      {parts.map((p, i) => (
        <Fragment key={i}>
          <span aria-hidden className="text-ink-500">/</span>
          <span className={cn("truncate", i === parts.length - 1 && "text-ink-50")} aria-current={i === parts.length - 1 ? "page" : undefined}>{CRUMBS[p] ?? decodeURIComponent(p)}</span>
        </Fragment>
      ))}
      {parts.length === 0 && <><span aria-hidden className="text-ink-500">/</span><span className="text-ink-50" aria-current="page">Overview</span></>}
    </nav>
  );
}

function NavList({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <ul className="space-y-1">
      {NAV.map(({ to, label, icon: Icon, end }) => {
        const link = (
          <NavLink to={to} end={end} onClick={onNavigate} aria-label={collapsed ? label : undefined} className={({ isActive }) => cn("flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition", collapsed && "justify-center px-0", isActive ? "bg-white/[0.07] text-ink-50 shadow-[inset_2px_0_0_0_var(--color-mint)]" : "text-ink-300 hover:bg-white/[0.04] hover:text-ink-50")}>
            <Icon className="size-4 shrink-0" />
            {!collapsed && label}
          </NavLink>
        );
        // The tooltip is only useful when the label is hidden. A <span> wrapper keeps NavLink's function className intact.
        return <li key={to}>{collapsed ? <Tooltip content={label} side="right"><span className="block">{link}</span></Tooltip> : link}</li>;
      })}
    </ul>
  );
}

function Shell() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("creg.sidebar") === "1"; } catch { return false; }
  });
  const [drawer, setDrawer] = useState(false);
  useEffect(() => {
    try { localStorage.setItem("creg.sidebar", collapsed ? "1" : "0"); } catch { /* storage unavailable */ }
  }, [collapsed]);
  const { pathname } = useLocation();
  const showWindow = pathname === "/dashboard" || pathname.startsWith("/dashboard/monitoring");

  return (
    <div className="flex min-h-screen bg-ink-950">
      <aside className={cn("sticky top-0 hidden h-screen shrink-0 flex-col border-r border-ink-800 bg-ink-900/60 transition-[width] duration-300 ease-[var(--ease-out-quint)] md:flex", collapsed ? "w-[68px]" : "w-60")}>
        <div className={cn("flex h-14 items-center border-b border-ink-800 px-4", collapsed && "justify-center px-0")}>
          <Link to="/" aria-label="ConcurrentReg home">{collapsed ? <LogoMark /> : <Wordmark />}</Link>
        </div>
        <nav className="flex-1 overflow-y-auto p-3" aria-label="Dashboard"><NavList collapsed={collapsed} /></nav>
        <div className="space-y-1 border-t border-ink-800 p-3">
          <Link to="/" className={cn("flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-300 hover:bg-white/[0.04] hover:text-ink-50", collapsed && "justify-center px-0")} aria-label="Back to site"><Home className="size-4" />{!collapsed && "Back to site"}</Link>
          <button onClick={() => setCollapsed((c) => !c)} className={cn("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-300 hover:bg-white/[0.04] hover:text-ink-50", collapsed && "justify-center px-0")} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}{!collapsed && "Collapse"}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-ink-800 bg-ink-950/80 px-4 backdrop-blur-xl sm:px-6">
          <Dialog.Root open={drawer} onOpenChange={setDrawer}>
            <Dialog.Trigger asChild><button className="grid size-9 place-items-center rounded-lg border border-ink-600 md:hidden" aria-label="Open navigation"><Menu className="size-4" /></button></Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-black/70" />
              <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-72 border-r border-ink-700 bg-ink-900 p-4">
                <Dialog.Title className="sr-only">Dashboard navigation</Dialog.Title>
                <Dialog.Description className="sr-only">Pages of the experiment dashboard</Dialog.Description>
                <div className="mb-4 flex items-center justify-between"><Wordmark /><Dialog.Close asChild><button className="grid size-8 place-items-center rounded-lg border border-ink-600" aria-label="Close navigation"><X className="size-4" /></button></Dialog.Close></div>
                <NavList collapsed={false} onNavigate={() => setDrawer(false)} />
                <Link to="/" onClick={() => setDrawer(false)} className="mt-4 flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-300"><Home className="size-4" /> Back to site</Link>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
          <div className="min-w-0 flex-1"><Breadcrumb /></div>
          {showWindow && <TimeRange />}
          <ExperimentSelector />
          <SearchButton />
          <SystemStatus />
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 sm:py-8">
          <ErrorBoundary label="This dashboard page"><Outlet /></ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export default function DashboardLayout() {
  return (
    <MonitorProvider>
      <DemoProvider>
        <Shell />
      </DemoProvider>
    </MonitorProvider>
  );
}
