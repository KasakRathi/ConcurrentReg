# tests/test_demo_api.py

17 tests for `app/demo_api.py` and `app/verification.py`. See `docs/code-notes/demo_api.py.md` for what each protects. Notes:

* The "off by default" tests clear `CREG_DEMO_CONTROLS` explicitly (a shell that has it exported must not change the result).
* The invariant test inserts rows **bypassing the application rules** (three registrations in a two-seat section, a wrong seat counter) to prove the four SQL checks can fail. `get_section()` rolls back anything uncommitted, so both sections are fetched before adding rows.
* The reset test ends its own transaction first: on MySQL an open snapshot holds a metadata lock and would block `DROP TABLE`.
* The path-guard test calls the function directly, because over HTTP the router already rejects a slash, so that path never reaches the guard. A symlink inside the folder pointing outside is also refused.
* `test_seat_race_through_the_demo_api_never_oversells` needs MySQL/InnoDB (skipped, with a reason, elsewhere): 30 simultaneous requests for the 2-seat section store exactly 2 rows.
* Results: MySQL 8.4.11 187/187 passed before the registrations test was added, 188/188 after; SQLite 168 passed, 19 skipped (all 19 need row locks).
