import * as RT from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <RT.Provider delayDuration={200}>{children}</RT.Provider>;
}

export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <RT.Root>
      <RT.Trigger asChild>{children}</RT.Trigger>
      <RT.Portal>
        <RT.Content
          side={side}
          sideOffset={6}
          className="z-[100] max-w-xs rounded-md border border-ink-600 bg-ink-800 px-3 py-2 text-xs leading-relaxed text-ink-100 shadow-xl"
        >
          {content}
          <RT.Arrow className="fill-ink-600" />
        </RT.Content>
      </RT.Portal>
    </RT.Root>
  );
}
