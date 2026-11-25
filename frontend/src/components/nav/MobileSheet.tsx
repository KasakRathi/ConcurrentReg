import * as Dialog from "@radix-ui/react-dialog";
import { ChevronDown, Search, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { BackendStatus } from "@/hooks/backend-status";
import { cn } from "@/lib/cn";
import { Wordmark } from "@/components/ui/Logo";
import { MENUS } from "./nav-data";
import { usePalette } from "./palette";
import { useNavClick } from "./MenuPanels";

/** Full-screen mobile menu: grouped links that expand, a search button, the primary action and the real backend state. */
export function MobileSheet({ open, onOpenChange, backend }: { open: boolean; onOpenChange: (o: boolean) => void; backend: BackendStatus }) {
  const [group, setGroup] = useState<string | null>("product");
  const palette = usePalette();
  const click = useNavClick();
  const close = () => onOpenChange(false);
  let n = 0;
  const stagger = () => ({ animationDelay: `${60 + n++ * 45}ms` });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/80 backdrop-blur-sm data-[state=open]:animate-fade-in" />
        <Dialog.Content className="lp nav-sheet fixed inset-0 z-[70] flex flex-col overflow-y-auto bg-black px-6 pb-[max(24px,env(safe-area-inset-bottom))] pt-4 focus:outline-none">
          <Dialog.Title className="sr-only">Menu</Dialog.Title>
          <Dialog.Description className="sr-only">Site navigation, search and the primary action</Dialog.Description>
          <div className="flex h-[50px] items-center justify-between">
            <Link to="/" onClick={close} aria-label="ConcurrentReg home"><Wordmark /></Link>
            <Dialog.Close asChild><button className="grid size-11 place-items-center rounded-xl text-[#a1a4a5] transition active:scale-95" aria-label="Close menu"><X className="size-5" /></button></Dialog.Close>
          </div>

          <button onClick={() => { close(); setTimeout(() => palette.setOpen(true), 180); }} style={stagger()} className="nav-sheet-item mt-6 flex h-12 items-center gap-3 rounded-2xl border border-[var(--lp-line-soft)] bg-white/[0.03] px-4 text-left text-[15px] text-[#a1a4a5]">
            <Search className="size-4" aria-hidden /> Search pages, runs, commands
          </button>

          <nav aria-label="Mobile" className="mt-6 flex-1">
            <ul className="divide-y divide-white/[0.06]">
              {MENUS.map((m) => {
                const expanded = group === m.id;
                return (
                  <li key={m.id} className="nav-sheet-item" style={stagger()}>
                    <button onClick={() => setGroup(expanded ? null : m.id)} aria-expanded={expanded} className="flex w-full items-center justify-between py-4 text-left text-[24px] font-light tracking-tight text-[#f0f0f0]">
                      {m.label}
                      <ChevronDown className={cn("size-5 text-[#6c6f70] transition-transform duration-300", expanded && "rotate-180 text-mint")} aria-hidden />
                    </button>
                    <div className={cn("grid transition-[grid-template-rows] duration-300 ease-out", expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                      <ul className="overflow-hidden">
                        {m.links.map((l) => (
                          <li key={l.id}>
                            <Link to={l.to} onClick={(e) => { click(l.to)(e); close(); }} tabIndex={expanded ? 0 : -1} className="flex items-start gap-3 rounded-xl py-3 pl-1 active:bg-white/[0.05]">
                              <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl border border-[var(--lp-line-soft)] text-mint"><l.Icon className="size-[17px]" aria-hidden /></span>
                              <span><span className="block text-[16px] text-white">{l.label}</span><span className="block text-[13.5px] text-[#a1a4a5]">{l.desc}</span></span>
                            </Link>
                          </li>
                        ))}
                        <li className="pb-3" />
                      </ul>
                    </div>
                  </li>
                );
              })}
              <li className="nav-sheet-item" style={stagger()}>
                <Link to="/#facts" onClick={(e) => { click("/#facts")(e); close(); }} className="block py-4 text-[24px] font-light tracking-tight text-[#f0f0f0]">Limits</Link>
              </li>
            </ul>
          </nav>

          <div className="nav-sheet-item mt-8 space-y-4" style={stagger()}>
            <Link to="/dashboard/demo" onClick={close} className="lp-btn h-14 w-full text-[16px]">Launch experiment</Link>
            <Link to="/dashboard" onClick={close} className="lp-btn lp-btn-ghost h-12 w-full">Open dashboard</Link>
            <p className="flex items-center justify-center gap-2 pt-1 text-[12.5px] text-[#6c6f70]" role="status">
              <span className={cn("size-2 rounded-full", backend.online ? "bg-mint animate-pulse-dot" : "bg-[#464a4d]")} />
              {backend.online ? "Backend online" : backend.online === false ? "Backend not running" : "Checking backend"}
            </p>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
