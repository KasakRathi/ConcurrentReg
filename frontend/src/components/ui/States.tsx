import { AlertTriangle, DatabaseZap, Inbox } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function EmptyState({ title, children, action, icon, className }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-ink-600 px-6 py-12 text-center", className)}>
      <div className="text-ink-300">{icon ?? <Inbox className="size-6" />}</div>
      <p className="text-sm font-medium text-ink-50">{title}</p>
      {children && <div className="max-w-md text-[13px] leading-relaxed text-ink-300">{children}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function ErrorState({ title, children, action, className }: { title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-2 rounded-lg border border-rose/30 bg-rose/[0.05] px-5 py-4", className)}>
      <div className="flex items-center gap-2 text-sm font-medium text-rose">
        <AlertTriangle className="size-4" />
        {title}
      </div>
      {children && <div className="text-[13px] leading-relaxed text-ink-200">{children}</div>}
      {action}
    </div>
  );
}

/** For a metric the backend does not expose. States the missing requirement instead of showing a number. */
export function Unavailable({ what, requirement }: { what: string; requirement: string }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-dashed border-ink-600 px-4 py-3">
      <DatabaseZap className="mt-0.5 size-4 shrink-0 text-ink-400" />
      <div className="text-[13px] leading-relaxed">
        <p className="font-medium text-ink-100">{what}: not available</p>
        <p className="text-ink-300">{requirement}</p>
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-shimmer rounded-md bg-[linear-gradient(90deg,transparent,rgb(255_255_255/0.06),transparent)] bg-[length:200%_100%] bg-ink-800", className)}
      aria-hidden="true"
    />
  );
}
