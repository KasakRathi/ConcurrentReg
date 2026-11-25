# tests/test_os_components.py

## 1. Purpose
Unit tests of the three Day 3 building blocks and the settings, one at a time: the bounded queue, the DB semaphore, the worker pool, `OSLayerConfig`.

## 2. Why it exists
To show, before anything is combined, that each mechanism really limits what it claims to limit. The numbers (capacity 3 or 5, 3 workers, 2 permits) are test-fixture values, not research parameters.

## 3. What is covered
- **Bounded queue:** refuses items beyond capacity; 8 threads pushing 400 items into capacity 5 leave exactly 5; with producers and consumers racing, depth never passes capacity and nothing accepted is lost; FIFO order and space freed after a `get`; shutdown keeps accepted items and refuses new ones.
- **Semaphore:** 10 threads and 2 permits — the test counts for itself how many are inside; the most is exactly 2; waiting time is measured; after 5 failures inside the block no permit has leaked (run in a thread with a deadline, so a leak makes the test fail instead of hang).
- **Worker pool:** 12 jobs on 3 workers never run more than 3 at once and do reach 3; a handler that raises 5 times leaves every worker alive and the pool working; `stop()` finishes all accepted jobs and then refuses new ones; starting twice is refused.
- **Shutdown and bookkeeping (added in the verification repair):** idle workers blocked on an empty queue exit promptly when the pool stops; after jobs succeed or fail the queue's own count of unfinished jobs is 0 and `join()` returns (this test failed before the one-line `task_done()` repair, which is how the gap was found); the runtime provides `queue.Queue.shutdown` (Python 3.13+).
- **Settings:** invalid values are rejected; values are read from the environment; defaults are used when variables are missing; a bad value names its variable.

## 4. Important variables / helpers
- `make_counting_handler(seconds)` — a job handler that sleeps and records how many ran at once, measured independently of the pool's own counter.
- `pool_factory` — fixture that starts pools and always stops them at the end.
- `wait_until` — bounded polling (from `conftest.py`).

## 5. Limits
These tests use plain numbers as jobs. They show the mechanisms work in isolation, not that the combined layer is correct — see `test_os_request_pipeline.py` and `test_os_layer_mysql.py`. They run on any test database because they never use row locks.
