import type { ReactNode } from "react";
import { Reveal } from "@/components/ui/Reveal";
import { cn } from "@/lib/cn";
import { VideoTile } from "./VideoTile";
import type { MediaName } from "./VideoTile";

/** Tile + large heading + muted paragraph, centred. The rhythm used by most sections. */
export function SectionHead({ tile, tileLabel, title, children, className }: { tile?: Exclude<MediaName, "hero">; tileLabel?: string; title: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <Reveal className={cn("mx-auto flex max-w-[800px] flex-col items-center text-center", className)}>
      {tile && <VideoTile name={tile} label={tileLabel ?? ""} />}
      <h2 className={cn("lp-h2 grad-text", tile && "mt-6")}>{title}</h2>
      {children && <p className="lp-p mt-5 max-w-[680px] text-pretty">{children}</p>}
    </Reveal>
  );
}

/** Left-aligned heading used above two-column card rows. */
export function SectionHeadLeft({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <Reveal className="max-w-[720px]">
      <h2 className="lp-h2 grad-text">{title}</h2>
      {children && <p className="lp-p mt-5">{children}</p>}
    </Reveal>
  );
}
