# app/verification.py

**Purpose.** Run the project's own pytest suite on request (for the demo's "show the testing" step) and report it test by test.

**Safety.** The command is fixed (`python -m pytest -v -p no:cacheprovider --junitxml=...`); no user input reaches it. `check_can_run()` refuses unless `TEST_DATABASE_URL` is set, names a database ending in `_test`, and is NOT the same URL as `DATABASE_URL` (the tests wipe every table). A run is stopped after 900 s.

**Functions.** `parse_live_line` turns one `pytest -v` line into `{file, name, status, reason, percent}` (skipped tests carry their reason). `parse_junit` reads the JUnit XML into counts and one record per test. `start_verification` starts a background thread that streams the output, keeps the last 400 finished tests, and on exit reads the JUnit file. `VerificationJob.snapshot()` is what the API returns (status, percent, live counts, the 60 most recent tests, the final report, the last output lines).

**Tests.** `tests/test_demo_api.py`: JUnit and live-line parsing, the three refusals, and the endpoint refusing when both URLs are the same. Running the real suite through the UI was verified end to end in a browser (188 passed on MySQL 8.4.11, nothing skipped).

**Not done.** It does not run anything else, does not choose a database, and does not hide skipped tests: every skip appears with its reason.
