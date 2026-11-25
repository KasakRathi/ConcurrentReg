# app/os_layer/layer_config.py

## 1. Purpose
Holds the three settings of the Day 3 OS concurrency layer and reads them from environment variables.

## 2. Why it exists
Queue capacity, worker count and semaphore permits are **experimental parameters** (Master MD: fixed during one run,
varied between runs). They must be changeable without editing code, and they must not be scattered around the program.

## 3. Important classes/functions
- **`OSLayerConfig`** — a small frozen dataclass with three fields. It refuses anything that is not a whole number of at least 1.
- **`OSLayerConfig.from_environment()`** — builds the settings from `QUEUE_CAPACITY`, `WORKER_COUNT` and `DB_SEMAPHORE_PERMITS`; a missing variable uses the default.
- **`_read_whole_number(name, default)`** — reads one variable; a non-number raises `ValueError` that names the variable.

## 4. Important variables / configuration
- `queue_capacity` (`QUEUE_CAPACITY`) — the most requests that may wait in the queue. Default 16.
- `worker_count` (`WORKER_COUNT`) — how many server worker threads exist. Default 4.
- `db_semaphore_permits` (`DB_SEMAPHORE_PERMITS`) — how many workers may be inside the database section at once. Default 2.
- The defaults are **development defaults** so the server can start. They are not experimental conclusions and not recommendations.
- Choosing permits: it is meant to be informed by what the database can serve at once. The SQLAlchemy pool in `database.py` allows 60 connections (20 + 40 overflow), so permits above 60 would just make workers wait on the pool instead.

## 5. How requests move through the code
They do not. The settings are read once, when the server starts (`main.create_app`), and stay fixed for the whole run.

## 6. How the queue works / 7. workers / 8. semaphore
This file only supplies the numbers: the capacity of the queue (`bounded_queue.py`), the number of threads (`worker_pool.py`) and the number of permits (`db_semaphore.py`).

## 9. DB sessions/transactions
None.

## 10. What happens on errors
A bad value raises `ValueError` and the server refuses to start ("Application startup failed"), so a mistyped experiment setting can never run silently with a wrong value.

## 11. What happens during shutdown
Nothing.

## 12. Tests
`tests/test_os_components.py`: invalid values are rejected; values are read from the environment; missing variables use the defaults; a bad value names its variable.

## 13. What this file does NOT implement
No automatic tuning, no values chosen as "best", no changing these three numbers while the server runs. (The optional IASL layer moves a separate admission limit; it does not resize the queue, workers or semaphore.)
