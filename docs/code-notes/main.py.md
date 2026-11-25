# app/main.py

## 1. Purpose
Defines the FastAPI application: `POST /registrations`, a read-only `GET /os-layer/status`, and the start-up / shutdown of the OS concurrency layer.

## 2. Why it exists
It is the entry point from the outside world. It contains no registration logic and does no database work: it hands the request to the OS layer (`app/os_layer/`) and turns the answer into an HTTP response.

## 3. Important functions/classes
- **`create_app(os_config=None, iasl_config=None)`** — builds the app. A `lifespan` function starts the layer (workers) at start-up and stops it at shutdown. If `os_config` / `iasl_config` is `None` the settings are read from environment variables when the server starts; tests pass their own. IASL (optional admission control) is built, attached and started here only when `IASL_ENABLED` is true; otherwise `app.state.iasl` is `None` and nothing changes. The read-only `/iasl/*` routes come from `iasl_api.py`.
- **`app`** — the application object that uvicorn runs (`app.main:app`).
- **`create_registration(request, response, http_request)`** — an `async` endpoint. Calls `layer.submit(...)`, then `await asyncio.wrap_future(...)` for the worker's answer, sets the HTTP status from `HTTP_STATUS`, and returns `{success, message}`. The event loop is free while it waits, because the work happens on worker threads.
- **`os_layer_status(http_request)`** — returns `layer.snapshot()`: configured limits and live counters (queue depth and maximum, accepted/rejected, active and maximum workers, semaphore holders and waiters, queue wait totals). It is for measurements and is not part of the registration contract.
- **`HTTP_STATUS`** — result code → status: success 201; duplicate 409; full course 409; unknown student/section 404; database or internal error 500; `QUEUE_FULL` 503; `SHUTTING_DOWN` 503.

## 4. Important variables
- `http_request.app.state.os_layer` — the running `OSConcurrencyLayer`, created in the lifespan function.
- `result.code` — the outcome, used only to choose the HTTP status.

## 5. How requests move through the code
HTTP request → FastAPI validates the body (`schemas.py`) → `create_registration` → `layer.submit` → queue → worker → semaphore → Day 1 `register_student` → result → status code + JSON.
The old `get_db` session dependency is no longer used by this endpoint: the worker opens its own session.

## 6. How the queue works / 7. workers / 8. semaphore
See the notes of `bounded_queue.py`, `worker_pool.py` and `db_semaphore.py`.

## 9. DB sessions/transactions
None here. A session is created per job on a worker thread (see `request_pipeline.py.md`); the request object and sessions never cross threads.

## 10. What happens on errors
Day 1 outcomes keep their old statuses and bodies. Raw database errors and stack traces are never sent to the client.
**Provisional, undecided:** the Master MD does not say how a full queue should be reported. `QUEUE_FULL` is answered `503` with `{"success": false, "message": "Request queue is full"}` only so that the request gets an answer. The one place to change it is `HTTP_STATUS` (and the matching line in `workload_generator.py`).
A bad `QUEUE_CAPACITY`/`WORKER_COUNT`/`DB_SEMAPHORE_PERMITS` value makes start-up fail with a clear message.

## 11. What happens during shutdown
The lifespan function calls `layer.stop()` (in a thread, so the event loop is not blocked): new requests are refused with 503, requests already accepted are finished, workers exit.

## 12. Testing
`tests/test_api.py` (status codes and bodies, the provisional queue-full 503, the status endpoint, using `TestClient` as a context manager so start-up/shutdown run); `tests/test_workload_live.py`, `tests/test_os_layer_mysql.py` (real HTTP server).

## 13. What this file does NOT implement
No authentication and no per-request server timeout. It contains no admission logic itself: the optional IASL admission controller lives in `app/iasl/` and the hook in `os_layer/request_pipeline.py`; `main.py` only wires it up (off by default) and maps its refusal to HTTP 503. (The demo endpoints added later live in `demo_api.py`.)

## Added after Day 3: demo controls

`create_app` also includes `demo_api.info_router` (always on, read-only) and `demo_api.router` (404 unless `CREG_DEMO_CONTROLS=1`). Nothing else in this file changed. See `docs/code-notes/demo_api.py.md`.
