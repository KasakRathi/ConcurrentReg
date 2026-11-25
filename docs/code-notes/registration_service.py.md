# app/registration_service.py

## 1. Purpose
Contains the registration logic: the one place that decides whether a student gets a seat.

## 2. Why it exists
Seat allocation must be correct under simultaneous requests. Keeping the whole transaction in one
small file makes the transaction boundary and the locking easy to see and explain.

## 3. Important functions/classes
- **`register_student(db, student_code, section_id, request_id=None)`** — public entry point. Input: a session, the
  `STU001`-style code, the section id. Output: a `RegistrationResult`. Adds one JSON log line per
  call, and catches database errors so callers never see raw exceptions.
- **`_register(...)`** — the actual single-transaction flow (below).
- **`lock_section`** — `SELECT ... FOR UPDATE` on one section row.
- **`is_already_registered`** — readable duplicate check.
- **`decrease_available_seats`** — subtracts 1 from `available_seats`. It is its own tiny function
  so the rollback test can make it fail on purpose without any test code in the real logic.
- **`RegistrationResult`** — `code` (`SUCCESS`, `DUPLICATE`, `FULL`, `STUDENT_NOT_FOUND`,
  `SECTION_NOT_FOUND`, `ERROR`) plus a `message`.

## 4. Important variables
- `student_code` — the text code of the student attempting registration.
- `student.id` (`student_pk`) — the student's numeric key, stored in the registrations table.
- `section_id` — the section whose seat allocation is being processed.
- `section.available_seats` — how many seats are free right now (read *after* locking, so it is trustworthy).
- `request_id` — ID that ties together the log line for one request. It is generated here unless the caller passes one; the Day 3 OS layer passes its own so the `registration` log line and the `os_layer_request` line match. (Day 3 added only this optional argument; the transaction logic is unchanged.)

## 5. Execution flow
The whole request is **one transaction**. It begins at the first query and ends with exactly one
commit (success) or one rollback (every other outcome).
1. Look up the student. Missing → rollback, `STUDENT_NOT_FOUND`.
2. Lock the section row (`SELECT ... FOR UPDATE`). No row → rollback, `SECTION_NOT_FOUND`.
   The lock query doubles as the "does this section exist" check, so the section is read only once.
3. Already registered? → rollback, `DUPLICATE`.
4. No seats? → rollback, `FULL`. (`available_seats` is read after the lock, so it is trustworthy.)
5. Insert the registration, decrease seats by 1, **commit**, `SUCCESS`.

The duplicate check in step 3 is an ordinary read. Because the transaction started at step 1
(before we waited for the lock), MySQL may answer it from an older snapshot and miss a registration
that another request committed while we waited. That is fine: the `UNIQUE(student_id, section_id)`
constraint rejects the insert in step 5, and the `IntegrityError` handler answers `DUPLICATE`.
The concurrent same-student test shows this path is really used.

## 6. Database behavior
- Reads: `students`, `course_sections`, `registrations`.
- Writes: one `registrations` INSERT and one `course_sections` UPDATE, in the same transaction.
- Locking: `lock_section` locks only that one section row. A second request for the same section
  waits there until the first commits or rolls back, then sees the updated seat count. Other
  sections are not affected. A request for an unknown student never reaches the lock.
- Commit: only after both writes succeed. Rollback: on every other outcome and on any database error.
- Seats are never changed without the matching registration row, and vice versa.

## 7. Error handling
- Duplicate found by the check → `DUPLICATE`. If a concurrent duplicate slips past the check, the
  `UNIQUE` constraint raises `IntegrityError` at insert time; we roll back (so the registration and
  the seat change both disappear) and also answer `DUPLICATE`. No database text reaches the client.
- Any other `SQLAlchemyError` (e.g. deadlock, lost connection) → rollback, `ERROR`. The detail
  goes to the log only. **There are no automatic retries on Day 1.**

## 8. Testing
`test_registration.py` (success, duplicate, full, invalid student, invalid section, rollback after a
simulated mid-transaction crash, constraint-handled duplicate) and `test_concurrency.py` (one seat /
two students, same student twice, 50 students for 10 seats).
