"""Unit tests for the workload generator. No server or database is needed here."""
import time

import httpx
import pytest

from workload import workload_generator as wg


def make_config(**changes):
    config = wg.WorkloadConfig(request_count=30, section_ids=[1, 2, 3, 4], **changes)
    wg.validate_config(config)
    return config


def logical_sequence(config):
    return [(r.student_id, r.section_id, r.planned_offset_s) for r in wg.generate_requests(config)]


# ---- request generation

def test_generates_the_requested_number_of_requests():
    requests = wg.generate_requests(make_config())
    assert len(requests) == 30
    assert len({r.request_id for r in requests}) == 30


def test_same_seed_gives_the_same_logical_sequence():
    first = logical_sequence(make_config(seed=7, contention="independent"))
    second = logical_sequence(make_config(seed=7, contention="independent"))
    assert first == second


def test_different_seed_can_give_a_different_sequence():
    first = logical_sequence(make_config(seed=1, contention="independent"))
    second = logical_sequence(make_config(seed=2, contention="independent"))
    assert first != second


def test_hot_contention_only_targets_hot_sections():
    config = make_config(contention="hot", hot_section_count=2)
    assert {r.section_id for r in wg.generate_requests(config)} <= {1, 2}


def test_mixed_contention_uses_both_hot_and_cold_sections():
    config = make_config(contention="mixed", hot_section_count=1, hot_fraction=0.5)
    sections = {r.section_id for r in wg.generate_requests(config)}
    assert 1 in sections and sections & {2, 3, 4}


def test_independent_contention_spreads_over_all_sections():
    config = make_config(contention="independent")
    assert {r.section_id for r in wg.generate_requests(config)} == {1, 2, 3, 4}


def test_students_do_not_repeat_per_section_unless_asked_to():
    config = make_config(contention="hot", student_count=10)   # 30 requests, 1 section, 10 students
    pairs = [(r.student_id, r.section_id) for r in wg.generate_requests(config)[:10]]
    assert len(set(pairs)) == 10                                # first 10 requests are all different students


def test_duplicate_fraction_one_repeats_the_first_request():
    config = make_config(duplicate_fraction=1.0)
    requests = wg.generate_requests(config)
    assert {(r.student_id, r.section_id) for r in requests} == {(requests[0].student_id, requests[0].section_id)}


# ---- arrival timing patterns

def test_burst_sends_everything_at_offset_zero():
    assert set(wg.arrival_offsets(make_config(pattern="burst"))) == {0.0}


def test_steady_spaces_requests_by_one_over_rate():
    offsets = wg.arrival_offsets(make_config(pattern="steady", rate=10))
    assert offsets[:3] == pytest.approx([0.0, 0.1, 0.2])


def test_ramp_gets_faster_stage_by_stage():
    config = make_config(pattern="ramp", rate=30, ramp_stages=3)   # 10 requests per stage: 10/s, 20/s, 30/s
    offsets = wg.arrival_offsets(config)
    gaps = [b - a for a, b in zip(offsets, offsets[1:])]
    assert gaps[0] == pytest.approx(1 / 10)
    assert gaps[15] == pytest.approx(1 / 20)
    assert gaps[-1] == pytest.approx(1 / 30)


# ---- configuration validation

@pytest.mark.parametrize("changes", [
    {"request_count": 0}, {"request_count": -5}, {"request_count": wg.MAX_REQUESTS + 1},
    {"concurrency": 0}, {"pattern": "nonsense"}, {"contention": "nonsense"},
    {"timeout_seconds": 0}, {"base_url": ""}, {"rate": 0, "pattern": "steady"},
    {"section_ids": []}, {"hot_section_count": 9}, {"duplicate_fraction": 1.5},
])
def test_invalid_configuration_is_rejected(changes):
    config = wg.WorkloadConfig(**{"section_ids": [1, 2], **changes})
    with pytest.raises(wg.ConfigError):
        wg.validate_config(config)


# ---- result classification

@pytest.mark.parametrize("status, message, expected", [
    (201, "Registration successful", wg.SUCCESS),
    (409, "Student is already registered for this course section", wg.DUPLICATE),
    (409, "Course section is full", wg.COURSE_FULL),
    (503, "Request queue is full", wg.QUEUE_FULL),
    (503, "Server is shutting down", wg.SERVER_ERROR),
    (404, "Student does not exist", wg.CLIENT_ERROR),
    (422, None, wg.CLIENT_ERROR),
    (500, "Registration failed because of a database error", wg.SERVER_ERROR),
    (503, None, wg.SERVER_ERROR),
])
def test_known_responses_map_to_the_right_category(status, message, expected):
    body = {"success": False, "message": message} if message else None
    assert wg.classify_response(status, body) == expected


@pytest.mark.parametrize("status, body", [
    (201, {"success": True, "message": "Something else"}),   # right status, unexpected message
    (201, None),                                             # not JSON
    (200, {"success": True, "message": "Registration successful"}),  # wrong status
    (409, {"message": "A new kind of conflict"}),            # unrecognised conflict
    (302, None),
])
def test_unexpected_responses_are_unknown_and_never_success(status, body):
    assert wg.classify_response(status, body) == wg.UNKNOWN


# ---- single request: latency and failure handling (mock transport, no server)

def send_with_handler(handler):
    request = wg.Request("req-00000", 0, "STU001", 1, 0.0)
    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return wg.send_request(client, "/registrations", request, time.perf_counter())


def test_latency_is_measured_around_the_request():
    def slow_handler(request):
        time.sleep(0.05)
        return httpx.Response(201, json={"success": True, "message": "Registration successful"})

    result = send_with_handler(slow_handler)

    assert result["category"] == wg.SUCCESS
    assert result["http_status"] == 201
    assert 50 <= result["latency_ms"] < 500
    assert result["latency_ms"] == pytest.approx((result["end_offset_s"] - result["start_offset_s"]) * 1000)


def test_timeout_is_recorded_not_raised():
    def handler(request):
        raise httpx.ReadTimeout("too slow")
    result = send_with_handler(handler)
    assert result["category"] == wg.TIMEOUT and result["http_status"] is None


def test_connection_failure_is_recorded_not_raised():
    def handler(request):
        raise httpx.ConnectError("refused")
    result = send_with_handler(handler)
    assert result["category"] == wg.CONNECTION_ERROR and result["http_status"] is None


def test_request_body_follows_the_day1_api_contract():
    seen = {}
    def handler(request):
        seen["body"] = request.read()
        return httpx.Response(201, json={"success": True, "message": "Registration successful"})
    send_with_handler(handler)
    assert seen["body"] == b'{"student_id":"STU001","section_id":1}'


# ---- aggregation

def fake_result(category, latency_ms=10.0, status=200):
    return {"category": category, "latency_ms": latency_ms, "http_status": status}


def test_summary_counts_add_up():
    results = (
        [fake_result(wg.SUCCESS)] * 4 + [fake_result(wg.DUPLICATE)] * 2 + [fake_result(wg.COURSE_FULL)] * 3
        + [fake_result(wg.TIMEOUT, status=None)] + [fake_result(wg.UNKNOWN)]
    )
    summary = wg.summarize_results(results, elapsed_seconds=2.0)

    assert summary["total_requests"] == 11
    assert summary["successful_requests"] == 4
    assert summary["failed_requests"] == 7
    assert sum(summary["category_counts"].values()) == 11
    assert summary["category_counts"][wg.DUPLICATE] == 2
    assert summary["category_counts"][wg.COURSE_FULL] == 3
    assert summary["category_counts"][wg.TIMEOUT] == 1
    assert summary["category_counts"][wg.UNKNOWN] == 1


def test_throughput_values_from_controlled_data():
    results = [fake_result(wg.SUCCESS)] * 4 + [fake_result(wg.COURSE_FULL)] * 6
    summary = wg.summarize_results(results, elapsed_seconds=2.0)
    assert summary["completed_requests_per_second"] == pytest.approx(5.0)          # 10 / 2s
    assert summary["successful_registrations_per_second"] == pytest.approx(2.0)    # 4 / 2s


def test_latency_statistics_and_timeouts_excluded():
    latencies = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    results = [fake_result(wg.SUCCESS, latency_ms=value) for value in latencies]
    results.append(fake_result(wg.TIMEOUT, latency_ms=5000, status=None))
    stats = wg.summarize_results(results, elapsed_seconds=1.0)["latency_ms"]

    assert stats["min"] == 10 and stats["max"] == 100
    assert stats["average"] == pytest.approx(55)
    assert stats["p50"] == 50 and stats["p95"] == 100


def test_summary_with_no_responses_has_no_latency():
    summary = wg.summarize_results([fake_result(wg.CONNECTION_ERROR, status=None)], elapsed_seconds=1.0)
    assert summary["latency_ms"] is None
