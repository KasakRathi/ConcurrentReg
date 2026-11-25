# tests/conftest.py

## 1. Purpose
Shared test setup: points the app at the test database and gives every test a clean, seeded database.

## 2. Why it exists
The tests delete and recreate all tables. This file makes sure that can only ever happen to a
database whose name ends in `_test`, and that tests do not affect each other.

## 3. Important functions/classes
- **module start-up check** — requires `TEST_DATABASE_URL` ending in `_test`, then copies it into
  `DATABASE_URL` *before* the app is imported. Otherwise it raises and nothing runs.
- **`fresh_database`** (automatic fixture) — drop tables, recreate, seed. Runs before every test.
- **`db`** — a session for the test body.
- **`get_section(db, code)`**, **`count_registrations(db, section_id)`** — helpers that read the
  latest committed data (they `rollback()` first to discard any old snapshot).

- **`DATABASE_DIALECT`** — `"mysql"`, `"sqlite"`, … taken from the engine actually in use. Printed in the pytest header.
- **`requires_mysql`** — a skip marker for tests that only mean something with MySQL/InnoDB row locks. On another
  database the test is **skipped with a visible reason**, not silently dropped and not reported as passed.
- **`start_server`** (fixture, a factory) — starts the real FastAPI app (`create_app(os_config)`) with uvicorn in a background
  thread on a free local port, using the test database, and returns `(url, os_layer)`. Because the server runs inside the test
  process, a test can read `os_layer.snapshot()` directly to see what the *server* did. Every server is stopped at the end of the test.
- **`server_url`** (fixture) — `start_server` with `GENEROUS_OS_CONFIG`; used by the Day 2 live tests and the Day 2 MySQL test.
- **`GENEROUS_OS_CONFIG`** — queue 64, 8 workers, 8 permits: test-fixture values that are large enough that the Day 3 layer never
  constrains the Day 1/Day 2 tests, so those tests keep meaning what they meant before. They are not research parameters.
- **`wait_until(condition, timeout_seconds)`** — polls until a condition holds (or the timeout passes); used instead of fixed sleeps.
- **`peak_overlap(intervals)`**, **`log_events(caplog, logger_name, event_name)`**, **`count_innodb_lock_waits()`** — helpers for the Day 3 end-to-end evidence: the most intervals overlapping at one moment (used on times read from log lines), the JSON log lines of one kind captured during a test, and how many transactions InnoDB reports in `LOCK WAIT` (needs the PROCESS privilege; InnoDB serves a cached list if read more often than about every 0.1 s, so callers poll slower).
- **`add_students(db, first, last)`** — adds students `STU011…` so tests can use more students than the 10 in the seed data.
- **`max_requests_in_flight(results)`** — from recorded start/end offsets, the largest number of requests overlapping at one moment.

## SQLite note
The guard only checks that the database name ends in `_test`, so a SQLite file such as `sqlite:///concurrent_test`
is accepted. That is allowed on purpose for quick local checks, but SQLite has no row-level locks: with it,
concurrent seat updates overwrite each other (observed: 50 successes for 10 seats). Those tests are therefore
marked `requires_mysql`. This describes SQLite, not a defect in the MySQL implementation.

## 4. Important variables
- `TEST_DATABASE_URL` — which database the tests may wipe.

## 5. Execution flow
pytest loads this file first, then runs each test with a fresh database.

## 6. Database behavior
Drops/creates all tables and inserts seed data once per test.

## 7. Error handling
Refuses to run if the test database name is unsafe.

## 8. Testing
It is test infrastructure; it is exercised by every test.
