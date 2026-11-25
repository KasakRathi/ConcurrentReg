import { useEffect, useRef } from "react";
import { COLORS } from "@/lib/theme";
import type { Packet, PipelineSim } from "@/lib/pipelineSim";

/**
 * Draws a PipelineSim. This is a simulation of the architecture, not live data:
 * the parent must label it as such. The canvas only reads the engine; it never changes the rules.
 *
 * Layout runs left-to-right on wide screens and top-to-bottom on narrow ones (`vertical`).
 */

interface Props {
  sim: PipelineSim;
  running: boolean;
  speed?: number;
  /** Called every animation frame (parent can drive scenarios from it). */
  onFrame?: (dt: number) => void;
  className?: string;
  ariaLabel: string;
}

// Each stage is a centre and a half-width along the flow axis, as fractions of its length. No two overlap.
const ST = {
  src: { c: 0.055, hw: 0.04 },
  adm: { c: 0.165, hw: 0.05 },
  queue: { c: 0.345, hw: 0.095 },
  workers: { c: 0.53, hw: 0.045 },
  sem: { c: 0.655, hw: 0.04 },
  db: { c: 0.82, hw: 0.095 },
  res: { c: 0.96, hw: 0.03 },
} as const;
const WAIT_SEM = 0.595; // where a worker holding a request waits for a permit
const LOCK = 0.775; // the row-lock marker inside the MySQL box
const WAIT_LOCK = 0.743;
const SEATS = 0.863;

interface Geometry {
  W: number;
  H: number;
  vertical: boolean;
  L: number;
  C: number;
  /** a: fraction along the flow, f: fraction across (0..1, already mapped so labels stay clear in vertical mode). */
  at: (a: number, f: number) => [number, number];
}

function geometry(W: number, H: number): Geometry {
  const vertical = W < 700;
  const L = vertical ? H : W;
  const C = vertical ? W : H;
  // In the vertical layout the left third is reserved for stage labels.
  const cross = (f: number) => (vertical ? C * (0.34 + 0.62 * f) : C * f);
  return { W, H, vertical, L, C, at: (a, f) => (vertical ? [cross(f), L * a] : [L * a, cross(f)]) };
}

/** Evenly spread `count` items across the middle of the cross axis. */
const spread = (index: number, count: number, span = 0.62) => 0.5 - span / 2 + (span * (index + 0.5)) / Math.max(count, 1);

function queuePitch(g: Geometry, capacity: number) {
  return Math.min(g.L * 0.028, (g.L * 0.17) / Math.max(capacity, 1));
}
const queueA = (g: Geometry, capacity: number, i: number) => ST.queue.c + ((capacity - 1) / 2 - i) * (queuePitch(g, capacity) / g.L);

function targetFor(p: Packet, g: Geometry, sim: PipelineSim, queueIndex: Map<number, number>): [number, number, number] {
  const S = sim.params.sections;
  const sectionF = (s: number) => spread(s, S, S === 1 ? 0.0001 : 0.7);
  if (p.phase === "queued") {
    const [x, y] = g.at(queueA(g, sim.params.queueCapacity, queueIndex.get(p.id) ?? 0), 0.5);
    return [x, y, 1];
  }
  if (p.phase === "waitSem") {
    const [x, y] = g.at(WAIT_SEM, spread(p.worker, sim.params.workers));
    return [x, y, 1];
  }
  if (p.phase === "waitLock") {
    const [x, y] = g.at(WAIT_LOCK, sectionF(p.section));
    return [x, y, 1];
  }
  if (p.phase === "holdLock") {
    const [x, y] = g.at(LOCK, sectionF(p.section));
    return [x, y, 1];
  }
  const fade = Math.max(0, 1 - p.exitT / 1.3);
  if (p.outcome === "SUCCESS") {
    const [x, y] = g.at(ST.res.c, sectionF(p.section) - 0.06);
    return [x, y, fade];
  }
  if (p.outcome === "COURSE_FULL") {
    const [x, y] = g.at(ST.res.c, sectionF(p.section) + 0.06);
    return [x, y, fade];
  }
  const [x, y] = g.at(ST.queue.c, 0.99);
  return [x, y, fade];
}

export function PipelineCanvas({ sim, running, speed = 1, onFrame, className, ariaLabel }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const runningRef = useRef(running);
  const visible = useRef(true);
  const speedRef = useRef(speed);
  const frameCb = useRef(onFrame);
  runningRef.current = running;
  speedRef.current = speed;
  frameCb.current = onFrame;

  useEffect(() => {
    const el = canvas.current;
    const box = wrap.current;
    if (!el || !box) return;
    const ctx2d = el.getContext("2d");
    if (!ctx2d) return;
    const c: CanvasRenderingContext2D = ctx2d;
    let width = 0;
    let height = 0;
    let raf = 0;
    let last = performance.now();

    const resize = () => {
      const rect = box.getBoundingClientRect();
      width = Math.max(280, Math.floor(rect.width));
      height = width < 700 ? 620 : Math.max(320, Math.min(400, Math.floor(width * 0.34)));
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      el.width = Math.floor(width * dpr);
      el.height = Math.floor(height * dpr);
      el.style.width = `${width}px`;
      el.style.height = `${height}px`;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw(0);
    };

    function stageBox(g: Geometry, st: { c: number; hw: number }, label: string, opts: { dashed?: boolean; sub?: string } = {}) {
      const [x0, y0] = g.at(st.c - st.hw, g.vertical ? 0.02 : 0.1);
      const [x1, y1] = g.at(st.c + st.hw, g.vertical ? 0.98 : 0.9);
      const x = Math.min(x0, x1);
      const y = Math.min(y0, y1);
      const w = Math.abs(x1 - x0);
      const h = Math.abs(y1 - y0);
      c.save();
      c.strokeStyle = opts.dashed ? "rgba(133,142,149,0.45)" : "rgba(255,255,255,0.10)";
      c.fillStyle = "rgba(255,255,255,0.018)";
      if (opts.dashed) c.setLineDash([4, 4]);
      c.beginPath();
      c.roundRect(x, y, w, h, 10);
      c.fill();
      c.stroke();
      c.restore();
      c.font = "500 11px 'Geist Mono Variable', ui-monospace, monospace";
      c.textBaseline = "alphabetic";
      if (g.vertical) {
        c.textAlign = "left";
        c.fillStyle = COLORS.text;
        c.fillText(label.toUpperCase(), 10, y + h / 2 - (opts.sub ? 2 : -4));
        if (opts.sub) {
          c.fillStyle = COLORS.axis;
          c.fillText(opts.sub, 10, y + h / 2 + 12);
        }
      } else {
        c.textAlign = "center";
        c.fillStyle = COLORS.text;
        c.fillText(label.toUpperCase(), x + w / 2, y - 12);
        if (opts.sub) {
          c.fillStyle = COLORS.axis;
          c.fillText(opts.sub, x + w / 2, y + h + 18);
        }
      }
    }

    function drawStatic(g: Geometry) {
      const { at } = g;
      const p = sim.params;
      stageBox(g, ST.src, "Requests");
      stageBox(g, ST.adm, "Admission", { dashed: true, sub: "optional, off" });
      stageBox(g, ST.queue, "Bounded queue", { sub: `capacity ${p.queueCapacity}` });
      stageBox(g, ST.workers, "Workers", { sub: `${p.workers} threads` });
      stageBox(g, ST.sem, "Semaphore", { sub: `${p.permits} permits` });
      stageBox(g, ST.db, "MySQL txn", { sub: "row lock + seats" });
      stageBox(g, ST.res, "Result");

      // flow rail
      c.strokeStyle = "rgba(255,255,255,0.07)";
      c.lineWidth = 1;
      c.beginPath();
      const [rx0, ry0] = at(0.02, 0.5);
      const [rx1, ry1] = at(0.985, 0.5);
      c.moveTo(rx0, ry0);
      c.lineTo(rx1, ry1);
      c.stroke();

      // queue cells (the head of the queue is on the right / bottom, next to the workers)
      const pitch = queuePitch(g, p.queueCapacity);
      const cell = pitch * 0.66;
      for (let i = 0; i < p.queueCapacity; i += 1) {
        const [x, y] = at(queueA(g, p.queueCapacity, i), 0.5);
        c.fillStyle = i < sim.queue.length ? "rgba(211,216,220,0.16)" : "rgba(255,255,255,0.04)";
        c.beginPath();
        c.roundRect(x - cell / 2, y - cell / 2, cell, cell, 3);
        c.fill();
      }
      for (let w = 0; w < p.workers; w += 1) {
        const [x, y] = at(ST.workers.c, spread(w, p.workers));
        c.strokeStyle = sim.workerSlots[w] ? "rgba(251,191,36,0.55)" : "rgba(255,255,255,0.14)";
        c.beginPath();
        c.arc(x, y, 9, 0, Math.PI * 2);
        c.stroke();
      }
      for (let k = 0; k < p.permits; k += 1) {
        const [x, y] = at(ST.sem.c, spread(k, p.permits, 0.34));
        const held = k < sim.semHolders;
        c.fillStyle = held ? "rgba(167,139,250,0.9)" : "rgba(255,255,255,0.06)";
        c.strokeStyle = "rgba(167,139,250,0.55)";
        c.beginPath();
        c.arc(x, y, 6, 0, Math.PI * 2);
        c.fill();
        c.stroke();
      }
      const S = p.sections;
      const seatSize = Math.max(6, Math.min(10, g.L * 0.011));
      for (let s = 0; s < S; s += 1) {
        const f = spread(s, S, S === 1 ? 0.0001 : 0.7);
        const [lx, ly] = at(LOCK, f);
        const held = sim.lockHolder[s] !== null;
        c.strokeStyle = held ? "rgba(167,139,250,0.95)" : "rgba(167,139,250,0.35)";
        c.lineWidth = held ? 1.6 : 1;
        c.beginPath();
        c.arc(lx, ly, 11, 0, Math.PI * 2);
        c.stroke();
        c.lineWidth = 1;
        const perRow = Math.min(5, p.seatsPerSection);
        const rows = Math.ceil(p.seatsPerSection / perRow);
        const step = seatSize * 1.55;
        const [sx0, sy0] = at(SEATS, f);
        for (let i = 0; i < p.seatsPerSection; i += 1) {
          const col = i % perRow;
          const row = Math.floor(i / perRow);
          const along = (col - (perRow - 1) / 2) * step;
          const across = (row - (rows - 1) / 2) * step;
          const sx = sx0 + (g.vertical ? across : along);
          const sy = sy0 + (g.vertical ? along : across);
          const taken = i < p.seatsPerSection - sim.seatsLeft[s];
          c.fillStyle = taken ? COLORS.mint : "rgba(255,255,255,0.05)";
          c.strokeStyle = taken ? COLORS.mint : "rgba(255,255,255,0.18)";
          c.beginPath();
          c.roundRect(sx - seatSize / 2, sy - seatSize / 2, seatSize, seatSize, 2);
          c.fill();
          c.stroke();
        }
      }
    }

    function drawPacket(p: Packet) {
      const v = p.view!;
      let color: string = COLORS.text;
      let r = 4.6;
      if (p.phase === "waitSem") color = COLORS.amber;
      else if (p.phase === "waitLock") color = COLORS.violet;
      else if (p.phase === "holdLock") {
        color = "#c4b5fd";
        r = 6;
      } else if (p.phase === "exit") {
        color = p.outcome === "SUCCESS" ? COLORS.mint : p.outcome === "COURSE_FULL" ? COLORS.amber : COLORS.rose;
        r = 5.5;
      }
      c.globalAlpha = Math.max(0, Math.min(1, v.a));
      if (p.phase === "holdLock" || (p.phase === "exit" && p.outcome === "SUCCESS")) {
        const grd = c.createRadialGradient(v.x, v.y, 0, v.x, v.y, 18);
        grd.addColorStop(0, color + "66");
        grd.addColorStop(1, color + "00");
        c.fillStyle = grd;
        c.beginPath();
        c.arc(v.x, v.y, 18, 0, Math.PI * 2);
        c.fill();
      }
      c.fillStyle = color;
      c.beginPath();
      c.arc(v.x, v.y, r, 0, Math.PI * 2);
      c.fill();
      c.globalAlpha = 1;
    }

    function draw(dt: number) {
      const g = geometry(width, height);
      c.clearRect(0, 0, width, height);
      drawStatic(g);

      const queueIndex = new Map<number, number>();
      sim.queue.forEach((p, i) => queueIndex.set(p.id, i));
      const all: Packet[] = [...sim.queue, ...sim.workerSlots.filter((p): p is Packet => p !== null), ...sim.exiting];
      const ease = dt > 0 ? 1 - Math.exp(-dt * 11) : 1;
      for (const p of all) {
        const [tx, ty, ta] = targetFor(p, g, sim, queueIndex);
        if (!p.view) {
          const [sx, sy] = g.at(ST.src.c, 0.5);
          p.view = { x: sx, y: sy, a: 0 };
        }
        p.view.x += (tx - p.view.x) * ease;
        p.view.y += (ty - p.view.y) * ease;
        p.view.a += (ta - p.view.a) * Math.min(1, ease * 1.4);
        drawPacket(p);
      }
    }

    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (runningRef.current && visible.current) {
        const sdt = dt * speedRef.current;
        // small fixed sub-steps keep the engine stable at any speed
        const steps = Math.max(1, Math.ceil(sdt / (1 / 60)));
        for (let i = 0; i < steps; i += 1) sim.step(sdt / steps);
        frameCb.current?.(sdt);
        draw(dt);
      }
      raf = requestAnimationFrame(loop);
    };

    const ro = new ResizeObserver(resize);
    ro.observe(box);
    const io = new IntersectionObserver(([entry]) => {
      visible.current = entry.isIntersecting;
      if (entry.isIntersecting) draw(0);
    });
    io.observe(box);
    resize();
    raf = requestAnimationFrame(loop);
    // Not running (reduced motion or paused): still repaint when something changes.
    const repaint = window.setInterval(() => {
      if (!runningRef.current && visible.current) draw(0);
    }, 250);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(repaint);
      ro.disconnect();
      io.disconnect();
    };
  }, [sim]);

  return (
    <div ref={wrap} className={className}>
      <canvas ref={canvas} role="img" aria-label={ariaLabel} className="block max-w-full" />
    </div>
  );
}
