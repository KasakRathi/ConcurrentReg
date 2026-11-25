import * as NavigationMenu from "@radix-ui/react-navigation-menu";
import { ArrowUpRight } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import type { BackendStatus } from "@/hooks/backend-status";
import { cn } from "@/lib/cn";
import type { NavCardDef, NavLinkDef, NavMenuDef } from "./nav-data";

/** In-page links must scroll even when the hash is already set (the router sees no change then). */
export function useNavClick() {
  const { pathname, hash } = useLocation();
  return (to: string) => (e: React.MouseEvent) => {
    if (to.startsWith("/#") && pathname === "/" && hash === to.slice(1)) {
      e.preventDefault();
      document.getElementById(to.slice(2))?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  };
}

export function isLinkActive(to: string, pathname: string, activeSection: string | null) {
  if (to.startsWith("/#")) return pathname === "/" && activeSection === to.slice(2);
  return pathname === to;
}

function LinkRow({ link, active, onClick }: { link: NavLinkDef; active: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <li>
      <NavigationMenu.Link asChild active={active}>
        <Link to={link.to} onClick={onClick} className="nav-row group/row flex items-start gap-3 rounded-2xl p-2.5 outline-none transition-colors hover:bg-white/[0.06] focus-visible:bg-white/[0.08] focus-visible:ring-2 focus-visible:ring-white/30 data-[active]:bg-white/[0.05]">
          <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl border border-[var(--lp-line-soft)] bg-white/[0.03] text-[#a1a4a5] transition-colors group-hover/row:border-mint/30 group-hover/row:text-mint group-data-[active]/row:text-mint">
            <link.Icon className="size-[17px]" aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-[14.5px] font-medium text-[#f0f0f0]">
              {link.label}
              <ArrowUpRight className="size-3.5 -translate-x-1 text-[#6c6f70] opacity-0 transition-all group-hover/row:translate-x-0 group-hover/row:opacity-100" aria-hidden />
            </span>
            <span className="mt-0.5 block text-[13px] leading-[18px] text-[#a1a4a5]">{link.desc}</span>
          </span>
        </Link>
      </NavigationMenu.Link>
    </li>
  );
}

function Card({ card, onClick }: { card: NavCardDef; onClick: (e: React.MouseEvent) => void }) {
  return (
    <NavigationMenu.Link asChild>
      <Link to={card.to} onClick={onClick} className="group/card relative flex min-h-[188px] flex-col justify-end overflow-hidden rounded-2xl border border-[var(--lp-line-soft)] bg-black p-3.5 outline-none transition-[border-color,transform] duration-300 hover:-translate-y-0.5 hover:border-[var(--lp-line)] focus-visible:ring-2 focus-visible:ring-white/30">
        <img src={card.poster} alt="" aria-hidden className="absolute inset-0 size-full scale-100 object-cover opacity-90 transition-transform duration-500 ease-out group-hover/card:scale-[1.07]" />
        <span aria-hidden className="absolute inset-0 bg-gradient-to-t from-black via-black/55 to-transparent" />
        <span className="relative">
          <span className="block text-[14px] font-medium leading-5 text-white">{card.title}</span>
          <span className="mt-0.5 block text-[12.5px] text-[#a1a4a5]">{card.desc}</span>
        </span>
      </Link>
    </NavigationMenu.Link>
  );
}

function LiveCard({ backend }: { backend: BackendStatus }) {
  const { online, status } = backend;
  return (
    <div className="flex min-h-[188px] flex-col justify-between rounded-2xl border border-[var(--lp-line-soft)] bg-white/[0.02] p-4">
      <div>
        <p className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.14em] text-[#a1a4a5]">
          <span className={cn("size-2 rounded-full", online ? "bg-mint animate-pulse-dot" : online === false ? "bg-[#6c6f70]" : "bg-[#464a4d]")} />
          {online ? "Live API" : online === false ? "Backend not running" : "Checking"}
        </p>
        {online && status ? (
          <dl className="mt-4 space-y-2.5 text-[13px]">
            {[["Queue", `${status.queue.depth} / ${status.queue.capacity}`], ["Workers", `${status.workers.active} / ${status.workers.configured}`], ["Permits held", `${status.db_semaphore.in_critical_section} / ${status.db_semaphore.permits}`], ["Accepted", String(status.queue.accepted)]].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-white/[0.05] pb-2 last:border-0"><dt className="text-[#a1a4a5]">{k}</dt><dd className="tabular font-mono text-white">{v}</dd></div>
            ))}
          </dl>
        ) : (
          <p className="mt-4 text-[13px] leading-5 text-[#a1a4a5]">{online === false ? <>Nothing is shown in place of live data. Start it with <code className="text-white">uvicorn app.main:app</code>.</> : "Waiting for GET /os-layer/status."}</p>
        )}
      </div>
      <NavigationMenu.Link asChild>
        <Link to="/dashboard/monitoring" className="mt-4 inline-flex items-center gap-1 text-[13px] text-white underline-offset-4 outline-none hover:underline focus-visible:underline">Open monitoring <ArrowUpRight className="size-3.5" aria-hidden /></Link>
      </NavigationMenu.Link>
    </div>
  );
}

export function MenuPanel({ menu, activeSection, backend }: { menu: NavMenuDef; activeSection: string | null; backend: BackendStatus }) {
  const { pathname } = useLocation();
  const click = useNavClick();
  return (
    <NavigationMenu.Content className="nav-content">
      <div className="grid gap-3 p-3" style={{ width: menu.width, gridTemplateColumns: menu.id === "dashboard" ? "1.25fr 1fr" : menu.cards ? "minmax(0,1.1fr) minmax(0,1fr)" : "1fr" }}>
        <ul className="self-start">{menu.links.map((l) => <LinkRow key={l.id} link={l} active={isLinkActive(l.to, pathname, activeSection)} onClick={click(l.to)} />)}</ul>
        {menu.cards ? <div className="grid grid-cols-2 gap-2.5">{menu.cards.map((c) => <Card key={c.id} card={c} onClick={click(c.to)} />)}</div> : <LiveCard backend={backend} />}
      </div>
    </NavigationMenu.Content>
  );
}
