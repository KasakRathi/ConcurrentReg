# app/os_layer/request_pipeline.py

## 1. Purpose
The Day 3 OS concurrency layer, put together. `OSConcurrencyLayer` connects the bounded queue, the worker pool and the DB
semaphore to the unchanged Day 1 registration service, and records what happened to every request.

```
HTTP request -> submit() -> bounded queue -> worker thread -> DB semaphore -> register_student() -> MySQL/InnoDB
```

## 2. Why it exists
Each part has one job and lives in its own file (`bounded_queue.py`, `worker_pool.py`, `db_semaphore.py`). Something must
join them and own the lifecycle and the logging; that is this file. It is **not** itself an admission controller: it only offers a hook where an optional one (IASL, off by default) may refuse a request before the queue, and a hook that tells an observer the outcome afterwards.

## 3. Important classes/functions
- **`Job`** — one request on its way through: `request_id`, `student_code`, `section_id`, `enqueued_at`, `queue_depth_at_arrival`, `future`.
- **`OSConcurrencyLayer(config)`** — builds the queue, semaphore and pool from an `OSLayerConfig`.
  - **`start()` / `stop(timeout_seconds=30)`** — explicit startup and graceful shutdown.
  - **`submit(student_code, section_id)`** — the single entry point. Never waits. Returns a `Future` that will hold a `RegistrationResult`.
  - **`_process(job)`** — runs on a worker thread for each job (see flow below).
  - **`_run_registration(job)`** — opens a new `SessionLocal()`, calls Day 1 `register_student`, closes the session.
  - **`snapshot()`** — a copy of every counter (used by `GET /os-layer/status` and by the tests).
- **Result codes** `QUEUE_FULL`, `SHUTTING_DOWN` — outcomes that exist only because of this layer.

## 4. Important variables / configuration
- `config` — the three experimental settings (`layer_config.py`), copied into every log line so each line is self-describing.
- `enqueued_at`, `worker_started`, `semaphore_acquired`, `worker_finished` — readings of `time.perf_counter()` (a monotonic clock, as in Day 2, so durations are not affected by clock changes).
- `queue_wait` = worker started − enqueued. `semaphore_wait` = time spent waiting for a permit. `db_section_ms` = time inside the permit.

## 5. How requests move through the code
1. `main.py` receives the HTTP request and calls `layer.submit(student_id, section_id)`.
2. `submit` creates a `Job` with a new `request_id` and a `Future`.
   *(If an admission controller is installed (IASL on), it is asked here, before the queue; a refusal finishes the `Future` at once with `ADMISSION_REJECTED`. With none installed, every request is admitted and only the queue's capacity can turn one away.)*
3. `queue.try_put(job)`: `ADDED` → the request waits; `FULL` → the `Future` is finished at once with `QUEUE_FULL`; `SHUT_DOWN` → `SHUTTING_DOWN`. Refusals are logged as `os_layer_rejected`.
4. A free worker takes the job (`_process`): skips it if the caller cancelled; otherwise measures the queue wait.
5. `with db_semaphore.hold()`: waits for a permit, then `_run_registration` runs the Day 1 transaction.
6. The permit is released; `future.set_result(result)` answers the waiting HTTP request; then the queue wait is added to the totals and an `os_layer_request` log line is written.
7. `main.py` turns the result code into an HTTP status and JSON body.

## 6. How the queue works
See `bounded_queue.py.md`: fixed capacity, FIFO, refuses instead of waiting when full.

## 7. How workers work
See `worker_pool.py.md`: `worker_count` threads. Request-handling threads (the event loop) never run registrations.

## 8. How the semaphore works
See `db_semaphore.py.md`. It is taken after the worker has a job and released right after the registration returns, so it covers only the database work. Day 1's student lookup is a database read inside the same transaction, so it is inside the permit too; there is no separate non-database preparation step on Day 3.

## 9. DB sessions/transactions
- A new `SessionLocal()` is created and closed **on the worker thread, inside the permit**, for every job. Sessions and ORM objects are never shared between threads.
- Only plain values (text, numbers, a `Future`) cross from the HTTP layer to a worker; the FastAPI request object is never passed on.
- The transaction itself (student lookup, row lock, duplicate check, seat check, insert, seat decrease, one commit or rollback) is Day 1 `register_student`, unchanged. It begins and ends inside one call.
- `request_id` is passed into `register_student`, so the Day 1 `registration` log line and the `os_layer_request` line carry the same id.

## 10. What happens on errors
- Queue full → immediate `QUEUE_FULL` result; the request never reaches a worker.
- Day 1 returns `ERROR` itself for database errors. Any other exception inside the protected block is caught in `_process`, becomes an `ERROR` result ("Registration failed because of an internal error"), is logged, and the permit is still released (context manager). The worker survives.
- A request cancelled while still queued is skipped (`set_running_or_notify_cancel`), so it never reaches the database.
- The waiting request is answered **before** logging, so a logging problem cannot leave a request hanging.

## 11. What happens during shutdown
`stop()` shuts the queue down: later `submit` calls get `SHUTTING_DOWN`; requests already accepted are finished; workers then exit. A final `os_layer_stopped` line with all counters is logged. If workers are still running after the timeout their names are logged.

## 12. Tests
`tests/test_os_request_pipeline.py` (stand-in for `register_student`, so situations are exact): limits reached and not exceeded; semaphore covers only the DB section; queue saturation; queue wait; log fields; exception safety; cancellation; shutdown.
`tests/test_os_layer_mysql.py` (real MySQL/InnoDB): no overselling, duplicates, last seat, and the Day 2 workload generator driving the Day 3 server.

## 13. What this file does NOT implement
No admission policy of its own (it only calls the optional, duck-typed IASL hook; the policy lives in `app/iasl/`), no retries, no priority scheduling, no server-side request timeout, no payment, no temporary registration storage.

### Observability: fields of the `os_layer_request` log line
`request_id`, `student_id`, `section_id`, the three configured limits, `worker`, `queue_depth_at_arrival`, `enqueued_at_s`, `queue_wait_ms`, `worker_started_at_s`, `semaphore_wait_ms`, `semaphore_acquired_at_s`, `db_section_ms`, `worker_finished_at_s`, `worker_total_ms`, `result`, `error`. Times ending `_s` are seconds since the layer started (comparable between lines, so overlap of workers can be worked out from a log).

### Unresolved decisions (not decided in the Master MD)
- HTTP response for a full queue (provisional 503 in `main.py`).
- Final queue ordering/fairness policy (FIFO used for now).
- Exact boundary of the DB critical section (the whole registration call is used for now).
- Behaviour under worker saturation (requests simply wait in the queue until it is full).
