# tests/test_os_layer_mysql.py

## 1. Purpose
Tests the Day 3 OS layer together with the real Day 1 registration transaction on MySQL/InnoDB, including the Day 2 workload generator acting as the clients. The whole file is marked `requires_mysql`: it is skipped, with a visible reason, on any other database.

## 2. Why MySQL/InnoDB is required
No-overselling depends on InnoDB row locks (`SELECT ... FOR UPDATE`). SQLite has none, so these results would mean nothing there (see `conftest.py.md`).

## 3. Tests (10)
Correctness through the layer
- `test_concurrent_registrations_through_the_layer_never_oversell` — 30 students, a 10-seat section, 6 workers, 3 permits: exactly 10 `SUCCESS` and 20 `FULL`; 10 rows, 0 seats left; counters stay within the limits.
- `test_same_student_twice_at_once_through_the_layer_registers_once` — one `SUCCESS`, one `DUPLICATE`, one row, seats 5 → 4.

End-to-end through every Day 3 layer, over HTTP, with the Day 2 generator as the clients
- `test_capacity_one_end_to_end_through_every_day3_layer` (two configurations) — a section with exactly **one seat**, 8 simultaneous clients. The test holds the section's row lock (backend untouched), waits until the server's own counters show the saturated state, then releases the lock. Configuration "every-request-fits": 8 requests accepted by a queue of 8, 4 workers, 2 permits. Configuration "queue-overflows": a queue of 2, 2 workers, 1 permit, so the queue turns requests away. It checks:
  - **Correctness:** exactly 1 `SUCCESS`; every other accepted request `COURSE_FULL`; the rest `QUEUE_FULL`; 0 seats left; exactly 1 registration row; no duplicate rows; the stored row belongs to the client that was told `SUCCESS`.
  - **Queue:** accepted + refused = 8; accepted ≤ workers + capacity; depth and maximum depth never above capacity; refusals happen exactly when the queue cannot hold everything.
  - **Workers:** while blocked, active = min(workers, accepted); the maximum reached the configured number and never went above it; every accepted job started and finished; no worker died.
  - **Semaphore:** while blocked, holders = min(permits, active); maximum holders = permits; acquisitions = number of accepted requests; at the end no permit is held and none is waited for.
  - **Overlap:** client-side peak in flight ≥ accepted (and more than the server's workers when accepted > workers).
  - **Logs:** one `os_layer_request` line per accepted request, one `os_layer_rejected` per refusal; the same request ids appear in Day 1's `registration` log lines (so the Day 1 service ran for exactly the accepted requests); workers named only within the configured set; the configured limits on every line; the peak number of busy workers and of requests inside the DB section, worked out from the log times alone, equals what the counters say.
  - **Environment:** MySQL dialect, test database, InnoDB tables.
- `test_innodb_never_sees_more_blocked_transactions_than_the_semaphore_allows` — the same scenario with 4 workers and 2 permits. Reading `information_schema.innodb_trx` (polled every 0.25 s), InnoDB reports exactly 2 transactions in `LOCK WAIT` while 4 workers are busy, and never more than 2. This is the database's own view that the semaphore bounds the protected DB concurrency. Needs the PROCESS privilege; without it the test is skipped with that reason.
- `test_last_seat_over_http_with_day2_clients_does_not_oversell` — the earlier, simpler capacity-1 test (outcomes only).
- `test_day2_clients_saturate_the_server_side_limits` — queue 4, 3 workers, 2 permits, 12 clients, CSE301 (5 seats): saturated state, conservation (accepted + refused = 12), bounds reached and not exceeded, database consistent.
- `test_day2_burst_without_any_artificial_hold_respects_the_limits` — 40 requests from 20 client threads, no hold: the server never exceeded 4 workers or 2 permits (read through `GET /os-layer/status`).

Real failures inside MySQL (not simulated database behaviour)
- `test_a_real_mysql_error_inside_the_db_section_leaks_neither_permit_nor_worker` — a worker is blocked on the row lock inside the DB section; the test KILLs that worker's MySQL connection. Day 1 reports it as `ERROR`; the permit passes to the waiting request, which then succeeds; both workers survive; only the second request's registration exists and seats are 4.
- `test_unexpected_error_while_holding_a_real_row_lock_releases_lock_permit_and_worker` — a Python error is injected (by `monkeypatch`, in the test only) right after the worker's transaction took the row lock, so an exception that Day 1 does not handle travels up through the permit. With one worker and one permit, the next request still completes (it would hang until MySQL's 50 s lock timeout if the lock, permit or worker had leaked), and the failed transaction left nothing behind.

## 4. Client concurrency versus server concurrency
The generator's client threads are **client** concurrency. The layer's counters (`max_active`, `max_in_critical_section`, `max_depth`) and InnoDB's lock-wait list are **server** concurrency. The tests assert the client side had more requests in flight than the server had workers whenever more requests were accepted than there are workers.
The lock-hold is what makes the server limits *reachable* deterministically (the Day 2 technique). Waiting for the saturated state is done by polling the counters, not by fixed sleeps. Without a hold, a fast database may finish each request before others arrive, so `test_day2_burst_without_any_artificial_hold_respects_the_limits` only checks that limits were not exceeded.

## 5. Limits
Counts are small test-fixture values (8 clients, 4 workers, ...), not research parameters. How many requests are accepted when the queue overflows depends on arrival timing, so those tests assert bounds and conservation, not one exact number. None of this measures performance or capacity. No test here removes the Day 1 row lock to prove that overselling would then occur; an earlier temporary experiment is not part of this evidence.
