# tests/test_workload_generator.py

## 1. Purpose
Unit tests for `workload/workload_generator.py`. They need no running server or database logic
(the shared fixture still resets the test database, which is harmless).

## 2. Why it exists
To show that the instrument itself is trustworthy before it is used to measure anything.

## 3. What is covered
- **Generation:** correct count and unique IDs; same seed → identical sequence; different seed → different sequence; hot sections only for `hot`; both hot and cold for `mixed`; all sections for `independent`; no accidental repeat students; `duplicate_fraction=1` repeats the first request.
- **Timing patterns:** `burst` offsets are 0; `steady` gaps are `1/rate`; `ramp` gaps shrink stage by stage.
- **Validation:** twelve invalid configurations are all rejected.
- **Classification:** each Day 1 response maps to the expected category, and the Day 3 "Request queue is full" 503 maps to `QUEUE_FULL` while another 503 stays `SERVER_ERROR`; unexpected responses (wrong message, not JSON, wrong status, unknown 409) become `UNKNOWN`, never `SUCCESS`.
- **Single request:** latency measured with a deliberately slow mock handler (≥ 50 ms); timeout and connection errors become records, not exceptions; request body matches the API contract.
- **Aggregation:** category counts add up; throughput from controlled data (10 requests in 2 s, 4 successes → 5.0 and 2.0 per second); latency statistics exclude timeouts; no-response case.

## 4. Important variables
- `fake_result(...)` builds a minimal result record so aggregates can be checked with known numbers.
- `send_with_handler(handler)` runs `send_request` against a fake HTTP transport.

## 5. Limits
The tests use `httpx.MockTransport`, so they prove the client logic, not network behaviour.
