# IASL Implementation Audit (Stage 0)

| | |
|---|---|
| **Status** | Stage 0 complete. **No IASL code has been written.** Awaiting review before Stage 1. |
| **Audited** | 2026-11-25, the repository root |
| **Method** | Every file under `app/`, `workload/`, `tests/`, `scripts/`, `docs/`, plus the frontend's API layer, was read. A repository-wide search for `iasl`, `admission`, `adaptive`, `feedback loop`, `hysteresis`, `cooldown` was run. The existing test suite was executed on both MySQL and SQLite to get a baseline. |
| **Not changed** | Nothing in the repository was modified by this audit except creating this file. (Separately, earlier in this session the frontend's missing `vite.config.ts` was recreated and dependencies were installed; that is unrelated to IASL.) |

**Status vocabulary used throughout**

| Label | Meaning |
|---|---|
| **Implemented** | Exists in the repository and was read in the cited file. |
| **Partial** | Exists but does not cover what IASL needs; the gap is stated. |
| **Not implemented** | Searched for; not present. |
| **Proposed** | A suggestion in this document. Nothing proposed exists yet. |

---

## 1. Executive summary

1. **There is no IASL, no admission controller, no adaptive control and no feedback loop anywhere in the repository.** The only trace is one comment marking where an admission controller should go (`app/os_layer/request_pipeline.py:94-96`) and many "not implemented" notes in the docs and frontend. The README itself lists IASL under "Intentionally NOT implemented yet".
2. **The OS layer is sound and well instrumented for *counters*, but not for *latency distributions*.** `OSConcurrencyLayer.snapshot()` (`request_pipeline.py:149`) exposes queue, worker and semaphore counters. It has no percentiles, no per-outcome counters, no timeout counter, no database-latency aggregate. p50/p95/p99 exist only on the **client** side, in the workload generator.
3. **Of the three parameters IASL could tune, none can be changed at run time with the current classes.** Queue capacity, worker count and semaphore permits are fixed at construction (`BoundedRequestQueue.__init__`, `WorkerPool.__init__`, `DbSemaphore.__init__`). The only runtime path is `POST /demo/os-layer`, which **replaces the whole layer** (`app/demo_api.py:348-360`). Consequently the safest, most natural control knob is a **new admission limit placed in front of the queue**, which is exactly what the code comment anticipates.
4. **Several existing tests and tools constrain how IASL may be added** (Section 9): one test asserts the exact shape of the OS-layer config dict; the workload generator classifies any unfamiliar 5xx as `SERVER_ERROR`; four backend files are excerpted verbatim by a frontend test. These are the main integration conflicts.
5. **Baseline is green:** 188 passed on MySQL 8.4.11/InnoDB; 169 passed + 19 skipped on SQLite (Section 10).
6. **The repository is not under version control** (`git status` fails). There is no way to diff or roll back. Recommend `git init` plus a baseline commit, or a copy of the tree, before Stage 2.

---

## 2. Existing architecture (as it actually is)

```
Client (workload generator, external process)
   |  HTTP POST /registrations
   v
FastAPI handler  app/main.py:32  create_registration()          [async, event-loop thread]
   |  layer.submit(student_id, section_id)  -> Future            [sync call, never waits]
   v
OSConcurrencyLayer.submit()  app/os_layer/request_pipeline.py:78
   |  (admission comment only, lines 94-96)
   v
BoundedRequestQueue.try_put()  bounded_queue.py:32              [queue.Queue(maxsize), FIFO]
   v
WorkerPool._worker_loop()  worker_pool.py:49                    [N daemon threads]
   v
OSConcurrencyLayer._process()  request_pipeline.py:110
   v
DbSemaphore.hold()  db_semaphore.py:25                          [threading.BoundedSemaphore]
   v
register_student()  app/registration_service.py:34              [one transaction, SELECT ... FOR UPDATE]
   v
MySQL / InnoDB   (CHECK ck_seats_in_range, UNIQUE uq_student_section)
```

Differences from the conceptual diagram in the brief:

| Brief's box | Repository reality | Status |
|---|---|---|
| Workload Generator | `workload/workload_generator.py`, external HTTP client | Implemented |
| Request Filtering / Classification | No such component. The handler passes every request on; only Pydantic validation (`app/schemas.py`) runs first. | **Not implemented** |
| IASL (5 modules) | Nothing | **Not implemented** |
| Admission Controller | Comment only, `request_pipeline.py:94-96` | **Not implemented** |
| Bounded Queue | `app/os_layer/bounded_queue.py` | Implemented |
| Worker Pool | `app/os_layer/worker_pool.py` | Implemented (fixed size) |
| DB Semaphore | `app/os_layer/db_semaphore.py` | Implemented (fixed permits) |
| Database layer | `app/database.py`, `app/registration_service.py`, `app/models.py` | Implemented |
| MySQL/InnoDB | Docker `mysql:8.4` via `scripts/demo_db.sh`; verified 8.4.11 | Implemented |

The process model is **one uvicorn process, one event loop, many threads** (`scripts/start_demo.sh` starts a single `uvicorn app.main:app`). All counters are per-process. Running several uvicorn workers would give each its own independent layer and counters; this is not supported or tested, and IASL's design must assume a single process.

---

## 3. Component inventory

### 3.1 Existing components and responsibilities

| Component | File / symbol | Responsibility | Status |
|---|---|---|---|
| HTTP entry | `app/main.py` `create_registration` (l.32), `os_layer_status` (l.42), `create_app` (l.47) | Validate body, call `submit`, map result code to HTTP status via `HTTP_STATUS` (l.15), build app, start/stop layer in `lifespan` (l.51) | Implemented |
| Layer config | `app/os_layer/layer_config.py` `OSLayerConfig` | Frozen dataclass: `queue_capacity`, `worker_count`, `db_semaphore_permits`; validates whole numbers ≥ 1; `from_environment()` | Implemented |
| Pipeline | `app/os_layer/request_pipeline.py` `OSConcurrencyLayer` | Owns queue, semaphore, pool; `submit`, `_process`, `snapshot`, structured logging | Implemented |
| Queue | `bounded_queue.py` `BoundedRequestQueue(queue.Queue)` | FIFO, `try_put` returns `ADDED/FULL/SHUT_DOWN`; counts `accepted`, `max_depth`, `rejected_full`, `rejected_shut_down` | Implemented |
| Workers | `worker_pool.py` `WorkerPool` | Fixed list of daemon threads; counts `active`, `max_active`, `jobs_started`, `jobs_finished`, `unexpected_errors`; worker survives handler exceptions | Implemented |
| Semaphore | `db_semaphore.py` `DbSemaphore` | `BoundedSemaphore`; counts `in_critical_section`, `waiting`, `acquisitions`, `wait_total_s`, `wait_max_s` and maxima | Implemented |
| Registration core | `app/registration_service.py` `register_student`, `_register`, `lock_section` | One transaction: student lookup, `SELECT … FOR UPDATE` on section, duplicate check, seat check, insert + decrement, single commit/rollback | Implemented |
| Schema | `app/models.py` | `ck_seats_in_range` CHECK, `uq_student_section` UNIQUE, FKs | Implemented |
| DB engine | `app/database.py` | `create_engine(..., pool_size=20, max_overflow=40, pool_pre_ping=True)`; `DATABASE_URL` required | Implemented |
| Demo controls | `app/demo_api.py` | Run generator against the server, reset DB, list/read results, run pytest, **replace the OS layer** | Implemented (gated by `CREG_DEMO_CONTROLS=1`) |
| Test runner | `app/verification.py` | Runs pytest from the dashboard, refuses if test DB = app DB | Implemented |
| Workload generator | `workload/workload_generator.py` (842 lines) | Open/closed loop clients, seeded schedules, result JSON, client-side p50/p95/p99 | Implemented |
| Frontend | `frontend/` | Landing + dashboard; polls `GET /os-layer/status`; demo page drives `/demo/*` | Implemented |

### 3.2 Concurrency mechanisms in use

| Mechanism | Where | Notes |
|---|---|---|
| Row lock `SELECT … FOR UPDATE` | `registration_service.lock_section` | **Source of correctness.** SQLite ignores it (README). |
| DB CHECK + UNIQUE | `models.py` | Last line of defence, independent of the app. |
| `queue.Queue(maxsize=…)` | `BoundedRequestQueue` | Bound enforced by stdlib. Uses `queue.ShutDown` (Python ≥ 3.13). |
| `threading.BoundedSemaphore` | `DbSemaphore` | Raises if a permit is returned twice. |
| `Future` + `asyncio.wrap_future` | `submit()` / `create_registration` | Event loop awaits; workers fulfil the Future. |
| Per-job `SessionLocal()` | `_run_registration` | Sessions never shared across threads. |
| Locks around counters | `WorkerPool._lock`, `DbSemaphore._lock`, `OSConcurrencyLayer._lock`, `BoundedRequestQueue._refusal_lock` | See 4.3 for consistency caveats. |

---

## 4. Existing metrics, logging and configuration

### 4.1 What `GET /os-layer/status` provides today (`OSConcurrencyLayer.snapshot`, l.149-191)

| Group | Fields | Kind |
|---|---|---|
| `config` | `queue_capacity`, `worker_count`, `db_semaphore_permits` | static |
| `queue` | `capacity`, `depth`, `max_depth`, `accepted`, `rejected_queue_full`, `rejected_shutting_down` | `depth` instantaneous; rest cumulative since layer start (`max_depth` is a high-water mark) |
| `queue_wait` | `jobs_dequeued`, `total_s`, `max_s`, `average_s` | cumulative; average is **since start**, not recent |
| `workers` | `configured`, `alive`, `active`, `max_active`, `jobs_started`, `jobs_finished`, `unexpected_errors` | `active`/`alive` instantaneous; rest cumulative |
| `db_semaphore` | `permits`, `in_critical_section`, `max_in_critical_section`, `waiting`, `max_waiting`, `acquisitions`, `wait_total_s`, `wait_max_s` | `in_critical_section`/`waiting` instantaneous; rest cumulative |

### 4.2 Mapping IASL's requested metrics to what exists

| Requested metric (brief §4A) | Available now? | Source / gap |
|---|---|---|
| Total incoming requests | **Derivable** | `accepted + rejected_queue_full + rejected_shutting_down` (no direct counter) |
| Accepted requests | Implemented | `queue.accepted` (means *entered the queue*, not "will succeed") |
| Rejected requests | Implemented | `rejected_queue_full`, `rejected_shutting_down` |
| Completed registrations / failed registrations | **Not implemented in the layer** | `workers.jobs_finished` counts every job regardless of outcome. Per-outcome (`SUCCESS`, `FULL`, `DUPLICATE`, `ERROR`…) exists only in log lines (`os_layer_request.result`) and in the client's result file. |
| Timed-out requests | **Not implemented** | There is no server-side request timeout (README "Limitations"). The generator's `TIMEOUT` is client-side only. |
| Requests per second | **Not implemented** | Must be computed from deltas of cumulative counters. |
| Request processing latency | **Partial** | Only in logs (`worker_total_ms`, `db_section_ms`) and as `queue_wait.average_s` / `wait_*` since start. No in-memory distribution. |
| Queue depth / capacity / utilisation | Implemented / derivable | `depth`, `capacity`; utilisation = depth/capacity |
| Queue waiting time | **Partial** | cumulative total/max/avg only; no recent window |
| Queue rejection count | Implemented | `rejected_queue_full` |
| Worker count / active / idle / utilisation | Implemented / derivable | `configured`, `alive`, `active`; idle = alive − active |
| Worker processing time | **Partial** | logs only (`worker_total_ms`) |
| Active DB operations / available permits / utilisation | Implemented / derivable | `in_critical_section`, `permits − in_critical_section` |
| DB operation latency | **Partial** | logs only (`db_section_ms`). Note this includes **row-lock wait time**, not just execution time. |
| DB timeout count | **Not implemented** | No DB-level timeout is configured. |
| DB errors | **Partial** | `ERROR` result code exists (`register_student` catches `SQLAlchemyError`); no counter. `workers.unexpected_errors` counts only exceptions that escape the handler. |
| Lock-wait metrics | **Not available to the application** | Only obtainable via `information_schema.innodb_trx` (see below). **Do not invent this.** |
| Throughput | Derivable | delta of `jobs_finished` over time |
| p50 / p95 / p99 latency | **Not implemented server-side** | Only client-side: `latency_stats()` / `percentile()` in `workload_generator.py` (l.473-480) |
| Error rate / timeout rate | Not implemented | Needs the per-outcome counters above |

**Lock waits.** `tests/conftest.py:count_innodb_lock_waits()` reads `information_schema.innodb_trx WHERE trx_state='LOCK WAIT'`. It needs the MySQL `PROCESS` privilege (granted to `creg` in `scripts/demo_db.sh`; optional in the README), InnoDB serves a **cached** result if polled faster than ~0.1 s (comment in the same function), and it does not exist on SQLite. So lock-wait count is *conditionally* obtainable on MySQL only and is **not** part of any application code path today. It should be treated as optional/unavailable, never as a required IASL input.

### 4.3 Consistency caveats of the existing metrics (relevant to a sampler)

* `snapshot()` reads fields without a global lock. Individual fields are consistent; **cross-field consistency is not guaranteed** (e.g. `depth` and `accepted` can be from slightly different instants). Acceptable for coarse control; must not be used for exact invariants.
* `queue.accepted` increments under the queue's internal mutex (`_put`); `rejected_full` under a separate lock. Counters are monotonic within one layer instance.
* **Cancelled-in-queue jobs** (client disconnected before a worker started) return early in `_process` (l.112-113) *before* `_note_queue_wait`, but `WorkerPool._run_one` still counts them in `jobs_finished`. So `jobs_finished − queue_wait.jobs_dequeued` can exceed zero without any error. Test: `test_request_cancelled_while_queued_is_skipped`. A rate computed from `jobs_finished` would count a skipped job as throughput.
* **Counters reset to zero when the layer is replaced** (`POST /demo/os-layer`). The frontend already handles this ("marks a restart when counters go down", `hooks/monitor.tsx`); a Python sampler must do the same.
* `max_depth`, `max_active`, `max_waiting` are lifetime high-water marks and **cannot be windowed**; unsuitable as control signals.

### 4.4 Logging (Implemented)

Python `logging`, configured once by `logging.basicConfig(level=INFO)` in `app/main.py:13`. Loggers: `os_layer`, `registration`. Format: one `json.dumps` object per message with an `event` field:

| Event | Emitted by | Key fields |
|---|---|---|
| `os_layer_started` / `os_layer_stopped` | `start()` / `stop()` | config, final counters |
| `os_layer_request` | `_log_request` | `request_id`, `queue_depth_at_arrival`, `queue_wait_ms`, `semaphore_wait_ms`, `db_section_ms`, `worker_total_ms`, `result`, `error`, config |
| `os_layer_rejected` | `_log_rejection` | `reason`, `queue_depth_at_arrival`, config |
| `registration` | `register_student` | `request_id`, `result`, `error`, `duration_ms` |

Convention for IASL (Proposed): a new logger name (e.g. `iasl`) with the same `json.dumps` + `event` pattern, so `tests/conftest.py:log_events()` works unchanged.

### 4.5 Configuration conventions (Implemented)

* Environment variables, read by `OSLayerConfig.from_environment()` with a private `_read_whole_number()`; **no prefix** (`QUEUE_CAPACITY`, `WORKER_COUNT`, `DB_SEMAPHORE_PERMITS`).
* Demo/infra variables use a **`CREG_` prefix** (`CREG_DEMO_CONTROLS`, `CREG_RESULTS_DIR`, `CREG_SELF_URL`).
* `DATABASE_URL`, `TEST_DATABASE_URL` via `python-dotenv` (`app/database.py`, `tests/conftest.py`).
* Validation style: frozen `@dataclass` with `__post_init__` raising `ValueError` naming the field; bad environment text raises `ValueError` naming the variable and **stops start-up**.
* Defaults are documented as "development defaults, NOT experimental conclusions" (`layer_config.py:5-9`).
* `.env.example` is referenced in the README and `database.py` but **does not exist** in the repository.

The brief's `IASL_*` names do not conflict with either convention. Prefix choice is an open decision (Section 12).

### 4.6 HTTP API surface (Implemented)

| Endpoint | File | Auth | Notes |
|---|---|---|---|
| `POST /registrations` | `main.py:32` | none | Maps `result.code` to status via `HTTP_STATUS`: 201, 404, 409 (duplicate), 409 (full), 500, **503 (queue full, "provisional")**, 503 (shutting down) |
| `GET /os-layer/status` | `main.py:42` | none | Read-only counters |
| `GET /demo/info` | `demo_api.py:293` | none | Always on |
| `/demo/*` (state, reset, runs, results, verify, **os-layer**) | `demo_api.py` | gated by env `CREG_DEMO_CONTROLS=1` (`require_controls`, l.40), otherwise 404 | **No authentication**; the gate is an on/off deployment switch |

There is no authentication or authorisation anywhere. "Protect configuration-changing endpoints" (brief §8) can therefore only follow the existing pattern (env-gated, off by default) unless a new mechanism is introduced.

---

## 5. Existing integration points

| # | Point | Location | Suitability for IASL |
|---|---|---|---|
| 1 | **Admission decision site** | `OSConcurrencyLayer.submit()`, `request_pipeline.py:94-96` (the comment), immediately before `self.queue.try_put(job)` at l.98 | **Best fit.** Runs on the event-loop thread, must be O(1) and non-blocking. Rejection already has a shape: finish the Future with a `RegistrationResult`, log via `_log_rejection`. |
| 2 | Layer lifecycle | `create_app.lifespan`, `main.py:51-58` | Natural place to start/stop a controller thread (start after `layer.start()`, stop before `layer.stop`). |
| 3 | Metrics source | `OSConcurrencyLayer.snapshot()` | Reusable as the sampler's input. **No new counters needed for the first version** (but see gaps, §6). |
| 4 | Layer replacement | `demo_api.reconfigure_os_layer`, l.348-360 swaps `app.state.os_layer` | **Conflict:** any component holding a reference to the old layer goes stale. IASL must read the layer through `app.state` on every tick (or be re-bound), and treat a counter drop as a restart. |
| 5 | Status/response mapping | `main.py` `HTTP_STATUS`; result codes `QUEUE_FULL`, `SHUTTING_DOWN` in `request_pipeline.py:27-28` | A new rejection reason needs a code, a message and an HTTP mapping. See conflict C2. |
| 6 | Experiment recording | `demo_api._add_context` (l.219) writes `document["server"]` into each result file | The place to record IASL config/state per experiment for baseline-vs-IASL comparison. |
| 7 | Progress accounting | `demo_api.counters()` (l.170): `finished + rejected_queue_full` | **Conflict:** an admission rejection that isn't counted here makes run progress under-report. |
| 8 | Test harness | `tests/conftest.py` `start_server(os_config)`, `create_app(os_config)` | `create_app` takes only `os_config`; IASL needs a way in (Proposed: optional second parameter, default = disabled). |

---

## 6. Missing functionality (what IASL needs that does not exist)

| Needed | Status | Note |
|---|---|---|
| Admission controller | **Not implemented** | Only a marked location. |
| Runtime-adjustable admission limit | **Not implemented** | New state is required (an "admitted-in-flight" bound or token bucket). |
| Runtime-adjustable queue capacity | **Not supported cleanly** | `queue.Queue.maxsize` is a plain attribute and `BoundedRequestQueue.capacity` is a separate copy; changing one without the other makes `snapshot()` lie. Would require editing `bounded_queue.py` (excerpted by a frontend test, see C4). |
| Runtime-adjustable worker count | **Not supported** | `_threads` list fixed at `start()`; no add/remove; `stop()` shuts the whole queue down. |
| Runtime-adjustable semaphore permits | **Not supported** | `BoundedSemaphore(permits)`; `permits` is a plain attribute, but changing it does not change the semaphore. |
| Recent-window latency (p50/p95/p99) | **Not implemented** server-side | Needs a bounded in-memory sample (e.g. fixed-size ring or per-interval buckets) fed from `_process`. This is a new write on the request path. |
| Per-outcome counters | **Not implemented** | Needed for error rate / completed vs failed. |
| Server-side request timeout | **Not implemented** | `await asyncio.wrap_future(...)` (`main.py:36`) waits indefinitely. A "timeout rate" signal cannot exist until a server timeout does. |
| Periodic sampler / control loop thread | **Not implemented** | |
| Decision log / history | **Not implemented** | |
| Request classification/filtering stage | **Not implemented** | Listed in the brief's diagram; no requirement text for it beyond the diagram. |
| Per-experiment recording of IASL state | **Not implemented** | |

---

## 7. Potential integration conflicts

| ID | Conflict | Evidence | Consequence if ignored |
|---|---|---|---|
| **C1** | `OSLayerConfig` is asserted by exact equality in a test. | `tests/test_demo_api.py:193`: `document["server"]["os_layer"] == {"queue_capacity": 3, "worker_count": 2, "db_semaphore_permits": 1}`; also `layer_config` is serialised by `asdict(self.config)` into `snapshot()["config"]`, every `os_layer_*` log line, and `/demo/info`. | Adding IASL fields to `OSLayerConfig` breaks an existing test and silently changes three outputs. **IASL config must be a separate class.** |
| **C2** | The generator only recognises `(503, "Request queue is full")` as `QUEUE_FULL`. Any other 5xx becomes `SERVER_ERROR`; any other 4xx except 409 becomes `CLIENT_ERROR`. | `workload_generator.py:59-64`, `classify_response` l.275-285. `SHUTTING_DOWN` (503) already falls into `SERVER_ERROR` today. | A new admission rejection with a new message or a 429 would be counted as a **server/client error** in every experiment, corrupting error-rate comparisons. Options: reuse the existing code+message (loses the distinction between queue-full and admission-rejected), or extend the generator's `KNOWN_RESPONSES`, `ALL_CATEGORIES`, and the frontend `Category` type / `results.ts` (which validates categories against `ALL_CATEGORIES`, l.32). Needs a decision. |
| **C3** | Run-progress accounting counts only `finished + rejected_queue_full`. | `demo_api.counters()` l.170-172 | Admission rejections would not advance the progress bar until the run ends. Cosmetic but visible; also feeds `db_check`. |
| **C4** | Frontend test asserts four backend files contain verbatim excerpts. | `frontend/src/lib/landing-data.test.ts:13-17`; files: `workload/workload_generator.py` (`arrival_offsets`), `app/os_layer/bounded_queue.py`, `app/os_layer/db_semaphore.py`, `app/registration_service.py` | Editing the **excerpted lines** of these files breaks `npm test`. Adding code elsewhere in them is safe. The registration core and semaphore should not be touched anyway. |
| **C5** | Docs and UI state "no admission control / no IASL". | README l.226, 280-281; `frontend/README.md:67`; `FactsSection.tsx:13`; `Experiments.tsx:170`; `PipelineCanvas.tsx:173`; `architecture.ts:77-87`; `Workloads.tsx:209`; `docs/JUDGES_REPORT.md:123,199,285`; several `docs/code-notes/*.md` | Once IASL exists these become **false statements**. This conflicts with the brief's rule "do not modify unrelated frontend or documentation files" and with its rule to be truthful. Needs an explicit decision (Section 12). |
| **C6** | `reconfigure_os_layer` replaces the layer. | `demo_api.py:348-360` | A controller holding the old layer reference would control a stopped object. Also counters reset. |
| **C7** | Connection pool is smaller than the maximum permits the demo allows. | `database.py:15` pool 20 + overflow 40 = **60**; `reconfigure_os_layer` accepts `db_semaphore_permits` up to **64** (validation at `demo_api.py:351`) | At >60 permits, workers inside the DB section can exhaust the SQLAlchemy pool; the 30 s pool timeout raises `sqlalchemy.exc.TimeoutError`, which `register_student` catches and reports as `ERROR`. **Pre-existing**, but any IASL permit-raising feature must cap permits at pool capacity. (MySQL's own `max_connections` is 300 in the demo container and 151 by default.) |
| **C8** | `create_app(os_config=None)` has one parameter and builds the layer inside `lifespan`. | `main.py:47-57` | IASL needs a construction path that tests can inject into, with default disabled. Signature change must stay backward compatible (`tests/conftest.py`, `tests/test_api.py` call it). |
| **C9** | `submit()` is invoked on the event-loop thread. | `main.py:36` | Any admission logic (and any lock it takes) runs on the loop. Must be constant-time with no I/O; the controller thread must publish the new limit via a cheap atomic read. |
| **C10** | `snapshot()` is also called on the event loop (`os_layer_status`, `info`). | `main.py:44`, `demo_api.py:300` | A sampler polling at high frequency competes with request handling. Keep sampling interval coarse and the snapshot cheap (it currently is). |
| **C11** | SQLite cannot validate concurrency behaviour. | README "Run the tests"; 19 skips on SQLite | IASL concurrency/consistency tests are meaningful **only on MySQL**; SQLite results must be reported separately (as the brief requires). |
| **C12** | Docker Desktop restarts unrelated containers; shared host. | observed this session | Experiments (Stage 8) will run on a machine also hosting other containers (`saams-*`). Latency/throughput results will be noisy. Must be disclosed, and ideally those containers stopped for measurement runs. |

---

## 8. Files to modify, and files to leave alone

### 8.1 Expected to be modified (Proposed; each only if the design requires it)

| File | Why | Risk |
|---|---|---|
| `app/os_layer/request_pipeline.py` | Replace the comment at l.94-96 with a call to an admission hook; optionally add per-outcome counters / recent-latency recording in `_process` and `snapshot()` | Medium: hot path; `snapshot()` shape is consumed by `frontend/src/lib/api.ts:parseOsLayerStatus` (additive fields are safe, removals are not) and by `test_api.py:test_status_endpoint_reports_configuration_and_counters` |
| `app/main.py` | Build/start/stop IASL in `lifespan`; map any new result code in `HTTP_STATUS`; include a new router | Low-Medium |
| `app/demo_api.py` | `counters()` (C3); `_add_context` to record IASL state; `reconfigure_os_layer` must re-bind IASL (C6) | Medium |
| `workload/workload_generator.py` | **Only if** C2 is resolved by adding a category | Medium: must not touch the excerpted `arrival_offsets` (C4); needs matching tests |
| `frontend/src/lib/types.ts`, `results.ts` | **Only if** C2 adds a category | Low, but outside the brief's "don't modify unrelated frontend" |
| `tests/conftest.py` | Possibly add an IASL-aware server fixture (additive) | Low |
| `README.md`, `docs/…` | C5 | Needs decision |

### 8.2 Should remain untouched

| File | Reason |
|---|---|
| `app/registration_service.py` | Correctness core; also excerpted by a frontend test. IASL must be isolated from it (brief §4E). |
| `app/models.py` | Constraints are the final guarantee. |
| `app/database.py` | Pool/engine; only *read* its limits. |
| `app/os_layer/db_semaphore.py`, `app/os_layer/bounded_queue.py` | Excerpted by a frontend test (C4); fixed-size by design; their dedicated tests (`test_os_components.py`) pin current behaviour. IASL should not make them resizable in the first version. |
| `app/os_layer/worker_pool.py` | No safe resize; leave. |
| `app/os_layer/layer_config.py` | C1. |
| `app/seed.py`, `app/schemas.py`, `app/verification.py` | Unrelated. |
| All existing tests | Must not be weakened (brief §9). Additive only. |
| `results/*.json` | Historical experiment evidence. |

### 8.3 New files (Proposed, for Stage 1 design to confirm)

An `app/iasl/` package, one small module per brief module (metrics, analyzer, controller, decision engine, guardrails, config), an `app/iasl_api.py` router (matching the `demo_api.py` naming), `tests/test_iasl_*.py`, and the `docs/iasl/*.md` set.

---

## 9. Current test coverage

### 9.1 Baseline runs (executed during this audit)

| Database | Command | Result |
|---|---|---|
| **MySQL 8.4.11 / InnoDB** (Docker `creg-demo-mysql`, port 3307, DB `concurrentreg_demo_test`) | `.venv/bin/python -m pytest -q -p no:cacheprovider` with `TEST_DATABASE_URL` from `.demo.env` | **188 passed, 1 warning, 34.40 s** |
| **SQLite** (`sqlite:///…/creg_test`, file) | `env -u DATABASE_URL TEST_DATABASE_URL=sqlite:///…/creg_test .venv/bin/python -m pytest -q -p no:cacheprovider` | **169 passed, 19 skipped, 1 warning, 11.78 s** (all 19 skips: "needs MySQL/InnoDB row locks") |
| Frontend | `npm run typecheck`; `npm test` | typecheck clean; **77 passed** (run earlier in this session) |

The single warning is a Starlette deprecation about `httpx` in `fastapi.testclient`; not related to IASL. The MySQL run used the `_test` database; the demo database `concurrentreg_demo` was not used by the tests (`conftest.py` refuses any database not ending in `_test`).

### 9.2 What the existing tests cover (by file)

| File | Covers | Relevance to IASL |
|---|---|---|
| `test_registration.py`, `test_concurrency.py` | Day 1 correctness: no oversell, no duplicates, 50-vs-10 race | **Must stay green**; reusable as the "no oversell" oracle |
| `test_os_components.py` (18 tests) | Queue bound, FIFO, shutdown; semaphore limit and release-on-exception; pool survives errors, stop semantics; config validation | Pins behaviour of the pieces IASL should not alter |
| `test_os_request_pipeline.py` (9) | Layer limits reached and never exceeded; queue-full immediate rejection; queue wait observable; log fields; no leaks; cancel-while-queued; graceful stop. Uses `FakeRegistration` + `make_layer`/`gate` fixtures | **Template for IASL pipeline tests without MySQL** |
| `test_os_layer_mysql.py` (9) | Real transaction through the layer, Day 2 clients saturating limits, InnoDB lock-wait ≤ permits | Template for MySQL-only IASL consistency tests |
| `test_api.py` (5) | Handler behaviour, provisional 503, status endpoint, shutdown 503 | Pins `HTTP_STATUS` and status shape |
| `test_demo_api.py` (17) | Demo gate, state/invariants, runs, result-file safety, one run at a time, settings change, JUnit parsing | Pins `/demo/*`, incl. C1 |
| `test_mysql_innodb.py` | InnoDB engine, capacity-1 race through API | |
| `test_workload_*` | Generator schedules, arrival models, live runs | Pins C2 behaviour |
| Frontend `vitest` | schedule parity with Python, results maths, command builder, excerpt copies (C4) | |

### 9.3 Not covered today

IASL (nothing to cover); server-side latency percentiles; per-outcome counters; any time-based/controller behaviour; any test of multi-process deployment; no test for pool exhaustion at >60 permits (C7); component/route tests in the frontend (documented as screenshot-checked only).

---

## 10. Risks and dependencies

| Risk | Detail | Mitigation direction (Proposed) |
|---|---|---|
| **Control instability** | A feedback loop over a noisy, bursty signal can oscillate. | Hysteresis, cooldown, small steps (as the brief requires); calibrate thresholds experimentally; ship **disabled by default**. |
| **Measurement noise from shared host** | C12; also the load generator runs on the same machine as server and DB, so client and server compete for CPU. The generator itself documents that an overloaded client invalidates open-loop runs (`valid_open_loop`). | Report `valid_open_loop`; repeat runs; disclose; stop unrelated containers during Stage 8. |
| **Few distinct hot sections** | Seed data is 10 students, 2 sections (`seed.py`). Requests > 10 for one section repeat students and yield `DUPLICATE`. Contention is dominated by a single row lock. | Experiments need more students/sections than the seed provides (that is *test data*, not production); the generator supports `--students`, `--sections`. |
| **Rejecting load can look like "better latency"** | Admission control trivially lowers p95 of *accepted* requests by turning others away. | Always report rejection rate and goodput alongside latency; evaluate on registrations/second and total outcomes, not latency alone. |
| **Admission ≠ registration** | `queue.accepted` already means only "entered the queue". | Keep lifecycle stages as separate counters (brief §5). |
| **Python-version dependency** | Requires ≥ 3.13 (`queue.ShutDown`); environment is 3.14.6 (GIL build, not free-threaded). | Keep IASL pure-stdlib. |
| **Dependency on `pytest`/`uvicorn`/FastAPI pinned versions** | `requirements.txt` pins exact versions (fastapi 0.142.2, sqlalchemy 2.1.1, …). | No new third-party dependency is anticipated. |
| **No version control** | `git status` fails. | Initialise git / snapshot before Stage 2. |
| **No auth** | See 4.6. | Follow the env-gated pattern; no public write endpoints. |
| **Docs/UI truthfulness** | C5. | Decision needed. |
| **Environment fragility seen this session** | `.demo.env` is generated per checkout; an existing container created with a different root password caused a setup failure that was fixed by aligning `.demo.env` with the container. `.env.example` is missing. | Document; not an IASL concern. |

---

## 11. Proposed integration approach (high level, for review; **not a design**)

Stage 1 will turn this into a detailed design. The audit's evidence points to:

1. **Control knob.** A new, bounded **admission limit** at `submit()`, owned by a new component, **not** resizing queue/workers/semaphore (they cannot be resized safely today). Worker/semaphore adjustment would be reported as *unsupported* rather than faked. The brief itself says "only if the existing worker pool safely supports runtime adjustment"; it does not.
2. **Metrics.** Start from `snapshot()` deltas on a periodic sampler thread (coarse interval). Add only what is missing and cheap: per-outcome counters and a recent-latency window, written outside the correctness-critical path. Mark unavailable metrics (timeouts, DB timeouts, lock waits) as **unavailable** in `/iasl/metrics`.
3. **Isolation.** IASL reads, decides, and publishes a number. The only code on the request path is one O(1) comparison at `submit()`. If the controller thread dies or metrics go stale, the limit reverts to a fixed, bounded fallback; if IASL is disabled, `submit()` behaves exactly as today.
4. **Rejection semantics.** An admission rejection must be a distinct, logged, counted outcome that is **never** reported as a registration result. Its HTTP shape is the open decision C2.
5. **Rule-based first.** Deterministic controller; no ML/LLM (as specified).

---

## 12. Decisions needed from you before Stage 1

1. **C2 — how should an admission rejection appear to clients?**
   (a) reuse `503 "Request queue is full"` (no generator/frontend change, but queue-full and admission-rejected become indistinguishable in results);
   (b) new distinct response + extend `workload_generator.py` and the frontend `Category`/`results.ts` (accurate, but touches files the brief says not to modify unnecessarily). **Recommendation: (b), small and additive**, because experiment integrity depends on it.
2. **C5 — update the "not implemented" statements in README/docs/frontend once IASL exists?** The brief forbids touching unrelated files, but leaving them is knowingly inaccurate. **Recommendation:** update only the specific statements that become false, listed in C5, in the final stage, and list them in the report.
3. **Control scope.** Confirm the first version controls **only the admission limit**, with queue/worker/semaphore resizing explicitly out of scope (unsupported today). **Recommendation: yes.**
4. **Config prefix.** `IASL_*` as in the brief (no conflict found). **Recommendation: yes.**
5. **Write-endpoint protection.** Follow the existing `CREG_DEMO_CONTROLS` gate for any config-changing endpoint, and ship read-only status endpoints publicly like `/os-layer/status`. **Recommendation: yes; no runtime-write endpoints in v1** (config is env-only), which removes the protection problem.
6. **Version control.** OK to run `git init` and make a baseline commit (or should I only copy the tree)? Nothing will be committed without your say-so.
7. **Experiment host.** OK to stop the unrelated `saams-*` / `docker-*` containers during Stage 8 measurement runs, or accept noisier numbers with disclosure?
8. **Server-side request timeout** (a prerequisite for a meaningful "timeout rate" signal) is out of scope unless you want it added; otherwise timeout-based signals are reported as unavailable.

---

## 13. Audit limitations

* The audit is a static read plus two baseline test runs. No load experiment has been run; no claim is made about current performance.
* Line numbers refer to the repository as audited on 2026-11-25 and will drift as code changes.
* The frontend was reviewed only where it touches the backend (types, API client, test that excerpts backend files, text that states IASL is absent); component behaviour was not audited.
* `results/` contains earlier experiment files; they were counted but not analysed here.
* Behaviour on PostgreSQL, multi-process deployment, or real university-scale load was not examined and is not claimed.
