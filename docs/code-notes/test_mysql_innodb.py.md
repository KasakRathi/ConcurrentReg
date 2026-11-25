# tests/test_mysql_innodb.py

## 1. Purpose
The MySQL/InnoDB-specific verification of the registration concurrency behaviour. The whole file is marked
`requires_mysql`: on any other database it is skipped with a visible reason.

## 2. Why MySQL/InnoDB is required
ConcurrentReg's seat safety comes from `SELECT ... FOR UPDATE` on the section row. InnoDB provides row-level locks;
SQLite does not and ignores the clause, so only a MySQL run can say anything about the intended design.
Connecting to MySQL does not guarantee the InnoDB engine, so the engine is checked explicitly.

## 3. Tests
- `test_all_tables_use_innodb` — reads `information_schema.tables` and expects `InnoDB` for `students`, `course_sections`, `registrations`.
- `test_capacity_one_with_more_requests_than_seats_through_the_api` — creates a section with capacity 1, sends 4
  simultaneous requests (4 students) through the real API using the workload generator, while the test holds the
  section's row lock from a separate connection (the backend is not modified). Steps and what is checked:
  1. Poll `information_schema.innodb_trx` until InnoDB reports 4 transactions in `LOCK WAIT` — server-side proof that all 4 requests were inside the database at once.
  2. Release the lock; the waiting transactions run one after another.
  3. Expect 1 `SUCCESS` and 3 `COURSE_FULL`; client-side peak in flight = 4. Since Day 3 the server runs this through the OS layer with generous settings (8 workers, 8 permits), so all 4 requests still reach the database and InnoDB still reports 4 in `LOCK WAIT`.
  4. Read the **persisted** state: `available_seats == 0`, exactly 1 registration row, no duplicate rows.

## 4. Important variables
- `request_count` — 4, a test-fixture value chosen to be larger than the capacity; not a research parameter.
- `waiting` — number of transactions InnoDB reports in `LOCK WAIT`.
- The poll interval is 0.25 s because InnoDB serves a cached copy of the transaction list when it is read more often than about every 0.1 s (an earlier 0.05 s poll saw only a stale empty list).

## 5. Environment
Needs a MySQL test database (`TEST_DATABASE_URL`). The lock-wait observation needs the `PROCESS` privilege; if it is missing, only that test is skipped (it checks first, before taking any lock).

## 6. What a pass proves, and what it does not
Proves, for that run on that MySQL server: the tables are InnoDB; 4 requests for 1 seat were all blocked on the row lock; exactly 1 registration was committed; stored seats and registrations are consistent.
Does not prove: behaviour at university-scale load, realistic traffic, PostgreSQL correctness, or the IASL admission layer (see `docs/iasl/IASL_TESTING.md`). If the lock were removed from the service, the same test fails (4 successes were observed in that experiment).

## 7. Running it
`.venv/bin/python -m pytest -v tests/test_mysql_innodb.py`
