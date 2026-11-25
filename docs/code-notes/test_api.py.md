# tests/test_api.py

## 1. Purpose
Checks the HTTP layer of `POST /registrations`.

## 2. Why it exists
Confirms the exact JSON bodies and HTTP status codes promised in the README.

## 3. Important functions/classes (tests)
- `test_post_registration_then_duplicate` — first call 201 with success message; second call 409 with the duplicate message.
- `test_post_unknown_student_is_404` — unknown student gives 404 and `success: false`.
- `test_full_queue_is_answered_with_the_provisional_503` — makes the layer report a full queue and checks the provisional 503 body. The queue-full response is not decided in the Master MD.
- `test_request_arriving_after_shutdown_began_gets_503_and_registers_nothing` — after the layer has begun shutting down, a request gets 503 "Server is shutting down" and no registration is stored.
- `test_status_endpoint_reports_configuration_and_counters` — `GET /os-layer/status` echoes the configuration and counts the request that was just made.

## 4. Important variables
- `client` (fixture) — FastAPI's `TestClient` used as a context manager (`with TestClient(app)`). That is required since Day 3: entering the context runs the app's start-up, which starts the OS-layer workers, and leaving it stops them. The app uses the development defaults (or the environment variables).

## 5. Execution flow
HTTP-style request → `main.py` → OS layer (queue → worker → semaphore) → service → test MySQL database.

## 6. Database behavior
Writes a real registration into the test database; the fixture resets it afterwards.

## 7. Error handling
Verifies that error outcomes are clean JSON, not stack traces.

## 8. Testing
Tests `main.py` and `schemas.py`.
