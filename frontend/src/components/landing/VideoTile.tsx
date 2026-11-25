import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

export type MediaName = "hero" | "cli" | "schedule" | "seed" | "ring";

/**
 * An original looping clip rendered by frontend/scripts/render-media (not a CSS imitation of video).
 * Plays only while on screen, never plays with reduced motion (the poster frame is shown instead), has no audio.
 */
export function LoopVideo({ name, className, label }: { name: MediaName; className?: string; label: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el || reduce) return;
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) void el.play().catch(() => undefined);
      else el.pause();
    });
    io.observe(el);
    return () => io.disconnect();
  }, [reduce]);
  return (
    <video
      ref={ref}
      className={className}
      muted
      loop
      playsInline
      preload={name === "hero" ? "auto" : "metadata"}
      poster={`/media/${name}-poster.jpg`}
      aria-label={label}
      role="img"
      disablePictureInPicture
    >
      <source src={`/media/${name}.webm`} type="video/webm" />
      <source src={`/media/${name}.mp4`} type="video/mp4" />
    </video>
  );
}

export function VideoTile({ name, label, className }: { name: Exclude<MediaName, "hero">; label: string; className?: string }) {
  return (
    <div className={cn("lp-tile", className)}>
      <LoopVideo name={name} label={label} className="size-full object-cover" />
    </div>
  );
}
