# tests/test_registration.py

## 1. Purpose
Checks the registration service one scenario at a time (no HTTP involved).

## 2. Why it exists
Proves each correctness rule: exactly one seat per registration, no duplicates, no registration
when full or when student/section is invalid, and no partial writes after a failure.

## 3. Important functions/classes (tests)
- `test_successful_registration` — one registration row, seats 5 → 4.
- `test_duplicate_registration` — second attempt rejected; one row; seats decreased once.
- `test_course_full` — seats set to 0; rejected; no row; seats stay 0.
- `test_invalid_student` / `test_invalid_section` — rejected; no row; seats unchanged.
- `test_unique_constraint_is_handled_cleanly_when_the_duplicate_check_misses` — registers once, then
  makes the application duplicate check wrongly answer "no" (monkeypatch, test only) and registers
  again. The database constraint must reject the insert; the result is `DUPLICATE`, one row, seats
  decreased once.
- `test_failure_in_the_middle_rolls_everything_back` — replaces `decrease_available_seats` (via
  `monkeypatch`, only inside the test) with a function that flushes the INSERT to the database
  and then raises. Verifies the INSERT was rolled back and seats are still 5.

## MySQL-only test
`test_unique_constraint_is_handled_cleanly_when_the_duplicate_check_misses` is marked `requires_mysql`: the service
recognises a duplicate by the constraint name inside MySQL's error text, and SQLite words that message differently
(on SQLite the result is `ERROR`, not `DUPLICATE`). The other registration tests run on any supported database.

## 4. Important variables
- `section` / `section.id` — the `CSE301` section (capacity 5) used by most tests.

## 5. Execution flow
Each test starts from the freshly seeded database, calls `register_student`, then re-reads the database.

## 6. Database behavior
Tests read the real MySQL database; they assert on committed state, not on Python objects.

## 7. Error handling
The rollback test deliberately triggers a database-style error and expects result code `ERROR`.

## 8. Testing
These *are* the tests for `registration_service.py`, `models.py` (constraints) and `seed.py`.
