import type { RunRequest } from "./demoApi";

/**
 * The scenarios offered in the live demo. Each is a normal workload-generator configuration.
 * `guarantee` is something that holds BY CONSTRUCTION for any outcome (it is checked against the database afterwards),
 * never a promise about specific numbers: the numbers come from the run.
 */
export interface Scenario {
  id: string;
  title: string;
  tag: string;
  duration: string;
  blurb: string;
  watch: string;
  guarantee: string;
  request: RunRequest;
}

export const SCENARIOS: Scenario[] = [
  {
    id: "race",
    title: "Finite-seat race",
    tag: "Correctness",
    duration: "under a second",
    blurb: "Forty students hit the same small section at the same instant.",
    watch: "How many registrations are stored, and the order in which requests were answered.",
    guarantee: "The section is never over capacity, and the client's success count equals the rows stored in MySQL.",
    request: { pattern: "burst", request_count: 40, contention: "hot", section_ids: [2, 1], hot_section_count: 1, seed: 42 },
  },
  {
    id: "steady",
    title: "Steady classroom",
    tag: "Baseline",
    duration: "about 6 s",
    blurb: "Ten requests a second, spread over both sections.",
    watch: "Queue depth staying shallow while seats fill.",
    guarantee: "Seats left always equal capacity minus stored registrations.",
    request: { pattern: "steady", rate: 10, request_count: 60, contention: "independent", section_ids: [1, 2], seed: 7 },
  },
  {
    id: "spike",
    title: "Spike and recovery",
    tag: "Load",
    duration: "about 9 s",
    blurb: "Calm, a two-second spike, then calm again.",
    watch: "Queue depth rising during the spike and draining afterwards; any refusals.",
    guarantee: "No matter how the queue behaves, the database invariants hold.",
    request: { pattern: "phases", phases: [[5, 3], [40, 2], [5, 4]], contention: "hot", section_ids: [1, 2], hot_section_count: 1, seed: 42 },
  },
  {
    id: "overload",
    title: "Overload",
    tag: "Load",
    duration: "under a second",
    blurb: "A hundred and twenty requests at once.",
    watch: "Requests beyond what the queue and workers can hold are refused immediately (HTTP 503).",
    guarantee: "Refused requests change nothing in the database.",
    request: { pattern: "burst", request_count: 120, contention: "hot", section_ids: [1, 2], hot_section_count: 1, seed: 42 },
  },
  {
    id: "dupes",
    title: "Duplicate clicks",
    tag: "Correctness",
    duration: "under a second",
    blurb: "Half the requests repeat a student who already asked.",
    watch: "Repeats answered 'already registered'.",
    guarantee: "No student is ever stored twice for one section (UNIQUE constraint).",
    request: { pattern: "burst", request_count: 30, contention: "hot", duplicate_fraction: 0.5, section_ids: [1, 2], hot_section_count: 1, seed: 11 },
  },
  {
    id: "closed",
    title: "Eight users, closed loop",
    tag: "Model",
    duration: "a few seconds",
    blurb: "Each virtual user waits for its answer, thinks, then asks again.",
    watch: "Arrivals following the server's speed (there is no fixed schedule to fall behind).",
    guarantee: "Closed-loop runs are reported without an open-loop validity claim.",
    request: { arrival_model: "closed", virtual_users: 8, think_time_min_s: 0.05, think_time_max_s: 0.15, request_count: 60, contention: "hot", section_ids: [1, 2], hot_section_count: 1, seed: 3 },
  },
];

/** What to say at each step. Plain text, shown in the presenter notes. */
export const TALK_TRACK = [
  { step: "1 · The system", say: "A FastAPI server runs a bounded queue, a worker pool and a database semaphore in front of one MySQL transaction. The badge shows which database it is really using." },
  { step: "2 · The data", say: "Two course sections with a few seats each. The four checks below are SQL queries on the live database, re-run continuously: they are the correctness rules, not a UI claim." },
  { step: "3 · The experiment", say: "Pick a scenario and run it. The real workload generator sends real HTTP requests to this same server. Watch the queue and the seats while it runs." },
  { step: "4 · The evidence", say: "The result file is the generator's own. The banner compares what the client was told with what MySQL actually stored, and the invariants are checked again." },
  { step: "5 · The tests", say: "One button runs the project's own pytest suite against a separate test database and streams each test as it finishes. Skipped tests show their reason; nothing is hidden." },
];
