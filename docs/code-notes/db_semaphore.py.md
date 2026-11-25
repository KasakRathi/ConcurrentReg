# app/os_layer/db_semaphore.py

## 1. Purpose
The DB semaphore: it limits how many workers may be inside the database section at the same time.

## 2. Why it exists
The worker pool limits how many requests are *being processed*; the semaphore limits how many of them are *using the
database at once*. They are separate dials (Master MD, Decision 5). If many workers pile onto one hot course row,
the semaphore keeps the number of waiting database transactions low.

## 3. Important classes/functions
- **`DbSemaphore(permits)`** — wraps `threading.BoundedSemaphore(permits)`; a bounded semaphore raises an error if a permit were ever given back twice.
- **`hold()`** — a context manager used as `with semaphore.hold() as waited:`. It waits for a permit, runs the block, and **always** gives the permit back, even if the block raises. It yields how many seconds the caller waited.

## 4. Important variables
- `permits` — the configured limit. `in_critical_section` — workers holding a permit now. `max_in_critical_section` — highest ever (never above `permits`).
- `waiting` / `max_waiting` — workers blocked waiting for a permit. `acquisitions`, `wait_total_s`, `wait_max_s` — totals for measurements.
- When a permit is released the counter goes down **before** the permit is freed, so the counter can never read higher than the real limit.

## 5. How requests move through the code
A worker (in `request_pipeline._process`) wraps only the registration call in `with self.db_semaphore.hold():`.

## 6. Queue / 7. Workers
Not involved. A request waiting in the queue holds no permit. A worker that has taken a job but is waiting for a permit holds none either; it is just waiting.

## 8. How the semaphore works
Permits start at `permits`. `hold()` takes one (waiting if none is free), the protected block runs, and the permit is returned in a `finally`. The semaphore guards **only the database work**, not the whole request lifecycle.

## 9. DB sessions/transactions
It does not touch the database. The worker creates the session, runs the Day 1 transaction and closes the session **inside** the permit, so the number of database connections in use cannot exceed the permit count.

## 10. What happens on errors
An exception inside the block still releases the permit (`finally`). If the wait itself is interrupted, the `waiting` counter is repaired and no permit is taken.

## 11. What happens during shutdown
Nothing special: workers finish their jobs (and so release permits) before they exit.

## 12. Tests
`tests/test_os_components.py`: with 2 permits and 10 threads, at most 2 are ever inside (counted independently by the test) and exactly 2 are reached; waiting time is measured; a permit is returned after 5 failures (the test fails, not hangs, if one leaks).
`tests/test_os_request_pipeline.py`: with 4 workers and 2 permits only 2 ever run the registration code at once; only the worker inside the section holds a permit; exceptions do not leak permits.

## 13. What this file does NOT implement
No automatic choice of permits from the database's capacity, no timeout while waiting for a permit, no fairness rules beyond what Python's semaphore does.
