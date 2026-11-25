/**
 * A small discrete-time SIMULATION of the ConcurrentReg request path, used for the landing-page visuals.
 * It models the mechanisms in app/os_layer and app/registration_service:
 *   arrival -> bounded queue (refuse when full) -> worker takes the head -> waits for a DB-semaphore permit
 *   -> waits for the section's row lock -> checks seats -> commits one seat, or answers "course full".
 * It is NOT a measurement and has no connection to the backend. The UI always labels it "Simulation".
 */

export type Phase = "queued" | "waitSem" | "waitLock" | "holdLock" | "exit";
export type Outcome = "SUCCESS" | "COURSE_FULL" | "QUEUE_FULL";

export interface SimParams {
  queueCapacity: number;
  workers: number;
  permits: number;
  sections: number; // independent sections, each with its own row lock and seats
  seatsPerSection: number;
  lockSeconds: number; // how long a transaction holds the row lock (simulated seconds)
}

export interface Packet {
  id: number;
  section: number;
  phase: Phase;
  outcome?: Outcome;
  worker: number; // -1 until a worker takes it
  remaining: number; // holdLock: seconds left
  exitT: number; // seconds since it left the system
  waitSince: number;
  // Render state owned by the canvas (the engine never reads it).
  view?: { x: number; y: number; a: number };
}

export interface Counters {
  offered: number;
  registered: number;
  full: number;
  refused: number;
}

/** Deterministic random numbers so a given seed always replays the same picture. */
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class PipelineSim {
  params: SimParams;
  t = 0;
  counters: Counters = { offered: 0, registered: 0, full: 0, refused: 0 };
  queue: Packet[] = [];
  workerSlots: (Packet | null)[];
  semHolders = 0;
  lockHolder: (Packet | null)[];
  lockQueue: Packet[][];
  seatsLeft: number[];
  exiting: Packet[] = [];
  maxQueueDepth = 0;
  private schedule: number[] = [];
  private next = 0;
  private nextId = 1;
  private rng: () => number;
  /** Probability that a new request targets section 0 (the "hot" one). 1 = everything on one hot section. */
  hotShare = 1;

  constructor(params: SimParams, seed = 1) {
    this.params = params;
    this.rng = mulberry32(seed);
    this.workerSlots = new Array(params.workers).fill(null);
    this.lockHolder = new Array(params.sections).fill(null);
    this.lockQueue = Array.from({ length: params.sections }, () => []);
    this.seatsLeft = new Array(params.sections).fill(params.seatsPerSection);
  }

  /** Release these arrival times (simulated seconds after `startAt`). Replaces any earlier schedule. */
  loadSchedule(offsets: number[], startAt = this.t) {
    this.schedule = offsets.map((o) => o + startAt);
    this.next = 0;
  }

  get scheduleDone() {
    return this.next >= this.schedule.length;
  }

  get inFlight() {
    return this.queue.length + this.workerSlots.filter(Boolean).length;
  }

  get idle() {
    return this.scheduleDone && this.inFlight === 0;
  }

  resetSeats() {
    this.seatsLeft.fill(this.params.seatsPerSection);
    this.counters = { offered: 0, registered: 0, full: 0, refused: 0 };
    this.maxQueueDepth = 0;
  }

  private pickSection() {
    if (this.params.sections === 1) return 0;
    if (this.rng() < this.hotShare) return 0;
    return 1 + Math.floor(this.rng() * (this.params.sections - 1));
  }

  private arrive() {
    const packet: Packet = { id: this.nextId++, section: this.pickSection(), phase: "queued", worker: -1, remaining: 0, exitT: 0, waitSince: this.t };
    this.counters.offered += 1;
    if (this.queue.length >= this.params.queueCapacity) {
      packet.phase = "exit";
      packet.outcome = "QUEUE_FULL";
      this.counters.refused += 1;
      this.exiting.push(packet);
      return;
    }
    this.queue.push(packet);
    this.maxQueueDepth = Math.max(this.maxQueueDepth, this.queue.length);
  }

  step(dt: number) {
    this.t += dt;

    while (this.next < this.schedule.length && this.schedule[this.next] <= this.t) {
      this.next += 1;
      this.arrive();
    }

    // 1. Idle workers take requests from the head of the queue (first in, first out).
    for (let w = 0; w < this.workerSlots.length; w += 1) {
      if (this.workerSlots[w] === null && this.queue.length > 0) {
        const packet = this.queue.shift()!;
        packet.worker = w;
        packet.phase = "waitSem";
        packet.waitSince = this.t;
        this.workerSlots[w] = packet;
      }
    }

    // 2. Workers waiting for a permit, longest waiting first.
    const waiting = this.workerSlots.filter((p): p is Packet => p !== null && p.phase === "waitSem").sort((a, b) => a.waitSince - b.waitSince);
    for (const packet of waiting) {
      if (this.semHolders >= this.params.permits) break;
      this.semHolders += 1;
      packet.phase = "waitLock";
      packet.waitSince = this.t;
      this.lockQueue[packet.section].push(packet);
    }

    // 3. Each section's row lock is held by one transaction at a time.
    for (let s = 0; s < this.params.sections; s += 1) {
      if (this.lockHolder[s] === null && this.lockQueue[s].length > 0) {
        const packet = this.lockQueue[s].shift()!;
        packet.phase = "holdLock";
        packet.remaining = this.params.lockSeconds;
        this.lockHolder[s] = packet;
      }
    }

    // 4. Transactions holding a lock finish: the seat check happens while the lock is held.
    for (let s = 0; s < this.params.sections; s += 1) {
      const packet = this.lockHolder[s];
      if (!packet) continue;
      packet.remaining -= dt;
      if (packet.remaining > 0) continue;
      if (this.seatsLeft[s] > 0) {
        this.seatsLeft[s] -= 1;
        packet.outcome = "SUCCESS";
        this.counters.registered += 1;
      } else {
        packet.outcome = "COURSE_FULL";
        this.counters.full += 1;
      }
      packet.phase = "exit";
      packet.exitT = 0;
      this.lockHolder[s] = null;
      this.semHolders -= 1;
      this.workerSlots[packet.worker] = null;
      this.exiting.push(packet);
    }

    for (const packet of this.exiting) packet.exitT += dt;
    this.exiting = this.exiting.filter((p) => p.exitT < 1.4);
  }

  /** Checks the rules that must always hold. Returns problems (empty = fine). Used by the unit tests. */
  invariants(): string[] {
    const p: string[] = [];
    const seatsTaken = this.params.seatsPerSection * this.params.sections - this.seatsLeft.reduce((a, b) => a + b, 0);
    if (this.counters.registered !== seatsTaken) p.push("registered count differs from seats taken");
    if (this.seatsLeft.some((s) => s < 0)) p.push("a section went below zero seats");
    if (this.semHolders < 0 || this.semHolders > this.params.permits) p.push("semaphore holders outside 0..permits");
    if (this.queue.length > this.params.queueCapacity) p.push("queue grew beyond its capacity");
    const busy = this.workerSlots.filter(Boolean).length;
    if (busy > this.params.workers) p.push("more busy workers than workers");
    const inDb = this.workerSlots.filter((x) => x && (x.phase === "waitLock" || x.phase === "holdLock")).length;
    if (inDb !== this.semHolders) p.push("semaphore holders differ from workers inside the database section");
    if (this.lockHolder.some((h, i) => h && h.section !== i)) p.push("a lock is held by a request for another section");
    const finished = this.counters.registered + this.counters.full + this.counters.refused;
    if (this.counters.offered !== finished + this.inFlight) p.push("offered != finished + in flight");
    return p;
  }
}
