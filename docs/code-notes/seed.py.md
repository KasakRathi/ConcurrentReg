# app/seed.py

## 1. Purpose
Loads small, **made-up development/test data** and can reset the database to a known state.

## 2. Why it exists
Tests and demos need the same predictable starting data every time.

## 3. Important functions/classes
- **`seed_dev_data(db)`** — input: a session. Adds 10 students (`STU001`–`STU010`) and two sections:
  `CSE301` (capacity 5, 5 free) and `CSE302` (capacity 2, 2 free). Output: none. Commits.
- **`reset_and_seed()`** — drops all tables, recreates them, then calls `seed_dev_data`.
  Run with `python -m app.seed`.

## 4. Important variables
- `capacity` / `available_seats` — start equal, because nobody is registered yet.

## 5. Execution flow
Run manually before starting the API; the test fixture also calls `seed_dev_data` before each test.

## 6. Database behavior
`reset_and_seed` **drops every table** in `DATABASE_URL` — never point it at data you want to keep.
`seed_dev_data` inserts students and sections in one commit.

## 7. Error handling
None special; a database error stops the script with a traceback (it is a developer tool).

## 8. Testing
Used by the `fresh_database` fixture in `conftest.py`; nearly every test relies on it.
