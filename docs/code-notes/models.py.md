# app/models.py

## 1. Purpose
Defines the three database tables as Python classes: `Student`, `CourseSection`, `Registration`.

## 2. Why it exists
The table layout, and the database rules attached to it, are what make registration safe even
if application code has a bug.

## 3. Important functions/classes
- **`Student`** (`students`) — `id` (numeric key), `student_id` (unique text code like `STU001`), `name`.
- **`CourseSection`** (`course_sections`) — `id`, `course_code`, `course_name`, `capacity`,
  `available_seats`. Has a CHECK: `0 <= available_seats <= capacity`.
- **`Registration`** (`registrations`) — `id`, `student_id`, `section_id`, `registered_at`, `status`.
  Has a UNIQUE constraint on `(student_id, section_id)`.

## 4. Important variables
- `capacity` — the maximum number of students the section can hold. Never changes during registration.
- `available_seats` — how many seats are currently free. Goes down by exactly 1 per successful registration.
- `Registration.student_id` — the numeric `students.id` (a foreign key), **not** the `STU001` text.
  This is easy to confuse with `Student.student_id`; the service keeps them apart as `student_code` and `student_pk`.
- `status` — always `REGISTERED` on Day 1. `registered_at` — time the row was created.

## 5. Execution flow
`register_student` reads/writes these classes. `seed.py` and the tests create the tables from them
(`Base.metadata.create_all`).

## 6. Database behavior
Declares constraints only; nothing is read or written here:
- `UNIQUE(student_id, section_id)` — the database refuses a second registration of the same
  student in the same section, even if two requests race.
- `CHECK(available_seats >= 0 AND available_seats <= capacity)` — the database refuses an impossible seat count.
- Foreign keys — a registration must point at a real student and a real section.

## 7. Error handling
Breaking a constraint makes MySQL raise an error. The service turns the duplicate case into a clean
"already registered" answer and any other case into a generic error plus rollback.

## 8. Testing
`test_registration.py` (duplicate, full, etc.) and `test_concurrency.py` exercise these rules.
