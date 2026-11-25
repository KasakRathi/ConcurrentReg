"""The experiment load driver (scripts/iasl_loadgen.py): faithful to the project's generator, and sound where that one stalled."""
import threading
import time
from collections import Counter

import pytest

from app.iasl.config import IASLConfig
from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from scripts import iasl_loadgen as lg
from tests.conftest import wait_until
from tests.test_os_request_pipeline import FakeRegistration
from workload import workload_generator as wg


def plan(phases, seed=1, contention="mixed", students=200, sections=4, burst_count=None):
    config = wg.WorkloadConfig(
        base_url="http://unused", arrival_model="open", pattern="burst" if burst_count else "phases",
        request_count=burst_count or 20, phases=[] if burst_count else phases, contention=contention, student_count=students,
        section_ids=list(range(1, sections + 1)), hot_section_count=2, hot_fraction=0.8, seed=seed, concurrency=1000)
    wg.validate_config(config)
    return config, wg.generate_requests(config)


@pytest.fixture
def gate():
    return threading.Event()


def categories(records):
    return Counter(r["category"] for r in records)


def test_it_agrees_with_the_projects_generator_on_identical_requests(start_server, monkeypatch):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration())
    url, _ = start_server(OSLayerConfig(256, 8, 8))
    config, requests = plan([[100, 1.0]])
    theirs, _ = wg.run_workload(requests, wg.WorkloadConfig(**{**config.__dict__, "base_url": url}))
    ours, polls, elapsed = lg.run_open_loop(requests, url, timeout_s=5.0, poll_interval=0.1)
    assert categories(theirs) == categories(ours) == {wg.SUCCESS: 100}
    assert [r["sequence"] for r in ours] == [r.sequence for r in requests]          # one record per request, in order
    assert [r["intended_offset_s"] for r in ours] == [r.planned_offset_s for r in requests]   # the schedule is the generator's own
    assert [r["section_id"] for r in ours] == [r.section_id for r in requests]
    assert elapsed >= 0.95 and polls


def test_requests_leave_on_schedule_and_never_early(start_server, monkeypatch):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration())
    url, _ = start_server(OSLayerConfig(256, 8, 8))
    _, requests = plan([[150, 1.0]])
    records, _, _ = lg.run_open_loop(requests, url, poll_interval=None)
    lateness = [(r["sent_offset_s"] - r["intended_offset_s"]) * 1000 for r in records]
    assert min(lateness) >= -1.0                                                   # never sent early (clock rounding aside)
    check = lg.validity(records, tolerance_ms=250)
    assert check["valid"] and check["reasons"] == [] and check["lateness_ms"]["p99"] < 250


def test_hundreds_of_requests_in_flight_do_not_stall_the_dispatcher_or_lose_a_record(start_server, monkeypatch, gate):
    """The scale that broke the threaded generator: many requests waiting on a slow server at once."""
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(gate=gate))
    url, layer = start_server(OSLayerConfig(64, 8, 8))
    _, requests = plan(None, burst_count=800)
    records, _, elapsed = lg.run_open_loop(requests, url, timeout_s=0.6, poll_interval=None)
    gate.set()
    counts = categories(records)
    assert len(records) == 800 and sum(counts.values()) == 800
    assert counts[wg.QUEUE_FULL] >= 600 and counts[wg.TIMEOUT] >= 1                 # 72 got in and timed out; the rest were refused at once
    assert counts[wg.QUEUE_FULL] + counts[wg.TIMEOUT] == 800
    # 800 requests due at the same instant take a moment to start on one event loop (measured: up to ~0.4 s for the last);
    # that is the instrument's honest cost for an instantaneous burst, so the tolerance here is 1 s, not the experiments' 250 ms.
    assert lg.validity(records, 1000)["valid"]
    assert elapsed < 30                                                              # only a sanity bound: the server shares this process


def test_a_client_timeout_is_a_timeout_and_a_dead_server_is_a_connection_error(start_server, monkeypatch, gate):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(gate=gate))
    url, _ = start_server(OSLayerConfig(16, 2, 2))
    _, requests = plan(None, burst_count=3)
    records, _, _ = lg.run_open_loop(requests, url, timeout_s=0.3, poll_interval=None)
    gate.set()
    assert categories(records) == {wg.TIMEOUT: 3} and all(r["http_status"] is None for r in records)
    records, _, _ = lg.run_open_loop(requests, "http://127.0.0.1:1", timeout_s=1.0, poll_interval=None)
    assert categories(records) == {wg.CONNECTION_ERROR: 3}


def test_an_admission_refusal_is_recognised_as_its_own_category(start_server, monkeypatch, gate):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(gate=gate))
    url, layer = start_server(OSLayerConfig(32, 2, 2), IASLConfig(enabled=True, sampling_interval_s=10.0, stale_metric_seconds=20.0,
                                                                 watchdog_seconds=60.0, cooldown_seconds=10.0,
                                                                 increase_cooldown_seconds=10.0, reversal_lockout_seconds=10.0))
    futures = [layer.submit(f"F{i}", 1) for i in range(2)]
    assert wait_until(lambda: layer.workers.active == 2)
    start_server.applications[-1].state.iasl.admission.set_limit(1)
    futures.append(layer.submit("FQ", 1))                                           # depth 1 == limit
    _, requests = plan(None, burst_count=5)
    records, polls, _ = lg.run_open_loop(requests, url, timeout_s=0.4, poll_interval=0.1)
    gate.set()
    assert categories(records) == {wg.ADMISSION_REJECTED: 5}
    assert polls and all(p["adm_limit"] == 1 for p in polls)                        # the admission limit is visible in the polls


def test_polls_have_the_fields_the_analysis_needs_and_can_be_switched_off(start_server, monkeypatch):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(seconds=0.002))
    url, _ = start_server(OSLayerConfig(64, 4, 2))
    _, requests = plan([[60, 1.0]])
    _, polls, _ = lg.run_open_loop(requests, url, poll_interval=0.1)
    assert len(polls) >= 5 and set(polls[0]) >= {"t", "depth", "alive", "active", "permits", "in_cs", "waiting", "adm_limit", "qfull"}
    assert polls == sorted(polls, key=lambda p: p["t"]) and polls[0]["adm_limit"] is None        # IASL off: no admission block
    _, none, _ = lg.run_open_loop(requests[:5], url, poll_interval=None)
    assert none == []


def test_closed_loop_never_has_more_requests_in_flight_than_users(start_server, monkeypatch):
    fake = FakeRegistration(seconds=0.01)
    monkeypatch.setattr(request_pipeline, "register_student", fake)
    url, _ = start_server(OSLayerConfig(64, 8, 8))
    _, requests = plan([[100, 0.6]])
    records, elapsed = lg.run_closed_loop(requests, url, users=5)
    assert categories(records) == {wg.SUCCESS: len(requests)} and fake.max_inside <= 5
    assert elapsed >= len(requests) * 0.01 / 5 * 0.8                                 # the users really did wait for each answer


def test_validity_flags_late_and_undispatched_requests_with_the_generators_own_wording():
    on_time = {"sent_offset_s": 1.1, "intended_offset_s": 1.0}
    late = {"sent_offset_s": 2.5, "intended_offset_s": 1.0}
    never = {"sent_offset_s": None, "intended_offset_s": 3.0}
    assert lg.validity([on_time], 250) == {"valid": True, "reasons": [], "lateness_ms": lg.lateness_stats([on_time])}
    result = lg.validity([on_time, late, never], 250)
    assert result["valid"] is False
    assert any("never dispatched" in r for r in result["reasons"]) and any("1 requests were sent more than 250 ms" in r for r in result["reasons"])
    assert lg.lateness_stats([never]) is None


# ----------------------------------------------------------------------------- several client processes

def test_several_client_processes_give_the_same_answers_in_the_same_order_on_one_shared_clock(start_server, monkeypatch):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration())
    url, _ = start_server(OSLayerConfig(256, 8, 8))
    _, requests = plan([[120, 1.5]])
    single, _, _ = lg.run_open_loop(requests, url, poll_interval=None)
    several, polls, elapsed = lg.run_open_loop(requests, url, poll_interval=0.1, processes=3)
    assert categories(single) == categories(several) == {wg.SUCCESS: len(requests)}
    assert [r["sequence"] for r in several] == [r.sequence for r in requests]        # merged back into request order
    assert [r["section_id"] for r in several] == [r.section_id for r in requests]
    assert [r["intended_offset_s"] for r in several] == [r.planned_offset_s for r in requests]
    check = lg.validity(several, tolerance_ms=250)
    assert check["valid"], check                                                     # the processes really share one time origin
    assert min(r["sent_offset_s"] for r in several) >= -0.001 and elapsed >= 1.4
    assert polls and set(polls[0]) >= {"t", "depth", "adm_limit"}                    # polled by exactly one process


def test_hundreds_in_flight_across_processes_lose_nothing(start_server, monkeypatch, gate):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(gate=gate))
    url, _ = start_server(OSLayerConfig(64, 8, 8))
    _, requests = plan(None, burst_count=600)
    records, _, _ = lg.run_open_loop(requests, url, timeout_s=0.8, poll_interval=None, processes=4, warm_connections=480)
    gate.set()
    counts = categories(records)
    assert len(records) == 600 and None not in records
    assert counts[wg.QUEUE_FULL] + counts[wg.TIMEOUT] == 600 and counts[wg.QUEUE_FULL] >= 400 and counts[wg.TIMEOUT] >= 1


def test_closed_loop_across_processes_keeps_the_total_number_of_users(start_server, monkeypatch):
    fake = FakeRegistration(seconds=0.01)
    monkeypatch.setattr(request_pipeline, "register_student", fake)
    url, _ = start_server(OSLayerConfig(64, 16, 16))
    _, requests = plan([[100, 0.9]])
    records, elapsed = lg.run_closed_loop(requests, url, users=6, processes=3)
    assert categories(records) == {wg.SUCCESS: len(requests)} and fake.max_inside <= 6   # 3 processes x 2 users, never more
    assert [r["sequence"] for r in records] == [r.sequence for r in requests]
