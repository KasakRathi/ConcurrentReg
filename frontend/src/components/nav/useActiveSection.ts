import { useEffect, useState } from "react";
import { SECTION_IDS } from "./nav-data";

/**
 * Scroll-spy: which landing-page section crosses the middle band of the viewport.
 * Uses IntersectionObserver (no scroll listener), so it stays cheap while scrolling.
 */
export function useActiveSection(enabled = true): string | null {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const els = SECTION_IDS.map((id) => document.getElementById(id)).filter((e): e is HTMLElement => e !== null);
    if (els.length === 0) return;
    const seen = new Map<string, number>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting ? e.intersectionRatio : 0);
        let best: string | null = null;
        let bestRatio = 0;
        for (const [id, ratio] of seen) if (ratio > bestRatio) { best = id; bestRatio = ratio; }
        setActive(best);
      },
      { rootMargin: "-35% 0px -55% 0px", threshold: [0, 0.01, 0.1, 0.5, 1] },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [enabled]);
  return active;
}
