import { cn } from "@/lib/cn";

/** Original ConcurrentReg mark: three request lanes merging into one committed row. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden="true">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="#0b0d0f" stroke="#2a2f33" />
      <path d="M8 11h9M8 16h16M8 21h11" stroke="#6ee7b7" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="23" cy="11" r="2.2" fill="#6ee7b7" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 font-medium tracking-tight text-ink-50", className)}>
      <LogoMark />
      <span>
        Concurrent<span className="text-mint">Reg</span>
      </span>
    </span>
  );
}
