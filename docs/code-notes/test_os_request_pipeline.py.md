# tests/test_os_request_pipeline.py

## 1. Purpose
Tests the whole OS layer (queue + workers + semaphore) with a controllable stand-in for `register_student`, so every situation can be created exactly and no database work is involved.

## 2. Why it exists
The limits (workers, permits, queue capacity) can be driven to their edges deterministically only if the "database work" is under the test's control: it can wait on a gate, sleep, or fail on demand. The stand-in is swapped in with `monkeypatch`, only inside the tests; no test logic exists in production code.

## 3. Tests
- `test_worker_and_semaphore_limits_are_reached_and_never_exceeded` — 4 workers, 2 permits, 20 requests: all 4 workers get busy but only 2 ever run the registration code (counted inside the stand-in and by the semaphore).
- `test_semaphore_covers_only_the_db_section_not_the_queue_or_the_workers` — 6 requests, 3 workers, 1 permit, blocked: 1 request holds the permit, 2 are on workers waiting for it, 3 are still in the queue.
- `test_queue_saturation_rejects_extra_requests_immediately_and_stays_bounded` — capacity 2, 1 busy worker: two requests queue, the next two are refused at once with `QUEUE_FULL`, depth and maximum depth never pass 2, refused requests never reach the database code, refusals are logged.
- `test_queue_wait_is_observable` — one worker, four 0.1 s jobs: queue waits grow (about 0, 100, 200, 300 ms) in both the log lines and the counters.
- `test_every_request_leaves_a_log_line_with_the_research_fields` — all fields present; configured limits recorded; times in order; start-up line logged.
- `test_exceptions_do_not_leak_permits_or_workers` — ordinary and database-type exceptions become `ERROR` results; afterwards the single permit and both workers still work (15 acquisitions, 0 held).
- `test_request_cancelled_while_queued_is_skipped`, `test_stop_finishes_accepted_requests_and_refuses_new_ones` — cancellation and graceful shutdown.
- `test_stop_while_workers_wait_for_a_permit_finishes_everything_and_leaks_nothing` — `stop()` is called while 1 request is inside the DB section, 2 workers wait for the permit and 3 requests are queued. A new request is refused at once; `stop()` waits instead of abandoning the accepted work; when the work can finish all 6 accepted requests succeed, no permit is left held or waited for, the queue's books balance, no worker is left alive, and nothing hangs.

## 4. Important variables
- `FakeRegistration` — the stand-in: optional `gate` (blocks until released), `seconds` (sleep), fails for student codes starting `BAD`/`DB`; counts calls and how many overlapped.
- `gate` / `make_layer` — fixtures; teardown opens the gate and stops every layer (with a short timeout), so a failing test cannot leave a worker blocked.

## 5. Limits
Not a database test: transaction correctness and no-overselling are tested in `test_os_layer_mysql.py`. These tests check timing with lower bounds only (a sleep is never shorter than asked), so they are not timing-fragile.
