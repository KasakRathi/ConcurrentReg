# tests/test_workload_arrival_models.py

## 1. Purpose
Tests of the generator's arrival models: open loop (scheduled arrivals, lateness, validity), closed loop (virtual users) and multi-phase schedules.

## 2. How the tests avoid being fragile
- Pure functions (schedules, rates, validity, statistics) are tested with **exact numbers** and hand-made records.
- Tests with real threads use a deliberately slow **mock server** (`httpx.MockTransport`), and assert only **lower bounds** on timing, because a sleep is never shorter than requested. Where possible the situation is built without waiting: a request whose intended time is 0.5 s *in the past* has a lateness of at least 500 ms immediately.
- No MySQL is needed: these tests pass on any test database. (One test uses the in-process real server and writes the new fields to a file.)

## 3. What is covered (maps to the 14 required cases)
1. Intended times: steady, the unchanged ramp, exact multi-phase times and half-open phase boundaries, fractional phases.
2. Positive lateness: a request due 0.5 s ago; a saturated generator (cap 1, 200 ms responses, a new arrival every 50 ms).
3. and 4. The two latencies use the right reference points: send-time latency from the moment of sending, intended-arrival latency from the intended time, and for one request `intended_arrival_latency = lateness + send_time_latency`; the wall-clock `intended_at`/`sent_at` agree with the monotonic numbers.
5. Offered and achieved rates use the documented formula on their own timestamps (10/s intended vs 5/s achieved = ratio 0.5); undefined for a pure burst.
6. A saturated or incomplete generator is flagged invalid, with reasons and the measurements still present; exactly the tolerance counts as on time.
7. The intended times are not shifted: after saturation the recorded intended offsets still equal the schedule.
8. Closed-loop users wait: with the first response held back, no second request is sent; after release it is, and `previous_end_offset_s` shows it.
9. Think times and the plan are reproducible from the seed; a different seed differs; changing think-time settings does not change which students/sections are targeted.
10. Burst-to-recovery phases (an example: 10/s, 40/s burst, 5/s recovery) are represented exactly.
11. Invalid rates, durations, seeds, NaN/infinity, too many phases or requests, bad closed-loop values and bad command-line values are rejected clearly (exit code 2, nothing sent).
12. and 13. Existing behaviour and result fields are preserved (the 45 older tests are unchanged and pass; legacy record and summary fields are checked here too).
14. Timeouts keep their timing fields and count as errors; stopping early leaves a `NOT_DISPATCHED` record for every unsent request, so counts still add up.
Also: the in-flight cap really bounds concurrent requests; slow responses do not change the schedule while the cap is not binding (open-loop independence); result-file reproducibility block; read-back check rejects inconsistent counts.

## 4. Important helpers
- `run(config, handler)` — runs a workload against a mock server. `ConcurrencyTracker` — counts how many requests are inside the mock server at once. `fake_record` — a hand-made result record for the summary tests.

## 5. Limits
Timings of tens to hundreds of milliseconds are used, so the suite takes a few seconds. The tests show the logic is right; they do not show how the generator behaves on very busy machines or at thousands of requests per second.
