import * as NavigationMenu from "@radix-ui/react-navigation-menu";
import { ChevronDown, Menu, Search } from "lucide-react";
import { motion, useReducedMotion, useScroll, useSpring } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useBackendStatus } from "@/hooks/backend-status";
import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/ui/Tooltip";
import { MobileSheet } from "./MobileSheet";
import { MenuPanel, useNavClick } from "./MenuPanels";
import { MENUS, menuForSection } from "./nav-data";
import { usePalette } from "./palette";
import { useActiveSection } from "./useActiveSection";

function Logo() {
  // Original mark; the three request lanes shift on hover (CSS in index.css: .logo-lane).
  return (
    <svg viewBox="0 0 32 32" className="size-8" aria-hidden="true">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="#0b0d0f" stroke="#2a2f33" />
      <g stroke="#6ee7b7" strokeWidth="2.4" strokeLinecap="round">
        <path className="logo-lane logo-lane-1" d="M8 11h9" />
        <path className="logo-lane logo-lane-2" d="M8 16h16" />
        <path className="logo-lane logo-lane-3" d="M8 21h11" />
      </g>
      <circle className="logo-dot" cx="23" cy="11" r="2.2" fill="#6ee7b7" />
    </svg>
  );
}

const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function BackendChip({ backend }: { backend: ReturnType<typeof useBackendStatus> }) {
  const { online, status } = backend;
  const text = online
    ? `Backend online · queue ${status?.queue.depth}/${status?.queue.capacity} · workers ${status?.workers.active}/${status?.workers.configured}`
    : online === false
      ? "Backend not running. Start it with: uvicorn app.main:app --port 8000"
      : "Checking the backend…";
  return (
    <Tooltip content={text} side="bottom">
      <Link to="/dashboard/monitoring" aria-label={text} className="hidden size-9 place-items-center rounded-xl transition-colors hover:bg-white/[0.07] md:grid">
        <span className={cn("size-2 rounded-full", online ? "bg-mint animate-pulse-dot" : online === false ? "bg-[#6c6f70]" : "bg-[#464a4d]")} />
      </Link>
    </Tooltip>
  );
}

export function SiteNav() {
  const { pathname } = useLocation();
  const click = useNavClick();
  const palette = usePalette();
  const reduce = useReducedMotion();
  const backend = useBackendStatus();
  const activeSection = useActiveSection(pathname === "/");
  const activeMenu = menuForSection(activeSection);

  const [scrolled, setScrolled] = useState(false);
  const [value, setValue] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [glide, setGlide] = useState(false);
  const [sheet, setSheet] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const triggers = useRef<Record<string, HTMLButtonElement | null>>({});
  const shortcut = useMemo(() => (isMac() ? "⌘K" : "Ctrl K"), []);

  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 180, damping: 30, mass: 0.4 });

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  useEffect(() => setSheet(false), [pathname]);

  // The popup follows the trigger it belongs to (and stays inside the window); it only glides sideways when moving between menus.
  const onValueChange = (next: string) => {
    setGlide(next !== "" && value !== "");
    setValue(next);
    const menu = MENUS.find((m) => m.id === next);
    const trig = triggers.current[next];
    const root = rootRef.current;
    if (!menu || !trig || !root) return;
    const t = trig.getBoundingClientRect();
    const r = root.getBoundingClientRect();
    const center = t.left + t.width / 2;
    const half = menu.width / 2;
    const clamped = Math.min(Math.max(center, 16 + half), window.innerWidth - 16 - half);
    setOffset(clamped - (r.left + r.width / 2));
  };

  const highlight = hover ?? (value || null);
  const spring = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 520, damping: 40, mass: 0.7 };
  const triggerCls = "nav-trigger group relative isolate flex h-10 items-center gap-1 rounded-xl px-3 text-[15px] font-medium text-[#a1a4a5] outline-none transition-colors duration-150 hover:text-white focus-visible:text-white focus-visible:ring-2 focus-visible:ring-white/35 data-[state=open]:text-white";

  const Highlight = ({ id }: { id: string }) =>
    highlight === id ? <motion.span layoutId="nav-highlight" transition={spring} className="absolute inset-0 -z-10 rounded-xl bg-white/[0.08]" aria-hidden /> : null;

  return (
    <header className="fixed inset-x-0 top-0 z-50 animate-header-in" data-scrolled={scrolled}>
      <div className={cn("relative isolate mx-auto transition-[max-width,margin] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]", scrolled ? "mt-2.5 max-w-[1060px]" : "mt-0 max-w-[1232px]")}>
        {/* The frosted pill is its own layer, so the popup below is not nested inside a backdrop-filter (which would stop it blurring the page). */}
        <span aria-hidden className={cn("pointer-events-none absolute inset-0 -z-10 rounded-[22px] border border-white/[0.09] bg-black/55 shadow-[0_18px_60px_-20px_rgba(0,0,0,0.9),inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-xl backdrop-saturate-150 transition-opacity duration-500", scrolled ? "opacity-100" : "opacity-0")} />
        <span aria-hidden className={cn("pointer-events-none absolute inset-x-0 -top-2.5 -z-10 h-[78px] bg-gradient-to-b from-black/70 to-transparent transition-opacity duration-500", scrolled ? "opacity-0" : "opacity-100")} />
        <div className="relative flex h-[58px] items-center justify-between gap-3 px-4 sm:px-6 min-[1360px]:px-0" style={scrolled ? { paddingInline: 16 } : undefined}>
          <Link to="/" aria-label="ConcurrentReg home" className="group flex shrink-0 items-center gap-2.5 rounded-lg font-medium tracking-tight text-white outline-none focus-visible:ring-2 focus-visible:ring-white/35" onClick={click("/#top")}>
            <Logo />
            <span className="hidden sm:inline">Concurrent<span className="text-mint">Reg</span></span>
          </Link>

          <NavigationMenu.Root ref={rootRef} value={value} onValueChange={onValueChange} delayDuration={110} skipDelayDuration={450} aria-label="Main" className="relative hidden md:block">
            <NavigationMenu.List className="flex items-center gap-0.5" onPointerLeave={() => setHover(null)}>
              {MENUS.map((m) => (
                <NavigationMenu.Item key={m.id} value={m.id} onPointerEnter={() => setHover(m.id)}>
                  <NavigationMenu.Trigger ref={(el) => { triggers.current[m.id] = el; }} className={triggerCls}>
                    <Highlight id={m.id} />
                    {m.label}
                    <ChevronDown className="size-3.5 opacity-70 transition-transform duration-300 group-data-[state=open]:rotate-180" aria-hidden />
                    {activeMenu === m.id && <span aria-hidden title="You are in this part of the page" className="absolute -bottom-0.5 left-1/2 size-1 -translate-x-1/2 rounded-full bg-mint shadow-[0_0_8px_#6ee7b7]" />}
                  </NavigationMenu.Trigger>
                  <MenuPanel menu={m} activeSection={activeSection} backend={backend} />
                </NavigationMenu.Item>
              ))}
              <NavigationMenu.Item onPointerEnter={() => setHover("limits")}>
                <NavigationMenu.Link asChild active={activeSection === "facts" && pathname === "/"}>
                  <Link to="/#facts" onClick={click("/#facts")} className={cn(triggerCls, "data-[active]:text-white")}>
                    <Highlight id="limits" />
                    Limits
                  </Link>
                </NavigationMenu.Link>
              </NavigationMenu.Item>
            </NavigationMenu.List>

            <div className="absolute left-1/2 top-full" style={{ transform: `translateX(calc(-50% + ${offset}px))`, transition: glide && !reduce ? "transform 350ms cubic-bezier(0.22,1,0.36,1)" : "none" }}>
              <NavigationMenu.Viewport className="nav-viewport" />
            </div>
          </NavigationMenu.Root>

          <div className="flex items-center gap-1.5">
            <button onClick={palette.toggle} aria-label={`Search ${shortcut}`} aria-keyshortcuts="Control+K Meta+K" className="group flex h-9 items-center gap-2 rounded-xl border border-[var(--lp-line-soft)] bg-white/[0.03] px-2.5 text-[13.5px] text-[#a1a4a5] outline-none transition-colors hover:border-[var(--lp-line)] hover:bg-white/[0.06] hover:text-white focus-visible:ring-2 focus-visible:ring-white/35 lg:min-w-[148px] lg:pl-3">
              <Search className="size-4" aria-hidden />
              <span className="hidden lg:inline">Search</span>
              <kbd className="ml-auto hidden rounded-md border border-[var(--lp-line-soft)] bg-black/40 px-1.5 py-0.5 font-mono text-[10.5px] text-[#6c6f70] lg:inline">{shortcut}</kbd>
            </button>
            <BackendChip backend={backend} />
            <Link to="/dashboard/demo" className="lp-btn lp-btn-sm nav-cta hidden sm:inline-flex">Launch experiment</Link>
            <button onClick={() => setSheet(true)} className="grid size-10 place-items-center rounded-xl text-[#d3d8dc] transition active:scale-95 md:hidden" aria-label="Open menu" aria-expanded={sheet}><Menu className="size-5" /></button>
          </div>
        </div>
        <motion.span aria-hidden style={{ scaleX: progress, opacity: scrolled ? 1 : 0 }} className="pointer-events-none absolute inset-x-6 bottom-0 h-px origin-left bg-gradient-to-r from-transparent via-mint to-sky transition-opacity duration-300" />
      </div>
      <MobileSheet open={sheet} onOpenChange={setSheet} backend={backend} />
    </header>
  );
}
