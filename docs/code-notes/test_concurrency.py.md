# tests/test_concurrency.py

## 1. Purpose
Small, bounded concurrency correctness tests: a last-seat race, a same-student race, and 50 students competing for 10 seats.

## 2. Why it exists
Shows that the row lock works. This is a correctness check only; the real load generator is future work (Day 2).

## 3. Important functions/classes (tests)
- `test_one_seat_two_students_at_the_same_time` — creates a section with capacity 1 and two
  students. Two threads, each with its own session, wait on a `Barrier` so they start together,
  then both call `register_student`. Expects exactly one `SUCCESS` and one `FULL`, one registration
  row, and `available_seats == 0`. It does not care which student wins.

- `run_requests_together(requests, section_id)` — helper. Starts one thread per student code, each
  with its own session; a `Barrier` releases them all at once. Returns the results and any exception
  that escaped a thread (the tests require none).
- `test_same_student_twice_at_the_same_time` — the same student, same section (capacity 5), two
  simultaneous requests. Expects one `SUCCESS` and one `DUPLICATE`, one registration row, seats 5 → 4.
  The loser has usually waited on the lock, so it exercises the database `UNIQUE` constraint path.
- `test_fifty_students_compete_for_ten_seats` — 10 seats, 50 valid students plus 2 unknown student
  codes, 52 simultaneous requests. Checks: successes ≤ 10; final seats ≥ 0; successes + final seats = 10;
  one registration row per success and no other rows; no duplicate rows; nothing registered for unknown
  students; no `ERROR` results and no escaped exceptions. Exact outcome is also fixed: 10 `SUCCESS`,
  40 `FULL`, 2 `STUDENT_NOT_FOUND`. This is a correctness test, not a load generator.

## MySQL-only
The three concurrency tests are marked `requires_mysql` (see `conftest.py.md`): they rely on row-level locking and are
skipped on SQLite, where they would fail for reasons that belong to SQLite, not to ConcurrentReg.

## 4. Important variables
- `start_together` — the barrier that releases both threads at the same moment.
- `results` — maps each student code to its result.

## 5. Execution flow
Both requests reach `lock_section` for the same row; one waits until the other commits, then sees 0 seats.

## 6. Database behavior
Two simultaneous transactions on one section row; the second waits on `SELECT ... FOR UPDATE`.

## 7. Error handling
A failure here means overselling (two successes) or a lost request.

## 8. Testing
Tests the locking and constraint handling in `registration_service.py`. During the repair, removing the
lock made the suite fail on every run (15 of 15), and stopping the `IntegrityError` from being turned
into `DUPLICATE` made it fail on every run (30 of 30); with the real code it passed 30 of 30.
Limit: these are bounded tests (at most 52 simultaneous requests); they do not prove behaviour under
all workloads.
