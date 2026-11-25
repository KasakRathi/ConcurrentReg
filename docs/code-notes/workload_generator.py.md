# workload/workload_generator.py

## 1. Purpose
A command-line tool that sends a controlled, repeatable stream of registration requests to
`POST /registrations` and records what happened to each one. It is an **experimental instrument**:
what it reports must be trustworthy before any control mechanism is compared with another.

## 2. Responsibilities
- Describe a workload with explicit settings (`WorkloadConfig`) and reject invalid ones.
- Generate the request list `(student, section, intended arrival time)` from a seed.
- Send the requests in one of two arrival models (open loop or closed loop, section 6).
- Measure, for every request, when it was *meant* to arrive, when it was *really* sent, and the latency measured from each of those two moments.
- Say plainly whether an open-loop run kept to its schedule (`valid_open_loop`) and why not if it did not.
- Write one JSON file (configuration, generated requests, per-request results, summary, reproducibility information) and read it back to check nothing is missing.

## 3. What it does NOT do
- It never opens the database and never changes seats. All state changes happen inside the backend, through the API. The database must already be seeded (`python -m app.seed`).
- No admission control, queues, semaphores, retries, IASL or AI/ML. Its thread pool only creates **client** traffic; it is not the server-side worker pool.
- It imports nothing from `app/`, so the system under test and the instrument stay separate.
- It does not create students or sections (the seed has 10 students and 2 sections; dataset scaling is later work).
- Its workloads are synthetic. They are **not** claimed to represent real university traffic.

## 4. Functions/classes
Configuration and schedules
- **`WorkloadConfig`** — all settings. Defaults are small demonstration values, not research parameters.
- **`Request`** — one logical request: ids, `planned_offset_s` (the *intended arrival*; `None` in closed loop), and for closed loop `user` and `think_time_before_s`.
- **`validate_config`, `validate_phases`** — reject impossible values (non-integer or negative seed, rate or duration ≤ 0, NaN/infinity, too many phases or requests, in-flight cap outside 1..1000, think time min > max, phases combined with closed loop, ...). Nothing is silently defaulted.
- **`phase_plan(config)`, `planned_request_count`, `arrival_offsets(config)`** — the intended arrival times. `burst`: all 0. `steady`: `index / rate`. `ramp`: the rate grows in equal steps. `phases`: see section 7.
- **`plan_think_times(config, count)`** — closed-loop think times from their own seeded random stream.
- **`generate_requests(config)`** — the request list. Targets use `random.Random(seed)` exactly as before, so a seed picks the same students and sections whatever the arrival model.

Execution
- **`send_request(client, endpoint, request, experiment_start)`** — sends one request and returns its record; never raises. It never sends *early*: if called before the intended time it waits.
- **`dispatch_open_loop`** — the open-loop dispatcher (section 6). **`dispatch_closed_loop`** — the virtual users.
- **`run_workload(requests, config, client=None, stop_event=None)`** — runs everything; returns `(results, elapsed_seconds)`, one record per request. `stop_event` (or Ctrl-C) ends the run early; unsent requests get a `NOT_DISPATCHED` record.
- **`undispatched_record`** — the record of a request that was never sent.

Results
- **`summarize_results(results, elapsed_seconds, config=None)`** — totals, categories, throughput, both latency summaries, plus `open_loop` or `closed_loop` (whichever applies; the other is `null`). Without `config` it gives only the older fields.
- **`summarize_open_loop`, `summarize_closed_loop`, `lateness_stats`, `latency_stats`, `rate_between`, `percentile`** — pure functions of the records, so they are tested with exact numbers.
- **`build_run_info`, `generator_revision`** — the reproducibility block. **`save_results`, `check_saved_results`** — write the file and verify it. **`main`** — the CLI.
- Result categories: `SUCCESS`, `DUPLICATE`, `COURSE_FULL`, `QUEUE_FULL`, `CLIENT_ERROR`, `SERVER_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `UNKNOWN`, and `NOT_DISPATCHED` (the run stopped before the request was sent). `QUEUE_FULL` (503 "Request queue is full") is provisional, as in the Master MD.

## 5. Important variables
- `arrival_model` — `open` or `closed`. `pattern` — open-loop timing: `steady`, `burst`, `ramp`, `phases`. `contention` — which sections are targeted. They are independent choices.
- `concurrency` — for open loop, the **cap on requests in flight**. Each in-flight request costs one thread and one connection, so it is limited to 1..1000 (default 100). It is not a claim about load.
- `lateness_tolerance_ms` — open-loop validity tolerance (default 50 ms, a demonstration value).
- `virtual_users`, `think_time_min_s`, `think_time_max_s` — closed loop.
- `planned_offset_s` / `intended_offset_s` — intended arrival, seconds after the run started. `sent_offset_s` (same as `start_offset_s`) — when it was actually sent. `end_offset_s` — when the response (or failure) arrived. All three are monotonic-clock offsets.
- `intended_at`, `sent_at` (same as `started_at`) — wall-clock strings for people to read. Never used for durations.
- `lateness_ms` = `(sent_offset − intended_offset) × 1000`. `send_time_latency_ms` (also `latency_ms`) = `(end − sent) × 1000`. `intended_arrival_latency_ms` = `(end − intended) × 1000` = lateness + send-time latency.
- `cap_was_full`, `slot_wait_ms` — set when the in-flight cap held a request back, and for how long; they explain *why* a request was late.
- `user`, `think_time_before_s`, `previous_end_offset_s` — closed loop: whose request, how long that user thought, and when that user's previous response arrived.

## 6. Execution flow and the two arrival models
`parse_args → config_from_args → validate_config → generate_requests → run_workload → summarize_results → save_results (+ run information) → check_saved_results → print summary`.

**Open loop** (default). Every request has an intended arrival time fixed in advance. The dispatcher waits until that moment, takes a free in-flight slot, and hands the request to a worker thread. Responses never change the schedule, **and the intended times are never moved**. If all slots are busy when a request is due, the dispatcher waits for one: the request goes out late, and that shows up as `lateness_ms` (and `cap_was_full`). Nothing piles up without limit: at most `concurrency` requests are submitted and unfinished. A saturated generator is therefore *visible*, not hidden.

**Closed loop.** `virtual_users` users. Each user thinks, sends its request, **waits for the response** (or the timeout), thinks again, and so on. Requests are dealt to users in turn (request 0 to user 0, request 1 to user 1, ...). There are no intended arrival times, so there is no lateness; arrivals depend on how fast the server answers. Closed-loop results are reported under `closed_loop`, never mixed with `open_loop`. (The open-loop mode is *not* closed-loop just because a full in-flight cap delays it.)

## 7. Multi-phase schedules
`pattern=phases` with `phases=[[rate_per_s, duration_s], ...]`, on the command line `--phases "10:5,100:2,10:10"`. That example (10/s for 5 s, a 100/s burst for 2 s, then 10/s for 10 s) is only an example, not a recommended value.
Phase *i* covers the half-open interval `[start, end)`. It sends `ceil(rate × duration)` requests at `start + k/rate`, so none lands on `end`, and the next phase starts exactly at `end`. The total number of requests comes from the phases (`--requests` is ignored). `run.schedule.phases` in the result file lists each phase with its start, end and request count.

## 8. Rates and the validity rule
Both rates use the same formula, `(events − 1) / (last − first)`:
- `offered_rate_per_s` — applied to the **intended** arrival times.
- `achieved_dispatch_rate_per_s` — applied to the **actual send** times of the dispatched requests.
- `achieved_to_offered_ratio` — achieved ÷ offered. Both are `null` for fewer than two events or when all events are at one instant (a pure burst).
- `completed_requests_per_second` (older field) is a different thing: sent requests ÷ the whole run, from start to the last response.

`valid_open_loop` is **true only if** (1) every intended request was dispatched, and (2) no request was sent more than `lateness_tolerance_ms` after its intended time (exactly the tolerance still counts as on time). Otherwise it is false and `invalid_reasons` says why. The measurements behind the flag are always present: `lateness_ms` (mean, median, max, and p95/p99 only when there are at least 20/100 samples), `requests_over_tolerance`, `requests_that_found_the_cap_full`, `errors` (timeouts, connection errors, server/client errors, unclassified), and `intended_requests` / `dispatched_requests` / `undispatched_requests`.
The command line prints a warning for an invalid run but still exits 0, as before; read the flag in the result file.

## 9. Reproducibility
- **Reproducible from the seed and configuration:** the intended schedule (and phase boundaries), the think times, the user assignment, and which student and section each request targets. They are saved in `generated_requests` and `run.schedule`.
- **Not reproducible:** operating-system thread scheduling, network timing and server response times. So lateness, latency and which request wins a contended seat differ between runs. The client and the server on one machine also compete for the same CPU.
- The result file's `run` block records: generator version and git revision (`git describe --always --dirty`, or null), arrival model, seed, schedule, target rate or virtual users, think-time settings, in-flight cap, timeout, tolerance, start and end wall-clock times, and these two statements about what is and is not reproducible.
- The database must be re-seeded between runs that are to be compared.

## 10. Error handling
- **Request level** (timeout, connection error, 4xx/5xx, unexpected answer): recorded as that request's result, with its timing fields; the run continues. Timeouts and connection errors count under `open_loop.errors`.
- **Run level:** invalid configuration → exit 2 before anything is sent; result file fails the read-back check → exit 1; every request got `CONNECTION_ERROR` → results are saved, then exit 1.
- **Interrupted run** (stop event or Ctrl-C): requests not sent get `NOT_DISPATCHED`, the run is invalid for open-loop evaluation, and the counts still add up.
- No retries, ever: they would change the offered workload.

## 11. Measurement definitions and limits
- Durations use `time.perf_counter()` (monotonic), so a change of the system clock cannot distort them.
- Latency statistics (average, min, max, p50, p95, p99, nearest rank) use only requests that received an HTTP response; timeouts and connection errors have no real response time.
- Limit: lateness is measured at the moment of sending, so it includes OS thread start-up (microseconds to milliseconds). The tolerance should be well above that. The generator does not check its own CPU use.
- Limit: arrivals are deterministic (evenly spaced inside a phase). Random (e.g. Poisson) arrivals are not implemented.

## 12. Testing
- `tests/test_workload_generator.py` (45 tests, unchanged) — targeting, seed, steady/burst/ramp timing, validation, classification, timeouts, aggregates.
- `tests/test_workload_arrival_models.py` (64 tests) — see its own note: exact schedules and phases, lateness and the two latencies, rate denominators, the validity rule, a deliberately saturated generator, the cap, closed-loop waiting and think times, reproducibility, incomplete runs, the result file and the CLI.
- `tests/test_workload_live.py` — real in-process backend: hot workload, overlap, CLI file and seed reproducibility.
