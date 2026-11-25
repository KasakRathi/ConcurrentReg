"""Tests for the workload generator's arrival models: open loop (scheduled arrivals, lateness,
validity), closed loop (virtual users), and multi-phase schedules.

Pure functions are tested with exact numbers. Where real threads are involved the tests use a
deliberately slow mock server and only LOWER bounds on timing (a sleep is never shorter than
asked), so they do not depend on exact operating-system scheduling.
All numbers are test-fixture values, not research parameters.
"""
import json
import threading
import time
from datetime import datetime

import httpx
import pytest

from tests.conftest import wait_until
from workload import workload_generator as wg

OK = {"success": True, "message": "Registration successful"}


def ok_response():
    return httpx.Response(201, json=OK)


def make_client(handler):
    return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))


def make_config(**changes):
    settings = dict(request_count=4, concurrency=10, pattern="steady", rate=20.0, section_ids=[1],
                    student_count=20, lateness_tolerance_ms=50.0)
    settings.update(changes)
    config = wg.WorkloadConfig(**settings)
    wg.validate_config(config)
    return config


def run(config, handler, stop_event=None):
    requests = wg.generate_requests(config)
    results, elapsed = wg.run_workload(requests, config, client=make_client(handler), stop_event=stop_event)
    return requests, results, elapsed


class ConcurrencyTracker:
    """A mock-server handler that counts how many requests are inside it at the same time."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.lock = threading.Lock()
        self.inside = 0
        self.most_inside = 0

    def __call__(self, request):
        with self.lock:
            self.inside += 1
            self.most_inside = max(self.most_inside, self.inside)
        time.sleep(self.seconds)
        with self.lock:
            self.inside -= 1
        return ok_response()


# =============================================================== intended arrival schedules

def test_steady_intended_times_are_exact():
    offsets = wg.arrival_offsets(make_config(pattern="steady", rate=4.0, request_count=5))
    assert offsets == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_existing_ramp_schedule_is_unchanged():
    # Independent re-computation of the original ramp rule: the rate grows in equal steps.
    config = make_config(pattern="ramp", rate=30.0, ramp_stages=3, request_count=30)
    expected, now = [], 0.0
    for index in range(30):
        expected.append(now)
        now += 1 / (30.0 * ((index * 3 // 30) + 1) / 3)
    assert wg.arrival_offsets(config) == pytest.approx(expected)


def test_burst_to_recovery_phases_are_represented_exactly():
    # EXAMPLE schedule: 10/s for 1 s, a burst at 40/s for 0.5 s, then recovery at 5/s for 2 s.
    config = make_config(pattern="phases", phases=[[10, 1], [40, 0.5], [5, 2]], request_count=1)
    plan = wg.phase_plan(config)
    offsets = wg.arrival_offsets(config)

    assert [p["requests"] for p in plan] == [10, 20, 10]
    assert [(p["start_s"], p["end_s"]) for p in plan] == [(0.0, 1), (1, 1.5), (1.5, 3.5)]
    assert wg.planned_request_count(config) == 40 == len(offsets)
    assert offsets == sorted(offsets)
    assert offsets[0] == 0.0 and offsets[9] == pytest.approx(0.9)           # steady phase: every 0.1 s
    assert offsets[10] == pytest.approx(1.0) and offsets[11] == pytest.approx(1.025)   # burst: every 25 ms
    assert offsets[30] == pytest.approx(1.5) and offsets[31] == pytest.approx(1.7)     # recovery: every 0.2 s
    # Half-open boundaries: a phase's arrivals are all < its end, the next phase starts exactly there.
    start = 0
    for phase in plan:
        arrivals = offsets[start:start + phase["requests"]]
        assert phase["start_s"] <= arrivals[0] and all(a < phase["end_s"] for a in arrivals)
        start += phase["requests"]


def test_a_phase_slower_than_one_request_per_duration_rounds_up_to_whole_requests():
    config = make_config(pattern="phases", phases=[[0.5, 3]], request_count=1)      # 1.5 expected -> 2 arrivals
    assert wg.arrival_offsets(config) == [0.0, 2.0]


def test_phase_requests_are_generated_with_those_intended_times():
    config = make_config(pattern="phases", phases=[[10, 0.5], [20, 0.5]], request_count=1)
    requests = wg.generate_requests(config)
    assert [r.planned_offset_s for r in requests] == wg.arrival_offsets(config)
    assert len(requests) == 5 + 10


def test_targets_do_not_depend_on_arrival_model_or_think_time_settings():
    base = make_config(contention="independent", section_ids=[1, 2, 3], request_count=20, seed=5)
    closed = make_config(contention="independent", section_ids=[1, 2, 3], request_count=20, seed=5,
                         arrival_model="closed", virtual_users=4, think_time_min_s=0.1, think_time_max_s=0.9)
    pairs = lambda config: [(r.student_id, r.section_id) for r in wg.generate_requests(config)]
    assert pairs(base) == pairs(closed)


# ========================================================= configuration is validated clearly

@pytest.mark.parametrize("changes", [
    {"seed": -1}, {"seed": 1.5}, {"seed": True},
    {"lateness_tolerance_ms": -1},
    {"arrival_model": "sideways"},
    {"concurrency": 0}, {"concurrency": wg.MAX_IN_FLIGHT + 1},
    {"pattern": "phases", "phases": []},
    {"pattern": "phases", "phases": [[0, 5]]},
    {"pattern": "phases", "phases": [[10, 0]]},
    {"pattern": "phases", "phases": [[10, -2]]},
    {"pattern": "phases", "phases": [[float("nan"), 5]]},
    {"pattern": "phases", "phases": [[float("inf"), 5]]},
    {"pattern": "phases", "phases": [[10]]},
    {"pattern": "phases", "phases": [["fast", 5]]},
    {"pattern": "phases", "phases": [[10, 1]] * (wg.MAX_PHASES + 1)},
    {"pattern": "phases", "phases": [[wg.MAX_REQUESTS, 10]]},                    # far too many requests
    {"pattern": "phases", "phases": [[10, 1]], "arrival_model": "closed"},       # phases are scheduled arrivals
    {"arrival_model": "closed", "virtual_users": 0},
    {"arrival_model": "closed", "virtual_users": wg.MAX_VIRTUAL_USERS + 1},
    {"arrival_model": "closed", "think_time_min_s": -0.1},
    {"arrival_model": "closed", "think_time_min_s": 2.0, "think_time_max_s": 1.0},
])
def test_invalid_arrival_configuration_is_rejected(changes):
    config = wg.WorkloadConfig(**{"section_ids": [1], "request_count": 4, **changes})
    with pytest.raises(wg.ConfigError):
        wg.validate_config(config)


# ====================================== one request: lateness and the two latency measurements

def test_a_request_sent_after_its_intended_time_has_positive_lateness_and_consistent_latencies():
    def slow(request):
        time.sleep(0.05)
        return ok_response()

    request = wg.Request("req-00000", 0, "STU001", 1, -0.5)     # intended 0.5 s BEFORE the experiment clock started
    record = wg.send_request(make_client(slow), "/registrations", request, time.perf_counter())

    assert record["intended_offset_s"] == -0.5 == record["planned_offset_s"]
    assert record["lateness_ms"] >= 500                          # sent at least 0.5 s after it was due
    assert record["send_time_latency_ms"] >= 50                  # from the moment of sending
    assert record["latency_ms"] == record["send_time_latency_ms"]
    # Same request, same monotonic clock: intended-arrival latency = lateness + send-time latency.
    assert record["intended_arrival_latency_ms"] == pytest.approx(
        record["lateness_ms"] + record["send_time_latency_ms"], abs=1e-6)
    assert record["intended_arrival_latency_ms"] > record["send_time_latency_ms"]
    assert record["start_offset_s"] == record["sent_offset_s"]
    # The wall-clock strings agree with the monotonic lateness (reporting only).
    gap_ms = (datetime.fromisoformat(record["sent_at"]) - datetime.fromisoformat(record["intended_at"])).total_seconds() * 1000
    assert gap_ms == pytest.approx(record["lateness_ms"], abs=2)


def test_a_request_is_never_sent_before_its_intended_time():
    experiment_start = time.perf_counter()
    request = wg.Request("req-00000", 0, "STU001", 1, 0.2)       # due 0.2 s from now
    record = wg.send_request(make_client(lambda r: ok_response()), "/registrations", request, experiment_start)

    assert record["sent_offset_s"] >= 0.2 - 1e-9
    assert record["lateness_ms"] >= -1e-6
    assert record["intended_arrival_latency_ms"] >= record["send_time_latency_ms"] - 1e-6


def test_closed_loop_requests_have_no_intended_arrival():
    request = wg.Request("req-00000", 0, "STU001", 1, None, user=0, think_time_before_s=0.0)
    record = wg.send_request(make_client(lambda r: ok_response()), "/registrations", request, time.perf_counter())
    assert record["lateness_ms"] is None and record["intended_at"] is None
    assert record["intended_arrival_latency_ms"] is None
    assert record["send_time_latency_ms"] is not None


def test_a_timeout_keeps_its_timing_fields_and_is_counted_as_an_error():
    def too_slow(request):
        raise httpx.ReadTimeout("simulated")

    config = make_config(request_count=2, rate=100.0)
    _requests, results, elapsed = run(config, too_slow)
    summary = wg.summarize_results(results, elapsed, config)

    assert [r["category"] for r in results] == [wg.TIMEOUT, wg.TIMEOUT]
    assert all(r["lateness_ms"] is not None and r["http_status"] is None for r in results)
    assert summary["open_loop"]["errors"]["timeouts"] == 2
    assert summary["send_time_latency_ms"] is None and summary["intended_arrival_latency_ms"] is None   # no responses


# ===================================================== rates, lateness statistics and validity

def fake_record(sequence, intended, sent, category=wg.SUCCESS, cap_was_full=False):
    sent_offset = sent
    return {"request_id": f"req-{sequence:05d}", "sequence": sequence, "category": category,
            "http_status": 201 if category == wg.SUCCESS else None,
            "intended_offset_s": intended, "sent_offset_s": sent_offset,
            "lateness_ms": None if sent is None else (sent - intended) * 1000,
            "latency_ms": 10.0, "send_time_latency_ms": 10.0,
            "intended_arrival_latency_ms": None if sent is None else (sent - intended) * 1000 + 10.0,
            "cap_was_full": cap_was_full}


def test_offered_and_achieved_rates_use_the_same_formula_on_their_own_timestamps():
    config = make_config()
    intended = [i * 0.1 for i in range(10)]            # 10 arrivals, 0.1 s apart -> 10 per second
    sent = [i * 0.2 for i in range(10)]                # actually sent every 0.2 s -> 5 per second
    results = [fake_record(i, intended[i], sent[i]) for i in range(10)]

    summary = wg.summarize_open_loop(results, config)

    assert summary["offered_rate_per_s"] == pytest.approx(10.0)      # (10 - 1) / 0.9
    assert summary["achieved_dispatch_rate_per_s"] == pytest.approx(5.0)   # (10 - 1) / 1.8
    assert summary["achieved_to_offered_ratio"] == pytest.approx(0.5)
    assert summary["intended_requests"] == summary["dispatched_requests"] == 10


def test_rates_are_undefined_for_a_burst_or_a_single_request():
    config = make_config()
    burst = [fake_record(i, 0.0, 0.001 * i) for i in range(5)]
    assert wg.summarize_open_loop(burst, config)["offered_rate_per_s"] is None    # all intended at one instant
    assert wg.rate_between([1.0]) is None and wg.rate_between([]) is None


def test_a_run_that_cannot_keep_its_schedule_is_flagged_invalid_and_explains_why():
    config = make_config(lateness_tolerance_ms=50.0)
    results = [fake_record(0, 0.0, 0.0), fake_record(1, 0.1, 0.11), fake_record(2, 0.2, 0.40, cap_was_full=True),
               fake_record(3, 0.3, 0.60, cap_was_full=True)]

    summary = wg.summarize_open_loop(results, config)

    assert summary["valid_open_loop"] is False
    assert summary["requests_over_tolerance"] == 2
    assert summary["requests_that_found_the_cap_full"] == 2
    assert summary["lateness_ms"]["max"] == pytest.approx(300)         # the measurements are still there
    assert any("2 requests were sent more than 50.0 ms" in reason for reason in summary["invalid_reasons"])
    assert "lateness_tolerance_ms" in summary["validity_rule"]


def test_a_run_within_tolerance_is_valid_and_exactly_the_tolerance_still_counts_as_on_time():
    config = make_config(lateness_tolerance_ms=50.0)
    results = [fake_record(0, 0.0, 0.020), fake_record(1, 0.1, 0.150)]   # 20 ms late, and exactly 50 ms late

    summary = wg.summarize_open_loop(results, config)

    assert summary["valid_open_loop"] is True and summary["invalid_reasons"] == []
    assert summary["requests_over_tolerance"] == 0


def test_requests_that_were_never_dispatched_make_a_run_invalid():
    config = make_config()
    results = [fake_record(0, 0.0, 0.0), fake_record(1, 0.1, None, category=wg.NOT_DISPATCHED)]
    results[1]["http_status"] = None

    summary = wg.summarize_open_loop(results, config)

    assert summary["dispatched_requests"] == 1 and summary["undispatched_requests"] == 1
    assert summary["valid_open_loop"] is False
    assert any("never dispatched" in reason for reason in summary["invalid_reasons"])


def test_high_percentiles_of_lateness_are_reported_only_with_enough_samples():
    few = wg.lateness_stats([float(v) for v in range(10)])
    some = wg.lateness_stats([float(v) for v in range(wg.MIN_SAMPLES_P95)])
    many = wg.lateness_stats([float(v) for v in range(wg.MIN_SAMPLES_P99)])
    assert few["p95"] is None and few["p99"] is None and few["mean"] == 4.5 and few["median"] is not None
    assert some["p95"] is not None and some["p99"] is None
    assert many["p95"] is not None and many["p99"] is not None
    assert wg.lateness_stats([]) is None


def test_intended_arrival_latency_summary_exceeds_send_time_latency_when_requests_were_late():
    config = make_config()
    results = [fake_record(i, i * 0.1, i * 0.1 + 0.2) for i in range(4)]       # every request 200 ms late
    summary = wg.summarize_results(results, 1.0, config)

    assert summary["send_time_latency_ms"]["average"] == pytest.approx(10.0)
    assert summary["intended_arrival_latency_ms"]["average"] == pytest.approx(210.0)
    assert summary["latency_ms"] == summary["send_time_latency_ms"]            # the old name is kept


# ================================== open loop with a real (slow) mock server and real threads

def test_a_saturated_generator_is_invalid_and_its_schedule_is_not_shifted():
    # One request in flight at a time, but a new arrival is due every 50 ms and each response takes 200 ms.
    def slow(request):
        time.sleep(0.2)
        return ok_response()

    config = make_config(concurrency=1, request_count=4, rate=20.0, lateness_tolerance_ms=50.0)
    requests, results, elapsed = run(config, slow)
    summary = wg.summarize_results(results, elapsed, config)
    late = [r["lateness_ms"] for r in results]

    assert [r["intended_offset_s"] for r in results] == [0.0, 0.05, 0.10, 0.15]      # intended times were NOT moved
    assert [r["intended_offset_s"] for r in results] == [r.planned_offset_s for r in requests]
    assert late[0] < 50 and late[1] >= 100 and late[2] >= 250 and late[3] >= 400    # each waits for the one before
    assert late == sorted(late)
    assert [r["cap_was_full"] for r in results[1:]] == [True, True, True]
    assert all(r["intended_arrival_latency_ms"] > r["send_time_latency_ms"] for r in results[1:])
    assert summary["open_loop"]["valid_open_loop"] is False
    assert summary["open_loop"]["requests_over_tolerance"] >= 3
    assert summary["open_loop"]["achieved_dispatch_rate_per_s"] < summary["open_loop"]["offered_rate_per_s"]
    assert elapsed >= 0.8


def test_slow_responses_do_not_change_the_arrival_schedule_when_the_cap_is_not_binding():
    def slow(request):
        time.sleep(0.3)                  # responses are slower than the gap between arrivals (50 ms)
        return ok_response()

    config = make_config(concurrency=10, request_count=5, rate=20.0, lateness_tolerance_ms=200.0)
    _requests, results, elapsed = run(config, slow)
    summary = wg.summarize_results(results, elapsed, config)

    assert max(r["lateness_ms"] for r in results) < 200          # arrivals stayed on schedule: open loop
    assert not any(r["cap_was_full"] for r in results)
    assert summary["open_loop"]["valid_open_loop"] is True
    assert summary["open_loop"]["dispatched_requests"] == 5


def test_the_in_flight_cap_bounds_concurrent_requests():
    tracker = ConcurrencyTracker(seconds=0.05)
    config = make_config(concurrency=3, pattern="burst", request_count=12)
    _requests, results, _elapsed = run(config, tracker)

    assert tracker.most_inside == 3                              # the cap was reached ...
    assert tracker.most_inside <= 3                              # ... and never exceeded
    assert len(results) == 12 and all(r["category"] == wg.SUCCESS for r in results)


def test_stopping_early_leaves_a_not_dispatched_record_for_every_unsent_request():
    stop = threading.Event()

    def stop_after_the_first(request):
        stop.set()
        return ok_response()

    config = make_config(request_count=5, rate=10.0)             # arrivals every 100 ms
    requests, results, elapsed = run(config, stop_after_the_first, stop_event=stop)
    summary = wg.summarize_results(results, elapsed, config)

    assert len(results) == len(requests) == 5                   # nothing silently disappeared
    assert results[0]["category"] == wg.SUCCESS
    assert [r["category"] for r in results[1:]] == [wg.NOT_DISPATCHED] * 4
    assert all(r["lateness_ms"] is None and r["http_status"] is None for r in results[1:])
    assert summary["category_counts"][wg.NOT_DISPATCHED] == 4
    assert summary["open_loop"]["dispatched_requests"] == 1 and summary["open_loop"]["undispatched_requests"] == 4
    assert summary["open_loop"]["valid_open_loop"] is False
    assert summary["completed_requests_per_second"] == pytest.approx(1 / elapsed)   # only sent requests count


def test_existing_result_and_summary_fields_are_preserved():
    config = make_config(request_count=3, rate=100.0)
    _requests, results, elapsed = run(config, lambda r: ok_response())
    summary = wg.summarize_results(results, elapsed, config)

    for field in ("request_id", "sequence", "student_id", "section_id", "planned_offset_s", "started_at",
                  "start_offset_s", "end_offset_s", "latency_ms", "http_status", "category", "detail"):
        assert field in results[0]
    for field in ("total_requests", "successful_requests", "failed_requests", "category_counts", "elapsed_seconds",
                  "completed_requests_per_second", "successful_registrations_per_second", "latency_sample_count",
                  "latency_ms"):
        assert field in summary
    assert set(summary["latency_ms"]) == {"average", "min", "max", "p50", "p95", "p99"}


# ======================================================================== closed loop

def test_closed_loop_user_sends_the_next_request_only_after_the_previous_response():
    calls = []
    gate = threading.Event()

    def handler(request):
        calls.append(time.perf_counter())
        if len(calls) == 1:
            gate.wait(timeout=10)        # the first response is held back
        return ok_response()

    config = make_config(arrival_model="closed", virtual_users=1, request_count=2)
    requests = wg.generate_requests(config)
    outcome = {}
    runner = threading.Thread(target=lambda: outcome.update(zip(("results", "elapsed"), wg.run_workload(
        requests, config, client=make_client(handler)))))
    runner.start()
    assert wait_until(lambda: len(calls) == 1)
    time.sleep(0.3)
    assert len(calls) == 1               # the user is still waiting for its response: no second request yet

    gate.set()
    runner.join(timeout=10)
    results = outcome["results"]
    assert len(calls) == 2
    assert results[1]["sent_offset_s"] >= results[0]["end_offset_s"]
    assert results[1]["previous_end_offset_s"] == results[0]["end_offset_s"]
    assert wg.summarize_closed_loop(results, config)["waited_for_previous_response"] is True


def test_closed_loop_users_respect_their_think_time():
    config = make_config(arrival_model="closed", virtual_users=1, request_count=3,
                         think_time_min_s=0.1, think_time_max_s=0.1)
    _requests, results, elapsed = run(config, lambda r: ok_response())
    summary = wg.summarize_results(results, elapsed, config)

    gaps = [results[i]["sent_offset_s"] - results[i - 1]["end_offset_s"] for i in (1, 2)]
    assert all(gap >= 0.099 for gap in gaps)
    assert summary["closed_loop"]["wait_after_previous_response_s"]["min"] >= 0.099
    assert elapsed >= 0.3                # think, send, think, send, think, send


def test_closed_loop_users_run_in_parallel_but_each_user_is_sequential():
    tracker = ConcurrencyTracker(seconds=0.1)
    config = make_config(arrival_model="closed", virtual_users=3, request_count=6)
    requests, results, _elapsed = run(config, tracker)

    assert tracker.most_inside == 3      # three users at once, never more than there are users
    for user in range(3):
        mine = sorted((r for r in results if r["user"] == user), key=lambda r: r["sequence"])
        assert len(mine) == 2
        assert mine[1]["sent_offset_s"] >= mine[0]["end_offset_s"]


def test_closed_loop_results_are_reported_separately_from_open_loop():
    closed_config = make_config(arrival_model="closed", virtual_users=2, request_count=4)
    _r, closed_results, closed_elapsed = run(closed_config, lambda r: ok_response())
    closed = wg.summarize_results(closed_results, closed_elapsed, closed_config)
    open_config = make_config(request_count=3, rate=100.0)
    _r, open_results, open_elapsed = run(open_config, lambda r: ok_response())
    opened = wg.summarize_results(open_results, open_elapsed, open_config)

    assert closed["arrival_model"] == "closed" and closed["open_loop"] is None
    assert closed["closed_loop"]["virtual_users"] == 2 and closed["closed_loop"]["arrivals_are_response_dependent"]
    assert opened["arrival_model"] == "open" and opened["closed_loop"] is None
    assert "valid_open_loop" in opened["open_loop"]


def test_think_times_and_user_assignment_are_reproducible_from_the_seed():
    config = make_config(arrival_model="closed", virtual_users=3, request_count=12, seed=9,
                         think_time_min_s=0.5, think_time_max_s=2.0)
    first = wg.plan_think_times(config, 12)
    second = wg.plan_think_times(config, 12)
    other_seed = wg.plan_think_times(make_config(arrival_model="closed", seed=10, think_time_min_s=0.5,
                                                 think_time_max_s=2.0, virtual_users=3, request_count=12), 12)

    assert first == second and first != other_seed
    assert all(0.5 <= t <= 2.0 for t in first)
    planned = [(r.user, r.think_time_before_s) for r in wg.generate_requests(config)]
    assert planned == [(r.user, r.think_time_before_s) for r in wg.generate_requests(config)]
    assert [user for user, _ in planned] == [i % 3 for i in range(12)]          # requests dealt to users in turn


def test_equal_min_and_max_think_time_means_a_fixed_think_time():
    config = make_config(arrival_model="closed", think_time_min_s=0.25, think_time_max_s=0.25, request_count=5)
    assert set(wg.plan_think_times(config, 5)) == {0.25}


# ===================================================== result file, run information and the CLI

def run_cli(tmp_path, *arguments):
    exit_code = wg.main(["--base-url", "http://127.0.0.1:1", "--timeout", "1", "--output-dir", str(tmp_path), *arguments])
    files = sorted(tmp_path.glob("*.json"))
    return exit_code, json.loads(files[-1].read_text()) if files else None


def test_phases_from_the_command_line_are_scheduled_and_recorded(tmp_path):
    code, saved = run_cli(tmp_path, "--phases", "50:0.1,10:0.2", "--sections", "1", "--concurrency", "5")

    assert code == 1                                         # nothing is listening: all connection errors
    assert saved["config"]["pattern"] == "phases" and saved["config"]["phases"] == [[50.0, 0.1], [10.0, 0.2]]
    assert len(saved["results"]) == 5 + 2                    # derived from the phases
    plan = saved["run"]["schedule"]["phases"]
    assert [p["requests"] for p in plan] == [5, 2] and plan[1]["start_s"] == pytest.approx(0.1)
    assert saved["summary"]["open_loop"]["errors"]["connection_errors"] == 7
    assert saved["summary"]["open_loop"]["intended_requests"] == 7


def test_the_result_file_records_what_is_needed_to_reproduce_a_run(tmp_path):
    _code, saved = run_cli(tmp_path, "--pattern", "steady", "--rate", "200", "--requests", "3", "--seed", "7",
                           "--lateness-tolerance-ms", "123")
    run_info = saved["run"]

    assert run_info["arrival_model"] == "open" and run_info["seed"] == 7
    assert run_info["target_rate_per_s"] == 200.0 and run_info["in_flight_cap"] == saved["config"]["concurrency"]
    assert run_info["lateness_tolerance_ms"] == 123 and run_info["timeout_seconds"] == 1.0
    assert run_info["generator_version"] == wg.GENERATOR_VERSION
    assert "generator_revision" in run_info                  # a git revision, or null if git is unavailable
    assert datetime.fromisoformat(run_info["run_started_at"]) <= datetime.fromisoformat(run_info["run_ended_at"])
    assert "not_reproducible" in run_info and "reproducible" in run_info
    assert saved["generated_requests"][1]["planned_offset_s"] == pytest.approx(0.005)    # the schedule itself


def test_a_closed_loop_run_records_its_users_and_think_times(tmp_path):
    _code, saved = run_cli(tmp_path, "--arrival-model", "closed", "--users", "2", "--requests", "4",
                           "--think-min", "0", "--think-max", "0.01", "--seed", "3")

    assert saved["run"]["virtual_users"] == 2 and saved["run"]["think_time"] == {"min_s": 0.0, "max_s": 0.01}
    assert saved["run"]["schedule"] is None and saved["run"]["in_flight_cap"] is None
    assert saved["summary"]["open_loop"] is None and saved["summary"]["closed_loop"]["virtual_users"] == 2
    assert all(r["planned_offset_s"] is None for r in saved["generated_requests"])
    assert [r["user"] for r in saved["generated_requests"]] == [0, 1, 0, 1]


@pytest.mark.parametrize("arguments", [
    ["--phases", "abc"], ["--phases", "10:5", "--pattern", "steady"], ["--pattern", "phases"],
    ["--phases", "10:0"], ["--arrival-model", "closed", "--phases", "10:5"], ["--users", "0", "--arrival-model", "closed"],
    ["--seed", "-3"], ["--lateness-tolerance-ms", "-1"], ["--think-min", "2", "--think-max", "1", "--arrival-model", "closed"],
])
def test_bad_command_line_values_are_rejected_before_anything_is_sent(tmp_path, arguments):
    assert wg.main(["--output-dir", str(tmp_path), *arguments]) == 2
    assert list(tmp_path.glob("*.json")) == []


def test_saved_results_with_inconsistent_dispatch_counts_fail_the_read_back_check(tmp_path):
    config = make_config(request_count=2, rate=100.0)
    _requests, results, elapsed = run(config, lambda r: ok_response())
    summary = wg.summarize_results(results, elapsed, config)
    summary["open_loop"]["undispatched_requests"] = 5          # tamper
    path = tmp_path / "x.json"
    wg.save_results(str(path), "x", config, wg.generate_requests(config), results, summary)
    with pytest.raises(ValueError):
        wg.check_saved_results(str(path), 2)


def test_open_and_closed_runs_against_the_real_server_write_the_new_fields(server_url, tmp_path):
    open_code = wg.main(["--base-url", server_url, "--pattern", "steady", "--rate", "50", "--requests", "4",
                         "--contention", "independent", "--sections", "1,2", "--lateness-tolerance-ms", "2000",
                         "--output-dir", str(tmp_path / "open")])
    closed_code = wg.main(["--base-url", server_url, "--arrival-model", "closed", "--users", "2", "--requests", "4",
                           "--contention", "independent", "--sections", "1,2", "--output-dir", str(tmp_path / "closed")])

    opened = json.loads(next((tmp_path / "open").glob("*.json")).read_text())
    closed = json.loads(next((tmp_path / "closed").glob("*.json")).read_text())
    assert open_code == 0 and closed_code == 0
    assert opened["summary"]["open_loop"]["valid_open_loop"] is True
    assert opened["summary"]["open_loop"]["lateness_ms"]["max"] < 2000
    assert all(r["http_status"] is not None for r in opened["results"] + closed["results"])
    assert closed["summary"]["closed_loop"]["waited_for_previous_response"] is True
    assert wg.NOT_DISPATCHED not in {r["category"] for r in opened["results"] + closed["results"]}
