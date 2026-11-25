# app/demo_api.py

**Purpose.** Lets the dashboard drive the real system in front of an audience. It does not touch the registration path: it only *orchestrates* things that already exist (the workload generator, `app/seed.py`, the pytest suite) and *reads* the database to check the correctness rules.

**Safety.** Everything except `GET /demo/info` is switched off unless the server is started with `CREG_DEMO_CONTROLS=1` (otherwise 404). Resetting the database and running a test suite must never be reachable on a normal deployment.

## Endpoints

| Endpoint | What it does |
|---|---|
| `GET /demo/info` (always on) | whether controls are enabled; the database dialect, version and whether it has row locks; the OS-layer settings; whether the tests can run safely |
| `GET /demo/state` | sections with capacity / seats left / registered, student and registration totals, and four invariants computed by SQL (capacity never exceeded; seats left = capacity - registered; 0 <= seats <= capacity; no repeated student+section) |
| `GET /demo/registrations` | the stored rows, joined with student and course codes (read-only) |
| `POST /demo/reset` | `reset_and_seed()`; refused (409) while a run is going |
| `POST /demo/runs` | validates a generator configuration with the generator's own `validate_config`, then runs it in a background thread against THIS server and saves the generator's normal result file |
| `GET /demo/runs/{id}`, `/runs/current` | progress (estimated from the layer's own counters: finished + refused since the run began), and when done the summary and the database cross-check |
| `GET /demo/results`, `/results/{id}` | list and read the result files (file name is checked twice: a pattern, and a real-path check so a symlink cannot escape the folder) |
| `POST /demo/os-layer` | replaces the queue/worker/semaphore layer with new settings, so a baseline-versus-candidate comparison needs no restart |
| `POST /demo/verify`, `GET /demo/verify/current` | runs the repository's pytest suite (see `verification.py`) |

## How a run goes

1. one run at a time (a lock held for the whole run; a refused start releases it again);
2. optionally reset the data; read the real section ids and student count from the database;
3. build a `WorkloadConfig` (base URL is this server), validate, start the thread;
4. the thread calls `generate_requests`, `run_workload`, `summarize_results`, `save_results`, `check_saved_results` exactly as the generator's own `main()` does;
5. **cross-check**: the number of rows in the database against the number of successes the client was told about (only when the data was reset first, otherwise earlier rows are included); the invariants are checked again;
6. the file gets an extra `server` block (OS-layer settings, database, whether the data was reset, the cross-check) because the generator cannot know them.

## Variables worth knowing

`CREG_DEMO_CONTROLS` (`1` to enable), `CREG_RESULTS_DIR` (where result files go; default `results`), `CREG_SELF_URL` (override the URL the generator uses to reach this server; default `http://127.0.0.1:<port>`), `MAX_DEMO_REQUESTS` (5000).

## Errors

409 a run/test is already going; 422 the generator's own message (for example "request_count must be between 1 and 10000"), more students than exist, or settings out of range; 404 controls are off or no such result.

## Tests

`tests/test_demo_api.py` (17 tests): gating, state, invariants that really fail on broken data, reset, a complete run with the database cross-check, path-escape guard (called directly, including a symlink), one run at a time, bad settings releasing the lock, live settings change, and (MySQL only) a 30-request seat race that stores exactly the section's capacity. Mutation checks: inverting the capacity invariant, and breaking the cross-check, each make tests fail; removing the real-path guard makes the symlink test fail.

## What it does not do

It does not change how a registration is processed, does not create new correctness logic (the database constraints and the row lock remain the authority), and does not claim a run is valid: the validity rules come from the generator.
