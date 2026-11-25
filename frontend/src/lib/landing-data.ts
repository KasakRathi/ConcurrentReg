/**
 * Content for the landing page that is not simple prose: code excerpts and file notes.
 * Every excerpt is an exact, contiguous copy of lines from the repository file named in `path`.
 * landing-data.test.ts re-reads those files and fails if an excerpt no longer matches.
 */
import type { WorkloadConfig } from "./types";

/** Presets of the "Run an experiment" section: each is a patch of the generator's own defaults. */
export const PRESET_PATCHES: { id: string; label: string; patch: Partial<WorkloadConfig> }[] = [
  { id: "steady", label: "Steady", patch: { pattern: "steady", rate: 10, request_count: 100 } },
  { id: "burst", label: "Burst", patch: { pattern: "burst", request_count: 50 } },
  { id: "ramp", label: "Ramp-up", patch: { pattern: "ramp", rate: 40, ramp_stages: 4, request_count: 160 } },
  { id: "phases", label: "Phases", patch: { pattern: "phases", phases: [[10, 5], [100, 2], [10, 10]] } },
  { id: "closed", label: "Closed loop", patch: { arrival_model: "closed", virtual_users: 10, think_time_min_s: 0.1, think_time_max_s: 0.3, request_count: 100 } },
  { id: "hotspot", label: "Hotspot", patch: { pattern: "burst", contention: "hot", request_count: 50 } },
  { id: "spread", label: "Spread", patch: { pattern: "burst", contention: "independent", request_count: 50 } },
  { id: "mixed", label: "Mixed", patch: { pattern: "burst", contention: "mixed", hot_fraction: 0.7, request_count: 50 } },
  { id: "dupes", label: "Duplicates", patch: { pattern: "burst", duplicate_fraction: 0.3, request_count: 50 } },
  { id: "seed", label: "New seed", patch: { pattern: "burst", seed: 7, request_count: 50 } },
  { id: "timeout", label: "1 s timeout", patch: { pattern: "burst", timeout_seconds: 1, request_count: 50 } },
  { id: "cap", label: "Wide cap", patch: { pattern: "burst", concurrency: 500, request_count: 500 } },
];

/** Server-side settings variants (environment variables). Experimental parameters, not recommendations. */
export const SERVER_VARIANTS = [
  { id: "default", label: "Defaults", q: 16, w: 4, p: 2 },
  { id: "small", label: "Small queue", q: 4, w: 2, p: 1 },
  { id: "wide", label: "Wide pool", q: 32, w: 8, p: 4 },
];

export interface CodeFile {
  id: string;
  name: string;
  path: string;
  language: "python";
  code: string;
  title: string;
  note: string;
  points: string[];
}

export const CODE_FILES: CodeFile[] = [
  {
    id: "generator",
    name: "workload_generator.py",
    path: "workload/workload_generator.py",
    language: "python",
    code: `def arrival_offsets(config):
    """Intended arrival time of each request, in seconds after the experiment starts."""
    count = config.request_count
    if config.pattern == "phases":
        return [phase["start_s"] + k / phase["rate_per_s"]
                for phase in phase_plan(config) for k in range(phase["requests"])]
    if config.pattern == "burst":
        return [0.0] * count
    if config.pattern == "steady":
        return [index / config.rate for index in range(count)]

    # ramp: the rate grows in equal steps; the last stage runs at config.rate.
    offsets = []
    time_so_far = 0.0
    for index in range(count):
        stage = index * config.ramp_stages // count          # 0 .. ramp_stages-1
        stage_rate = config.rate * (stage + 1) / config.ramp_stages
        offsets.append(time_so_far)
        time_so_far += 1 / stage_rate
    return offsets`,
    title: "The schedule is fixed in advance",
    note: "In an open-loop run every request has an intended arrival time that no response can change.",
    points: ["Same seed and settings give the same schedule.", "A late dispatch is measured as lateness, never hidden.", "The dashboard re-computes this schedule to preview it."],
  },
  {
    id: "queue",
    name: "bounded_queue.py",
    path: "app/os_layer/bounded_queue.py",
    language: "python",
    code: `    def try_put(self, item):
        """Add \`item\` if there is room. Never waits. Returns ADDED, FULL or SHUT_DOWN."""
        try:
            self.put_nowait(item)
        except queue.Full:
            with self._refusal_lock:
                self.rejected_full += 1
            return FULL
        except queue.ShutDown:
            with self._refusal_lock:
                self.rejected_shut_down += 1
            return SHUT_DOWN
        return ADDED`,
    title: "A full queue refuses, it does not wait",
    note: "The queue's bound comes from Python's own thread-safe queue, so it cannot be exceeded.",
    points: ["Order is first in, first out.", "Refusals are counted: rejected_queue_full in /os-layer/status.", "The HTTP answer for a full queue (503) is provisional."],
  },
  {
    id: "semaphore",
    name: "db_semaphore.py",
    path: "app/os_layer/db_semaphore.py",
    language: "python",
    code: `    @contextmanager
    def hold(self):
        """Wait for a permit, run the protected block, always give the permit back.

        Yields how many seconds this caller waited for the permit.
        """
        waited = self._acquire()
        try:
            yield waited
        finally:
            self._release()`,
    title: "A permit is always given back",
    note: "At most DB_SEMAPHORE_PERMITS workers are inside the database section at once.",
    points: ["The wait time is measured and counted.", "Correctness never depends on it: the database decides.", "It is an experimental parameter, not a recommendation."],
  },
  {
    id: "transaction",
    name: "registration_service.py",
    path: "app/registration_service.py",
    language: "python",
    code: `    if is_already_registered(db, student.id, section_id):
        db.rollback()
        return RegistrationResult(DUPLICATE, "Student is already registered for this course section")

    if section.available_seats <= 0:
        db.rollback()
        return RegistrationResult(FULL, "Course section is full")

    try:
        db.add(Registration(student_id=student.id, section_id=section_id))
        decrease_available_seats(db, section)
        db.commit()`,
    title: "Checked and committed under the row lock",
    note: "By this point the section row is locked with SELECT ... FOR UPDATE, so the seat check and the decrease cannot interleave with another request.",
    points: ["One insert and one decrease, one commit.", "UNIQUE(student_id, section_id) is the last line of defence.", "Every path ends in exactly one commit or rollback."],
  },
];
