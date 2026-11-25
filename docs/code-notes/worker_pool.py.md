# app/os_layer/worker_pool.py

## 1. Purpose
The server-side worker pool: a fixed number of threads that take jobs off the queue and run them.

## 2. Why it exists
It bounds how many requests are processed at the same time on the server. This is **not** the thread pool inside the Day 2
workload generator (that one only creates client traffic). Request-handling threads do not run registrations; the workers do.

## 3. Important classes/functions
- **`WorkerPool(work_queue, worker_count, handle_job)`** — it knows nothing about registrations; it only calls `handle_job(job)` for each job.
- **`start()`** — creates `worker_count` threads named `worker-1 … worker-N`. Starting twice raises an error.
- **`stop(timeout_seconds=30)`** — graceful stop; returns the names of any workers still running afterwards.
- **`alive_workers()`** — how many worker threads are still alive (would show if a worker had died).
- **`_worker_loop()`** — each thread: wait for a job (`get()`), run it, repeat; leave when the queue is shut down and empty.
- **`_run_one(job)`** — counts the worker as active, calls `handle_job`, catches errors, counts it as finished, and finally tells the queue the job is done (`task_done()`), also when the job failed.

## 4. Important variables
- `worker_count` — how many threads exist. `active` — workers running a job now. `max_active` — the highest ever.
- `jobs_started`, `jobs_finished` — totals. `unexpected_errors` — how often `handle_job` raised and the worker survived.
- The queue's own `unfinished_tasks` — jobs taken from the queue and not yet marked done. Since the Day 3 verification repair it returns to 0 when the workers are idle. Before, `task_done()` was never called, so it only grew (measured: 5 after 5 finished jobs) and `queue.join()` could never have returned. Nothing used `join()`, so no behaviour was wrong; it was a latent trap, fixed with one line.

## 5. How requests move through the code
Queue → `get()` in a worker thread → `handle_job(job)` (the layer's `_process`) → back to waiting on the queue.

## 6. Queue
Workers are the consumers of the bounded queue.

## 7. How workers work
They are plain `threading.Thread` objects (daemon threads, so a crashed process is not kept alive by them). The number never changes while running.
A worker that is waiting for a semaphore permit still counts as active.

## 8. Semaphore
Not used here; `handle_job` takes the permit.

## 9. DB sessions/transactions
None here. Each job opens and closes its own session inside `handle_job`; sessions are never shared between workers.

## 10. What happens on errors
Any `Exception` from `handle_job` is logged and counted, and the worker carries on, so one bad job cannot shrink the pool. (`alive_workers()` would reveal a worker lost to something worse.)

## 11. What happens during shutdown
`stop()` shuts the queue down, then waits (up to the timeout) for each worker to finish the jobs already accepted and leave.

## 12. Tests
`tests/test_os_components.py`: 12 jobs on 3 workers never run more than 3 at once and do reach 3; a handler that raises 5 times leaves all workers alive and the pool still works; the queue's books balance after jobs succeed or fail (`unfinished_tasks == 0`, `join()` returns); `stop()` finishes all accepted jobs; idle workers waiting on an empty queue are woken and exit in well under 2 s; starting twice is refused.
`tests/test_os_request_pipeline.py` / `tests/test_os_layer_mysql.py`: worker bound through the whole layer, and over HTTP against MySQL (see `test_os_layer_mysql.py.md`).
Requires Python 3.13+ (`queue.Queue.shutdown`); `test_runtime_provides_queue_shutdown` checks the runtime (verified: Python 3.14.6).

## 13. What this file does NOT implement
No resizing, no restarting dead workers, no priorities, no per-job timeout.
