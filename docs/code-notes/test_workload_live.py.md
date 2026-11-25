# tests/test_workload_live.py

## 1. Purpose
Runs the workload generator against the real Day 1 backend.

## 2. How it works
The `server_url` fixture (now in `conftest.py`, with generous Day 3 OS-layer settings so the queue, workers and semaphore never limit these tests) starts the real FastAPI app with uvicorn in a background thread on a free
local port. The app uses the test database (`TEST_DATABASE_URL`, set up by `conftest.py`).

The hot-workload test and the overlap test are marked `requires_mysql` because they rely on the row lock
(on SQLite the overlap test shows 5 requests in flight but no waiting, and the hot test oversells).
The CLI, reproducibility, unreachable-API and invalid-config tests run on any database.

## 3. Tests
- `test_hot_workload_against_real_backend_keeps_day1_invariants` — 6 requests, 3 in flight, all for CSE302 (2 seats). Expects 2 `SUCCESS`, 4 `COURSE_FULL`, no `UNKNOWN`/`SERVER_ERROR`; the **test** then reads the database: 2 registrations, 0 seats left. The generator only reports; the database check is what proves the backend stayed correct.
- `test_requests_really_overlap_when_the_section_is_locked` — the test holds the section's row lock (a read-only `SELECT ... FOR UPDATE` from a separate connection; the backend is not modified) for 0.5 s while 5 requests are sent with concurrency 5. All must wait together, so the recorded intervals must overlap: peak in flight = 5, every latency ≥ 400 ms, then 5 `SUCCESS`. This is the evidence that the generator creates concurrent requests, which a thread count alone would not give.
- `test_cli_run_saves_a_readable_result_file_and_is_reproducible` — runs `main` twice with the same seed; checks both JSON files exist, are complete, record the seed, and contain identical `generated_requests`.
- `test_unreachable_api_is_an_experiment_level_failure` — nothing listening: exit code 1, but the 3 `CONNECTION_ERROR` records are saved.
- `test_invalid_cli_configuration_exits_before_sending_anything` — exit code 2, no file written.

## 4. Limits
Overlap is proven by the lock-hold technique, not for ordinary fast requests; a local server answers in a few
milliseconds, so ordinary burst runs overlap only partly. Only small workloads (≤ 6 requests) are run here.
