# app/os_layer/bounded_queue.py

## 1. Purpose
The bounded queue: the waiting room for requests that are accepted but not yet being worked on.

## 2. Why it exists
Without a bound, a burst of requests would pile up without limit. The queue has a fixed capacity, so when it is full the
next request is refused immediately. Under the Master MD the queue is separate from admission control: it only stores
requests that were let in; it does not decide who gets in.

## 3. Important classes/functions
- **`BoundedRequestQueue(capacity)`** — a subclass of Python's `queue.Queue(maxsize=capacity)`. The standard library enforces the upper bound.
- **`try_put(item)`** — adds the item **without waiting**. Returns `ADDED`, `FULL` (no room) or `SHUT_DOWN` (the queue was closed).
- **`_put(item)`** — an internal hook that `queue.Queue` runs while holding its own lock. We use it to update `accepted` and `max_depth`, so those numbers are exact, not approximate.

## 4. Important variables
- `capacity` — the most items that may wait. `qsize()` — how many wait right now (the current depth).
- `max_depth` — the largest depth ever seen. It can never be above `capacity`.
- `accepted` — how many items entered. `rejected_full`, `rejected_shut_down` — how many were turned away, and why.

## 5. How requests move through the code
`OSConcurrencyLayer.submit` calls `try_put(job)`. Workers call `get()` (inherited from `queue.Queue`) and take jobs **first in, first out**.
FIFO is the simplest deterministic order; the Master MD still lists the final ordering/fairness policy as open.

## 6. How the queue works
Producers (`try_put`) never wait: if the queue holds `capacity` items the item is refused and counted. Consumers (`get`) wait while it is empty.
Because the bound belongs to `queue.Queue`, the queue cannot silently turn into an unbounded list.

## 7. Workers / 8. Semaphore
Workers are the consumers (see `worker_pool.py`). A queued request holds no semaphore permit.

## 9. DB sessions/transactions
None. Jobs contain only plain values (text, numbers, a `Future`), never a database session.

## 10. What happens on errors
A full queue is not an error in the code: it returns `FULL`, and the caller turns that into the `QUEUE_FULL` result. The external HTTP meaning of that is **not decided** yet (see `main.py.md`).

## 11. What happens during shutdown
`queue.shutdown()` (Python 3.13+): new puts return `SHUT_DOWN`; items already accepted can still be taken; once empty, `get()` raises `queue.ShutDown`, which tells a worker to exit.

## 12. Tests
`tests/test_os_components.py`: refuses items beyond capacity; 8 producers pushing 400 items into capacity 5 leave exactly 5 inside; depth never passes capacity while producers and consumers race; FIFO; shutdown keeps accepted items and refuses new ones.
`tests/test_os_request_pipeline.py` and `tests/test_os_layer_mysql.py`: saturation through the whole layer and through HTTP.

## 13. What this file does NOT implement
No admission decision, no priorities, no waiting time limit in the queue, no changing capacity while running.
