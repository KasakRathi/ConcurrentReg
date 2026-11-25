import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

export function CodeBlock({ code, title, className }: { code: string; title?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  };
  return (
    <div className={cn("overflow-hidden rounded-lg border border-ink-700 bg-ink-900", className)}>
      <div className="flex items-center justify-between border-b border-ink-700 px-3 py-1.5">
        <span className="font-mono text-[11px] text-ink-300">{title ?? "terminal"}</span>
        <button onClick={copy} className="inline-flex items-center gap-1.5 rounded px-1.5 py-1 text-[11px] text-ink-300 hover:bg-white/[0.06] hover:text-ink-50" aria-label="Copy to clipboard">
          {copied ? <Check className="size-3.5 text-mint" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="scroll-x p-4 text-[12.5px] leading-6 text-ink-100"><code>{code}</code></pre>
    </div>
  );
}
