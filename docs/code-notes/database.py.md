# app/database.py

## 1. Purpose
Connects the application to MySQL. It builds the SQLAlchemy `engine`, the `SessionLocal`
session factory, the `Base` class that all tables inherit from, and the `get_db` helper.

## 2. Why it exists
Every other file needs a database connection. Keeping it in one place means the password is
read from the environment in exactly one spot and never written in code.

## 3. Important functions/classes
- **`engine`** — the connection pool to MySQL, built from `DATABASE_URL`. The pool allows up to 60
  simultaneous connections (20 + 40 overflow) instead of SQLAlchemy's default of 15, so the
  concurrency tests are not quietly throttled by the pool. MySQL's default limit is 151.
- **`SessionLocal`** — a factory. Calling `SessionLocal()` gives a new session (one "conversation"
  with the database). `autoflush=False` means SQLAlchemy only sends SQL when we ask it to, so
  the order of SQL statements stays easy to follow.
- **`Base`** — parent class of the table classes in `models.py`.
- **`get_db()`** — input: none. Output: a session, closed afterwards. It was the FastAPI dependency in Day 1/2;
  since Day 3 the registration endpoint no longer uses it (a worker thread opens its own `SessionLocal()` per job),
  and it is kept only as a small helper.

## 4. Important variables
- `DATABASE_URL` — the connection string (`mysql+pymysql://user:password@host:port/database`).
  Read from the environment (or `.env`). If missing, the program stops with a clear error.

## 5. Execution flow
Imported at startup. Since Day 3 each worker thread of the OS layer creates its own session from `SessionLocal`
(`os_layer/request_pipeline.py`) and passes it to `registration_service.py`. The engine and its pool are shared
between threads (that is thread-safe); sessions never are. The number of connections in use at once is bounded by the
DB semaphore permits, which should not exceed the pool's 60.

## 6. Database behavior
Only opens connections. No reads, writes, transactions or locks happen here. (`pool_pre_ping`
checks a pooled connection is still alive before using it.)

## 7. Error handling
A missing `DATABASE_URL` raises `RuntimeError` immediately. The URL (with the password) is
never logged or printed.

## 8. Testing
Used by every test. The tests set `DATABASE_URL` to the `_test` database before importing it
(see `conftest.py.md`).
