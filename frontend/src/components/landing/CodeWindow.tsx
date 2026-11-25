import { Check, Copy } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

const KEYWORDS = new Set(["def", "return", "if", "for", "in", "try", "except", "with", "finally", "yield", "import", "from", "class", "not", "and", "or", "else", "elif", "as", "is", "None", "True", "False", "self"]);
const TOKEN = /(#.*$)|("""[^"]*"""|"[^"]*"|'[^']*'|`[^`]*`)|(\s--?[a-zA-Z][\w-]*)|(\b[A-Z_]{3,}=)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)/g;

/** A deliberately small highlighter for Python and shell lines: comments, strings, flags, env vars, keywords. */
export function highlight(line: string): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of line.matchAll(TOKEN)) {
    const i = m.index ?? 0;
    if (i > last) out.push(line.slice(last, i));
    const [text, comment, str, flag, env, num, word] = m;
    if (comment) out.push(<span key={key++} className="text-[#6c6f70]">{text}</span>);
    else if (str) out.push(<span key={key++} className="text-[#ffff92]">{text}</span>);
    else if (flag) out.push(<Fragment key={key++}>{text[0]}<span className="text-sky">{text.slice(1)}</span></Fragment>);
    else if (env) out.push(<span key={key++} className="text-mint">{text}</span>);
    else if (num) out.push(<span key={key++} className="text-[#ffca16]">{text}</span>);
    else if (word && KEYWORDS.has(word)) out.push(<span key={key++} className="text-[#a1a4a5]">{text}</span>);
    else out.push(text);
    last = i + text.length;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

export function CodeLines({ code, className, lineHeight = 20 }: { code: string; className?: string; lineHeight?: number }) {
  const lines = code.split("\n");
  return (
    <pre className={cn("scroll-x font-mono text-[13px] text-[#f0f0f0]", className)} style={{ lineHeight: `${lineHeight}px` }}>
      <code className="grid grid-cols-[auto_1fr] gap-x-4">
        {lines.map((l, i) => (
          <Fragment key={i}>
            <span className="code-line-no select-none">{i + 1}</span>
            <span className="whitespace-pre">{l === "" ? " " : highlight(l)}</span>
          </Fragment>
        ))}
      </code>
    </pre>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch { /* clipboard blocked */ }
      }}
      className="grid size-8 place-items-center rounded-lg border border-[var(--lp-line)] text-[#a1a4a5] transition hover:bg-white/10 hover:text-white"
      aria-label={`${label} to clipboard`}
    >
      {done ? <Check className="size-4 text-mint" /> : <Copy className="size-4" />}
    </button>
  );
}
