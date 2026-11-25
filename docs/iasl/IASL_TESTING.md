# IASL Testing Record (Stage 7)

Every number below comes from a command that was executed during this work; the command and its output summary are given.
Nothing here is a performance claim: these tests establish **correctness, safety and stability**, not that IASL improves anything
(that is Stage 8's question and is answered with measurements, not tests).

| | |
|---|---|
| **Date** | 2026-11-25 |
| **Databases** | MySQL 8.4.11 / InnoDB (Docker `creg-demo-mysql`, database `concurrentreg_demo_test`) and SQLite (file). **Reported separately.** |
| **Python / pytest** | 3.14.6 / 9.1.1 (pinned in `requirements.txt`) |
| **New tests** | 367 in 18 files (`tests/test_iasl_*.py`), plus 1 helper plugin (`tests/iasl_enabled_plugin.py`). 325 test IASL itself (15 files); 42 test the experiment tooling (analysis 22, decision rules 9, load driver 11) |
| **Existing tests** | 188 (MySQL) / 169 + 19 skipped (SQLite): **not edited, weakened, removed or skipped** |

---

## 1. Result matrix

`Q = -q -p no:cacheprovider --show-capture=no --tb=short`

### MySQL 8.4.11 / InnoDB

| Run | Command | Result |
|---|---|---|
| Existing tests, IASL off | `pytest $Q --ignore-glob='tests/test_iasl_*'` | **188 passed** |
| Existing tests, **IASL enabled** | `PYTHONPATH=. pytest -p tests.iasl_enabled_plugin $Q --ignore-glob='tests/test_iasl_*'` | **188 passed** |
| Everything | `pytest $Q` | **555 passed** (188 + 367) |

### SQLite

| Run | Command | Result |
|---|---|---|
| Existing tests, IASL off | `TEST_DATABASE_URL=sqlite:///.../creg_test pytest $Q --ignore-glob='tests/test_iasl_*'` | **169 passed, 19 skipped** |
| Existing tests, **IASL enabled** | same, with `-p tests.iasl_enabled_plugin` | **169 passed, 19 skipped** |
| Everything | `pytest $Q` | **535 passed, 20 skipped** |

The 19 skips are the existing row-lock tests ("needs MySQL/InnoDB row locks"); the 20th is the new MySQL-only correctness test.
SQLite has no row locks, so **a SQLite pass says nothing about concurrency correctness**; MySQL validation is claimed only for the
MySQL rows above, which were executed against MySQL/InnoDB.

### Frontend

`npm run typecheck` clean; `npm test`: **77 passed** (7 files), re-run after the final documentation and UI-text edits in Stage 9.

---

## 2. The existing suite with IASL really switched on

The standard fixtures build servers with IASL explicitly **off**, so on their own they never exercise the hooks. The plugin
`tests/iasl_enabled_plugin.py` wraps `create_app` so every server a test builds has IASL enabled with **all-default settings**
(nothing tuned to help tests pass), and sets `IASL_ENABLED=1` for the module-level app.

Proof that it works (run, not assumed): a server built the way the fixtures build one, with the plugin, has `app.state.iasl` installed,
its loop thread running and an `admission` block in `/os-layer/status`; the identical call without the plugin has no runtime.

Safety: the plugin must set `DATABASE_URL` before the app is imported, so it repeats `conftest.py`'s guard and **refuses to run unless
`TEST_DATABASE_URL` names a database ending in `_test`**.

One expected exception: running the **whole** suite under the plugin gives 4 failures, exactly the four new tests that assert
"IASL is off" (`test_when_iasl_is_off_the_endpoints_say_so_instead_of_failing`, `test_iasl_is_off_by_default_nothing_is_installed_and_the_status_is_unchanged`,
`test_iasl_is_switched_on_by_the_environment_and_a_bad_value_refuses_to_start`, `test_a_result_file_from_a_run_without_iasl_says_so`).
That is the plugin contradicting those assertions on purpose, not a defect; the meaningful enabled run is the existing suite alone (above).

---

## 3. Brief §9 checklist mapped to tests

| Requirement | Tests |
|---|---|
| Collector: valid / missing / invalid / stale | `test_iasl_metrics.py` (37), `test_iasl_robustness.py` (stale and invalid through the real loop) |
| Collector: concurrent updates | `test_iasl_telemetry.py` (8 writer threads, exact counts, bounded ring); `test_iasl_metrics.py` (6 concurrent samplers); `test_iasl_robustness.py` (collector sampling while 8 threads submit and complete requests: no exception, never INVALID) |
| Analyzer: healthy / pressure / overload / hysteresis / noise / transitions / missing | `test_iasl_analyzer.py` (35) |
| Controller: increase / decrease / no-change / min-max / cooldown / invalid action / fallback | `test_iasl_controller.py` (25), `test_iasl_guardrails.py` (29), `test_iasl_engine.py` (28) |
| Admission: accepted / rejected / queue-full | `test_iasl_admission.py` (27), `test_iasl_pipeline.py` (15) |
| Admission: **timeout handling** | There is **no server-side request timeout** (decided out of scope; audit §6). The only timeout that exists is a client giving up: `test_clients_that_give_up_leave_every_counter_consistent_and_the_server_healthy` (12 impatient HTTP clients; every admitted job ends exactly one way; workers healthy; next request answered). |
| Admission: concurrent handling | `test_with_one_submitter_the_limit_is_exact_and_with_many_it_overshoots_by_at_most_the_number_of_submitters`; `test_iasl_admission.py` (concurrent checks while the limit changes) |
| Integration: IASL enabled / disabled | `test_iasl_app.py`, `test_iasl_runtime.py`, the plugin run (section 2) |
| Integration: failure and fallback | `test_iasl_runtime.py`, `test_iasl_robustness.py`, `test_iasl_edges.py` (watchdog, repeated failures, stale, invalid, applier refusing, stuck thread) |
| Integration: high concurrency, semaphore saturation | `test_iasl_robustness.py` (permits=1, 8 workers, 5 submitter threads); `test_iasl_app.py` MySQL test (permits=1, 120-request burst) |
| Integration: capacity consistency, no duplicates, no overselling | `test_under_admission_pressure_and_semaphore_saturation_the_database_stays_correct` (**MySQL only**): successes <= capacity, registered rows == client-reported successes, seats == capacity - successes, all four `database_state()` invariants true |
| Regression: existing suite | section 1 |
| Isolation (brief §4E) | `test_iasl_boundary.py`: IASL imports no registration/DB/SQL/OS-layer code; the OS layer imports no IASL code |

---

## 4. Stability

Timing-sensitive code was run repeatedly, with real threads and no sleeps-and-hope assertions.

| Experiment | Command | Result |
|---|---|---|
| The 14 IASL test files that existed at that point (309 tests) x15, MySQL | `repeat.sh 15 ...` | **15 of 15 runs: 309 passed**, 28.3 to 29.6 s each |
| Same tests x5 under CPU contention (10 busy-loop processes on a 10-core machine) | `repeat.sh 5 ...` with burners | **5 of 5 runs: 309 passed**, 89 to 135 s each (about 4x slower). *Caveat:* the burners had a 10-minute cap and expired during run 5, so that run was only partly under load. |
| Robustness file x40, MySQL | loop of `pytest tests/test_iasl_robustness.py` | **40 of 40 passed** (after the two fixes in section 7) |

(`test_iasl_edges.py`, 16 tests, was added after the hunt; 309 + 16 = 325. Those 16 are covered by the final matrix in section 1.)

---

## 5. Coverage

Measured with coverage.py 7.17.5 (line **and branch**), installed in an isolated throwaway virtualenv so the project's `venv` and
`requirements.txt` are untouched. Command: `coverage run --branch --source=app -m pytest ...` on MySQL (513 tests at that point; the 42 experiment-tooling tests were added afterwards and are not part of this IASL coverage table).

| Module | Stmts | Miss | Branch | Partial | Cover |
|---|---|---|---|---|---|
| `app/iasl/admission.py` | 42 | 0 | 8 | 0 | 100% |
| `app/iasl/analyzer.py` | 117 | 0 | 38 | 0 | 100% |
| `app/iasl/config.py` | 151 | 0 | 62 | 0 | 100% |
| `app/iasl/controller.py` | 178 | 1 | 34 | 2 | 99% |
| `app/iasl/engine.py` | 34 | 0 | 22 | 0 | 100% |
| `app/iasl/guardrails.py` | 41 | 0 | 22 | 0 | 100% |
| `app/iasl/metrics.py` | 133 | 0 | 44 | 1 | 99% |
| `app/iasl/runtime.py` | 115 | 0 | 16 | 0 | 100% |
| `app/iasl/serialize.py`, `telemetry.py`, `types.py` | 185 | 0 | 14 | 0 | 100% |
| `app/iasl_api.py` | 49 | 0 | 12 | 0 | 100% |
| `app/os_layer/*` (4 files + config) | 295 | 0 | 28 | 0 | 100% |
| **Total** | **1340** | **1** | **300** | **3** | **99%** |

Residual: `controller.py:191` is a redundant guard in `_enter_fallback` that its only caller already checks (unreachable by construction);
`controller.py:224->exit` and `metrics.py:78->83` are branch-exit notes with no uncovered statement.
Context only (existing code, not part of IASL): `demo_api.py` 91%, `registration_service.py` 97%, `verification.py` 60%.

Coverage shows which lines ran, not that assertions on them are strong; that is what section 6 addresses.

---

## 6. Do the tests actually fail when the code is wrong? (mutation checks)

Because several test files passed on their first run, each stage was followed by deliberately breaking the code and confirming a test
failed (then restoring it and confirming a pass). **57 deliberate breaks, 57 caught** (40 in the IASL code across stages 2 to 6, then 8 in `scripts/iasl_analysis.py` and 9 in the decision rules of `scripts/iasl_report.py`; two attempted breaks did not apply because of a
malformed `sed`; they were redone and caught).

| Stage | Breaks (all caught) |
|---|---|
| 2 metrics/config | restart detection off; rates not divided by the interval; percentile off by one rank; threshold ordering unchecked |
| 3 analyzer | overload without corroboration; no per-signal hysteresis; escalate on the first sample; de-escalate straight to HEALTHY; a corroborating signal treated as primary |
| 4 controller | cooldown ignored; reversal lockout ignored; hard bounds not applied; step cap removed; oscillation never detected; unreliable metrics allowed to act; wrong pressure step; non-queue pressure decreasing; BLOCK verdict ignored; state not updated after apply; fallback exit not handing back the limit; untrusted streak never reaching fallback |
| 5 integration | admission never consulted; consulted on a shut-down queue; fail-closed instead of fail-open; refusals not counted; observer never told; capacity skip removed; `set_limit` bound removed; watchdog disabled; recorder not installed; tick failures not recorded; the engine flaw (below); generator not knowing the response |
| 8 experiment tooling | refusals counted in the latency set; timeouts left out of it; latency from send time instead of intended time; recovery needing one good second; recovery floor removed; paired direction ignored; goodput counting every answer; drain accepting a single poll; and the nine decision-rule breaks (H1 threshold loosened, H1 accepting 3 of 5 seeds, H2 floor lowered, H3 ignoring failures or ignoring errors, H4 ignoring admission refusals, H5 ignoring goodput, H6 ignoring baseline-only recovery or widening its slack) |
| 6 API | write route added; API reading the OS layer; disabled status crashing; unvalidated limit; history taking the runtime lock; "last action" wrong; unavailable metrics hidden |

---

## 7. Defects and flakes found by testing (honest list)

**Product design flaw (fixed, Stage 5).** The closed-loop test showed the limit falling 24 -> 16 -> 8 after the load had gone: the analyzer's
state is deliberately slow to recover, and the engine kept tightening against that stale state. Fixed with rules R1b/R1c
(`IASL_DESIGN.md` §6.2); breaking R1b again makes four tests fail.

**Test bugs (not product defects), found by repeating runs.** Listed because a flaky test is a defect too:

| Symptom | Cause | Fix |
|---|---|---|
| 2 of 5 runs of `test_iasl_robustness.py` failed (`199 == 200`) | the last worker answers the caller first and increments `jobs_finished` a moment later in the worker loop's `finally`; the test read the counter immediately | wait for the counter (also fixed in the live-traffic test, which had the same race) |
| two tests asserted a hard-coded limit of 20 | healthy warm-up ticks had legitimately raised it to 24 | compare with the value just before the bad data |
| a submit raced a worker when the limit was already 1 | the second request was correctly refused | fill the workers first, then tighten |

After the fixes: robustness file 40 of 40, all IASL tests 15 of 15 plus 5 of 5 under contention.

**Behaviour documented, not a defect.** With several threads calling `submit()` at once the admission limit is soft by at most
(submitters - 1): all of them can pass the depth check before any enqueues. In production `submit()` runs on the single event-loop thread,
where the limit is exact (tested), and the queue's own capacity is a hard bound either way (tested).

---

## 8. What is NOT tested (limitations)

* **No performance or benefit claim.** Nothing here shows IASL improves latency, throughput or recovery; Stage 8 measures that.
* **No server-side timeout exists**, so timeout-rate and DB-timeout signals are reported unavailable and untestable.
* **InnoDB lock-wait metrics** are not read by the application and are not tested.
* **Single process only.** Multiple uvicorn workers (each with its own layer and counters) were not tested and are not supported.
* **Scale.** MySQL correctness tests use up to 120 requests and 40 students; nothing at university scale, nothing against PostgreSQL.
* **Timing** tests use real threads on one shared machine, which also hosts unrelated containers; they passed under CPU contention but that is a
  stress sample, not a proof.
* **Frontend:** the three additive category changes are covered by typecheck and the existing frontend tests only; the dashboard now has an IASL page (`/dashboard/iasl`). Its
  data layer and decision wording are unit-tested (`iaslApi.test.ts`, `iaslLogic.test.ts`); the components themselves are checked by typecheck, build,
  a Lighthouse audit (accessibility 100 on mobile) and a manual run against a live backend under load, not by component tests.
* **SQLite** cannot validate concurrency (no row locks); its results show logic and API behaviour only.
* The thresholds and limits used in tests are **fixture values**, not calibrated settings.

---

## 9. Reproduce

```bash
# 0. environment (MySQL via Docker; credentials are generated into the git-ignored .demo.env)
./scripts/demo_db.sh && set -a && source .demo.env && set +a

# 1. everything, MySQL                       (expect 555 passed)
.venv/bin/python -m pytest -q
# 2. existing tests only, IASL off / enabled (expect 188 passed each)
.venv/bin/python -m pytest -q --ignore-glob='tests/test_iasl_*'
PYTHONPATH=. .venv/bin/python -m pytest -q -p tests.iasl_enabled_plugin --ignore-glob='tests/test_iasl_*'
# 3. SQLite (separately)                     (expect 535 passed, 20 skipped)
env -u DATABASE_URL TEST_DATABASE_URL=sqlite:///$PWD/creg_test .venv/bin/python -m pytest -q
# 4. only the IASL tests
.venv/bin/python -m pytest -q tests/test_iasl_*.py
# 5. coverage (isolated venv so the project's environment is untouched)
python3 -m venv /tmp/covenv && /tmp/covenv/bin/pip install -r requirements.txt coverage
/tmp/covenv/bin/coverage run --branch --source=app -m pytest -q && /tmp/covenv/bin/coverage report -m --include='app/iasl/*,app/iasl_api.py,app/os_layer/*'
```

The tests never touch the demo or app database: `conftest.py` refuses any database whose name does not end in `_test`.
