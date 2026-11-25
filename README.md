# ConcurrentReg

Research prototype for the project **"An OS and DBMS Framework for Managing High-Volume
University Course Registration."** It studies what happens when many students try to register
for limited-capacity course sections at the same time. This is a research prototype, not a
production system.

## Current scope: Day 1 core + Day 2 workload generator + Day 3 OS concurrency layer + optional IASL admission control

**Day 1 — the correct registration core.**
Only the database-backed registration core exists: each request runs in one MySQL transaction that
looks up the student, locks the section row, checks for duplicates and free seats, inserts the
registration and decreases the seat count by exactly 1 (committing once), or rolls back.

**Day 2** added an external workload generator (below). **Day 3** added the server-side OS concurrency layer:
a bounded queue, a worker pool and a DB semaphore placed around the unchanged Day 1 transaction (below).
**IASL** (added later, **off by default**) is an optional, deterministic, rule-based admission-control layer in front of the queue (see "IASL (adaptive admission control)" below).

## Technology

Python 3.14 (3.13 or newer is required: the queue shutdown feature) · FastAPI · SQLAlchemy 2 · MySQL 8.4 (InnoDB) · pytest

## Project structure

```
app/
  database.py              engine, session factory, DATABASE_URL
  models.py                students, course_sections, registrations tables
  schemas.py               request / response bodies of the API
  registration_service.py  the transaction-safe registration logic
  main.py                  POST /registrations, GET /os-layer/status, layer start-up/shutdown
  iasl_api.py              read-only GET /iasl/status|metrics|decisions|config
  iasl/                    optional adaptive admission control (off by default; see docs/iasl/)
  os_layer/                Day 3: the OS concurrency layer
    layer_config.py          queue capacity, worker count, semaphore permits
    bounded_queue.py         bounded FIFO queue of waiting requests
    worker_pool.py           server-side worker threads
    db_semaphore.py          limits workers inside the database section
    request_pipeline.py      joins them to register_student and logs every request (and hosts the optional IASL hooks)
  seed.py                  development/test data (made-up students and courses)
workload/
  workload_generator.py    Day 2: client-side workload generator (CLI)
tests/                     pytest tests (Day 1, Day 2 and Day 3)
docs/code-notes/           plain-English notes for every source file
.env.example               environment variable template
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Database

Create two empty MySQL databases and a user that owns them (any MySQL 8 works):

```sql
CREATE DATABASE concurrentreg;
CREATE DATABASE concurrentreg_test;
CREATE USER 'creg'@'127.0.0.1' IDENTIFIED BY 'choose-a-password';
GRANT ALL ON concurrentreg.* TO 'creg'@'127.0.0.1';
GRANT ALL ON concurrentreg_test.* TO 'creg'@'127.0.0.1';
GRANT PROCESS ON *.* TO 'creg'@'127.0.0.1';  -- optional: lets one MySQL test read InnoDB's lock-wait list
```

### Environment

Copy `.env.example` to `.env` and fill in the credentials (`.env` is ignored by Git), or export
the variables in your shell:

- `DATABASE_URL` — the database the API uses.
- `TEST_DATABASE_URL` — the database the tests use. Its name **must end in `_test`**: the tests
  drop and recreate every table, and refuse to start otherwise.
- `QUEUE_CAPACITY`, `WORKER_COUNT`, `DB_SEMAPHORE_PERMITS` — the three Day 3 settings (all optional, see
  "Day 3" below). A value that is not a whole number of at least 1 stops the server from starting.

### Create tables and load seed data

```bash
.venv/bin/python -m app.seed      # drops, recreates and seeds the tables in DATABASE_URL
```

## Run the backend

```bash
.venv/bin/uvicorn app.main:app --port 8000
curl -X POST localhost:8000/registrations -H 'content-type: application/json' \
     -d '{"student_id": "STU001", "section_id": 1}'
```

| Situation | HTTP status | `success` | `message` |
|---|---|---|---|
| Registered | 201 | true | Registration successful |
| Already registered | 409 | false | Student is already registered for this course section |
| No seats left | 409 | false | Course section is full |
| Unknown student / section | 404 | false | Student does not exist / Course section does not exist |
| Unexpected database error | 500 | false | Registration failed because of a database error |
| Queue full (Day 3, **provisional**, see below) | 503 | false | Request queue is full |
| Server shutting down (Day 3) | 503 | false | Server is shutting down |

Each request writes one Day 1 JSON log line (request ID, student, section, start time, result, error,
duration) and one Day 3 `os_layer_request` line with the same request ID (see Day 3).

## Run the tests

```bash
.venv/bin/python -m pytest -v
```

The pytest header shows which database the run used (`test database dialect: ...`), and skipped tests
are always listed with their reason (`pytest.ini` turns on `-rs`).

**Which database to test on.** `TEST_DATABASE_URL` decides. The project's concurrency guarantee depends on
row-level locking (`SELECT ... FOR UPDATE`), so:

| Test database | What it is good for | What it cannot show |
|---|---|---|
| **MySQL/InnoDB** (the intended environment) | The full suite, including every concurrency test and `tests/test_mysql_innodb.py` | Anything about PostgreSQL |
| **SQLite** (e.g. `sqlite:///some_test`) | Quick single-threaded checks of the logic, API and workload generator | Concurrency correctness. SQLite has no row locks and ignores `FOR UPDATE`; in an observed run all 50 requests for 10 seats succeeded. This is a SQLite limitation, not evidence about the MySQL implementation. |

On anything other than MySQL, the 8 tests that depend on row locks are **skipped**, not counted as passed.

**MySQL-specific verification** (run only if `TEST_DATABASE_URL` points to a MySQL test database):

```bash
.venv/bin/python -m pytest -v tests/test_mysql_innodb.py
```

It checks that the three tables are InnoDB, then sends 4 concurrent requests for a capacity-1 section through
the real API while the section's row lock is held. A passing run establishes that, in that run, InnoDB reported
all 4 transactions waiting on the row lock, exactly 1 registration succeeded, the persisted seat count is 0 and
there are no duplicate rows. The lock-wait count needs the `PROCESS` privilege; without it that one test skips.
It does **not** establish capacity at university scale, realistic traffic, PostgreSQL behaviour, or anything about
anything about the IASL admission layer (what is established about it is in `docs/iasl/IASL_TESTING.md`). The numbers in the tests are small test-fixture values, not research parameters.

## Day 2: workload generator (arrival models added in Phase 1)

An external client that sends controlled, repeatable registration traffic to `POST /registrations`
and records the outcome of every request. It never touches the database and contains no admission
control, queue or retry logic. Its thread pool only creates concurrent *client* traffic; it is not the
server-side worker pool of Day 3. Workloads are **synthetic**; they are not claimed to represent real
university traffic, and the defaults are demonstration values, not research parameters.

```bash
.venv/bin/python -m app.seed                                   # reset to known data first
.venv/bin/uvicorn app.main:app --port 8000                     # in another terminal
.venv/bin/python -m workload.workload_generator --pattern burst --contention hot \
     --requests 20 --seed 42                                   # see --help for all options
```

**Two arrival models**
- **Open loop** (`--arrival-model open`, the default). Every request has an *intended arrival time* fixed in advance, and responses never change it. If the generator cannot keep up (the in-flight cap, `--concurrency`, is full when a request is due), that request is sent late. The intended time is **not** moved: the delay is measured as *lateness* and the run is flagged.
- **Closed loop** (`--arrival-model closed --users N`). N virtual users; each thinks (`--think-min`, `--think-max`, seeded; equal values = fixed), sends a request, **waits for the response**, then repeats. There are no intended arrival times, so arrivals depend on how fast the server answers.

**Open-loop timing** (`--pattern`): `steady` (fixed `--rate`), `burst` (all at once), `ramp` (rate grows in `--ramp-stages` up to `--rate`), or multi-phase `--phases "RATE:DURATION,..."`. Example (not a recommended value): `--phases "10:5,100:2,10:10"` = 10 requests/s for 5 s, a 100/s burst for 2 s, then 10/s for 10 s to watch recovery. Phases are half-open `[start, end)`; the request count comes from the phases.

**Targets** (`--contention`): `hot` (the first `--hot-sections` of `--sections`), `independent` (all sections evenly), `mixed` (`--hot-fraction` hot). `--duplicate-fraction` repeats earlier student+section pairs. The seed data has 10 students, so more than 10 requests for one section necessarily repeat students and produce `DUPLICATE` results.

**Two latencies per request**
- `send_time_latency_ms` (also `latency_ms`): from the moment the request was sent to the response.
- `intended_arrival_latency_ms`: from the moment it was *meant* to arrive to the response. It equals `lateness_ms + send_time_latency_ms`. When the generator is late, only this one shows the delay the user would feel.

**Rates and validity.** `offered_rate_per_s` and `achieved_dispatch_rate_per_s` both use `(events - 1) / (last - first)`, on the intended times and on the actual send times. `completed_requests_per_second` and `successful_registrations_per_second` are different things (over the whole run). `valid_open_loop` is true only if every intended request was sent **and** none was sent more than `--lateness-tolerance-ms` (default 50, a demonstration value) after its intended time; `invalid_reasons` and the lateness statistics always explain an invalid run. An invalid run still exits 0 with a warning on stderr; read the flag in the result file. An invalid run should not be used as open-loop evidence: lower the rate, raise `--concurrency` (up to 1000; each in-flight request is a thread and a connection), or run the client on a less busy machine.

**Output.** One JSON file per run in `results/` (ignored by Git): experiment ID, configuration, generated requests, per-request results, a summary (with `open_loop` or `closed_loop`), and a `run` block with the generator version and git revision, seed, schedule and phase boundaries, in-flight cap or virtual users, think times, timeout, tolerance and start/end times. Result categories: `SUCCESS`, `DUPLICATE`, `COURSE_FULL`, `QUEUE_FULL`, `CLIENT_ERROR`, `SERVER_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `UNKNOWN`, and `NOT_DISPATCHED` (the run was stopped before a request was sent). Unrecognised answers are never counted as success.

**Reproducibility.** The same seed and configuration give the same intended schedule, think times and request targets. Thread scheduling, network and server timing (so lateness, latency and which request wins a seat) are not reproducible. Re-seed the database between runs you want to compare.

**Changed default.** `--concurrency` (the in-flight cap) now defaults to 100 instead of 5, so a burst or a fast schedule is not silently throttled. Pass `--concurrency 5` to get the old limit.

**Not implemented here:** random (Poisson) arrivals, dataset scaling, server-side metrics, an experiment runner.

## Day 3: OS concurrency layer (server side)

Every registration request now passes through three mechanisms before the Day 1 transaction runs:

```
Client request -> API (main.py) -> bounded queue -> worker pool -> DB semaphore -> Day 1 transaction -> MySQL/InnoDB
                                  (optional: with IASL_ENABLED=1 an admission check sits before the queue; see "IASL" below)
```

- **Bounded queue** — holds accepted requests waiting for a worker; first in, first out; when it is full the next request is refused immediately instead of waiting.
- **Worker pool** — `WORKER_COUNT` server threads take requests off the queue. This is server-side concurrency; it is **not** the client-side thread pool of the Day 2 workload generator, which only creates traffic.
- **DB semaphore** — `DB_SEMAPHORE_PERMITS` permits; a worker holds one only while it runs the registration transaction. A request waiting in the queue holds none.
- The registration transaction, row locking, duplicate protection and commit/rollback are the unchanged Day 1 code; the database remains the authority on correctness.

| Setting (environment variable) | Meaning | Development default |
|---|---|---|
| `QUEUE_CAPACITY` | most requests allowed to wait | 16 |
| `WORKER_COUNT` | server worker threads | 4 |
| `DB_SEMAPHORE_PERMITS` | workers allowed in the database section at once | 2 |

The defaults only let the server start locally. They are **experimental parameters, not recommendations**: they are meant to be varied between runs and are fixed while the server runs.

```bash
QUEUE_CAPACITY=8 WORKER_COUNT=3 DB_SEMAPHORE_PERMITS=2 .venv/bin/uvicorn app.main:app --port 8000
curl localhost:8000/os-layer/status        # configured limits + live counters (read-only)
```

**Observability.** `GET /os-layer/status` returns the configured limits and counters: queue depth, maximum depth, accepted and
refused requests, active and maximum workers, semaphore holders/waiters and their maxima, and queue-wait totals. Each request also logs an
`os_layer_request` JSON line (request ID, queue wait, semaphore wait, time in the database section, worker, result, and the three configured limits);
refused requests log `os_layer_rejected`. These are measurements for research, not a monitoring system.

**Client concurrency is not server concurrency.** 20 client threads in the workload generator can be in flight while the server runs
only `WORKER_COUNT` workers. The server-side counters above, not the number of client threads, show what the server did.

**Run the Day 3 tests**

```bash
.venv/bin/python -m pytest -v tests/test_os_components.py tests/test_os_request_pipeline.py   # any test database
.venv/bin/python -m pytest -v tests/test_os_layer_mysql.py                                    # needs a MySQL/InnoDB TEST_DATABASE_URL
```

The first two files use no row locks and run anywhere. `test_os_layer_mysql.py` runs the real registration transaction through the layer
(including the Day 2 generator as clients) and is skipped, with a reason, on SQLite or any other database (see "Run the tests" above).
Its end-to-end test uses a course with exactly one seat and several simultaneous clients, holds that course's row lock so the requests are
really in flight together, and checks the result three ways: the layer's own counters (queue depth, active workers, permits), InnoDB's list
of waiting transactions (needs the PROCESS privilege; otherwise that one test is skipped) and the request log lines. What it shows: for those
runs the limits were reached and not exceeded and exactly one registration was stored. It does not show capacity at university scale or
anything about performance.

**Unresolved decisions (not settled in the Master MD).** The HTTP response for a full queue is only a **provisional 503**; the final
ordering/fairness policy (first-in-first-out is used for now); the exact boundary of the database critical section (the whole registration
call is used for now); behaviour under worker saturation (requests wait in the queue until it is full).

**Limitations.** No retries and no server-side request timeout. Admission control exists only as the optional IASL layer (off by default, described below); with it off, only the queue's own capacity can turn a request away. Every refusal is logged on the request-handling thread.
Nothing in this section claims the layer improves performance or that any setting is good; the IASL evaluation is in `docs/iasl/IASL_EXPERIMENTS.md`.

## IASL (adaptive admission control)

IASL (Intelligent Adaptive System Layer) is an **optional** layer in front of the bounded queue. A controller thread samples the OS layer's counters,
classifies the system as HEALTHY, UNDER_PRESSURE or OVERLOADED with fixed rules (hysteresis, cooldowns, hard bounds), and moves **one** number: the
*admission depth limit* (a request is admitted only while fewer than that many requests are waiting). It is deterministic and rule-based, and every decision
is logged with the reason. It never touches the registration transaction or the database; the database stays the authority on seats and duplicates.

- **Off by default.** Nothing is installed and behaviour is unchanged unless you start the server with `IASL_ENABLED=1`. Settings are `IASL_*` environment variables (validated at start-up; a bad value stops the server and names it). All thresholds and limits are **provisional, uncalibrated defaults**.
- **A refused request** gets HTTP 503 with the message `Request rejected by admission control`, counted separately from `Request queue is full`. The workload generator reports it as the `ADMISSION_REJECTED` category.
- **Read-only endpoints:** `GET /iasl/status`, `/iasl/metrics`, `/iasl/decisions`, `/iasl/config`. There is no endpoint that changes IASL.
- **Safety:** if the controller fails, stalls or sees stale/invalid metrics, the limit falls back to a fixed bounded value (by default the queue capacity, i.e. no admission restriction).

```bash
IASL_ENABLED=1 QUEUE_CAPACITY=200 WORKER_COUNT=8 DB_SEMAPHORE_PERMITS=4 .venv/bin/uvicorn app.main:app --port 8000
curl localhost:8000/iasl/status
```

**What it is and is not.** It can trade refusals for shorter queueing delay; it cannot raise throughput (the database and semaphore bound that). It is **not** shown to be better in
general: the measured results, including where it did not help, are in `docs/iasl/IASL_EXPERIMENTS.md`. Not implemented: see the list under "Intentionally NOT implemented yet".
Design, configuration, test record and audit are in `docs/iasl/`.

## Frontend (added after Day 3)

`frontend/` holds a landing page and an experiment dashboard (Vite, React, TypeScript). It polls `GET /os-layer/status`, reads the JSON files
the workload generator writes to `results/` (imported in the browser, or loaded from the server in demo mode), and in demo mode drives the backend (below). Panels are
labelled live, result file, simulation, schematic or not exposed. See `frontend/README.md` and `docs/code-notes/frontend.md`.

```bash
cd frontend && npm install && npm run dev      # http://localhost:5173, proxies /api to http://127.0.0.1:8000
```

## Judges' demo (live dashboard on real MySQL)

One command starts a throwaway MySQL 8.4 (Docker, port 3307, localhost only), the backend with the demo controls on, and the dashboard:

```bash
./scripts/start_demo.sh        # then open http://localhost:5173/dashboard/demo
./scripts/stop_demo.sh --db    # stop everything (the MySQL data is kept)
```

The **Live demo** page walks through five steps, and every number on it comes from the running backend: (1) which database it really uses and the
server settings (changeable live); (2) the seats, four correctness rules computed by SQL on the live database, and the stored rows; (3) run a
scenario with the real workload generator against the real API, watching the queue; (4) the evidence: what the client was told versus what MySQL
stored, every request in the order it was answered, and a comparison with the previous run (with the server settings each run used);
(5) run the project's own pytest suite from the page and watch it stream. On SQLite the page says plainly that there are no row locks.

The demo controls are **off unless the server is started with `CREG_DEMO_CONTROLS=1`** (resetting the database and running tests must never be reachable
on a normal deployment). Only `GET /demo/info` is always on. The endpoints are in `app/demo_api.py` and `app/verification.py` (notes in `docs/code-notes/`);
the registration path is unchanged (the OS layer and the generator gained only the optional IASL hooks and the `ADMISSION_REJECTED` result category).

**Verified on 2026-10-19** (exact counts, nothing rounded): full Python suite on MySQL 8.4.11 / InnoDB, **188 passed, 0 failed, 0 skipped**; on SQLite
**169 passed, 0 failed, 19 skipped** (all 19 need row locks and say so). The same suite run from the dashboard's button: 188 passed on MySQL. A browser test
drove the page end to end against MySQL (20 checks: database badge, race with the database cross-check, live settings change, overload with refusals,
run comparison, the streamed test run, the Workloads "run now" panel, the server result list, the landing button): 20 of 20 passed.
Those figures are for the code as it was then; for the current suite (including the IASL tests) and how it was run, see `docs/iasl/IASL_TESTING.md`.

## Day 1 correctness guarantees

- Successful registrations for a section never exceed its capacity: the section row is locked
  with `SELECT ... FOR UPDATE` before seats are checked, and a database `CHECK` rejects a seat
  count below 0 or above capacity.
- A student cannot hold two registrations for one section: the service checks first, and the
  database `UNIQUE(student_id, section_id)` constraint is the final protection.
- The registration insert and the seat decrease commit together or not at all.

These guarantees are what the included tests establish (including bounded concurrent tests of up to
52 simultaneous requests). They are not claims about every workload.

Row-level locking is the *initial correctness-preserving implementation* used to establish the
core. It has not been compared against other strategies; that comparison is future work.

## Intentionally NOT implemented yet (future work)

Retry policy, calibrated load levels and large-scale experiments, AI/ML workload prediction and anomaly detection, PostgreSQL comparison,
authentication. None of these exist in this repository.

Within the IASL area specifically, **not implemented**: request filtering/classification, resizing the queue, worker pool or DB semaphore at run time,
any machine-learning, LLM or reinforcement-learning policy, a server-side request timeout (so timeout rate and DB timeouts are reported as unavailable),
calibrated thresholds (all defaults are provisional), multi-process deployment, and any write endpoint (IASL is configured only through the environment).
