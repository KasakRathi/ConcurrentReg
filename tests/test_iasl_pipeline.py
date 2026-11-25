"""IASL hooks inside the real OS layer (queue + workers + semaphore), with a controllable stand-in for the
registration service so every situation can be created exactly. Runs on any database.

The registration transaction itself is never exercised by IASL; the MySQL-only correctness tests are in test_iasl_app.py.
"""
import threading
from collections import Counter

import pytest

from app.iasl.admission import AdmissionController
from app.iasl.telemetry import OutcomeRecorder
from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import (
    ADMISSION_REJECTED, ADMISSION_REJECTED_MESSAGE, QUEUE_FULL, SHUTTING_DOWN, OSConcurrencyLayer,
)
from app.registration_service import ERROR, SUCCESS
from tests.conftest import log_events, wait_until
from tests.test_os_request_pipeline import FakeRegistration


@pytest.fixture
def gate():
    return threading.Event()


@pytest.fixture
def make_layer(monkeypatch, gate):
    layers = []

    def make(queue_capacity, worker_count, permits, fake, admission=None, observer=None):
        monkeypatch.setattr(request_pipeline, "register_student", fake)
        layer = OSConcurrencyLayer(OSLayerConfig(queue_capacity, worker_count, permits), admission, observer)
        layer.start()
        layers.append(layer)
        return layer

    yield make
    gate.set()
    for layer in layers:
        layer.stop(timeout_seconds=3)


def admission(capacity, limit, **kw):
    return AdmissionController(capacity, limit, kw.get("fallback", capacity), kw.get("watchdog", 3600.0))


def fill(layer, fake, workers, queued, prefix="F"):
    """Occupy every worker (blocked on the gate) and put `queued` more requests in the queue."""
    futures = [layer.submit(f"{prefix}{i}", 1) for i in range(workers)]
    assert wait_until(lambda: layer.workers.active == workers), "workers did not all pick up a job"
    futures += [layer.submit(f"{prefix}Q{i}", 1) for i in range(queued)]
    return futures


# ----------------------------------------------------------------------------- disabled path

def test_without_hooks_the_snapshot_is_exactly_what_it_was_before_iasl_existed(make_layer):
    layer = make_layer(8, 2, 2, FakeRegistration())
    assert layer.admission is None and layer.observer is None
    assert set(layer.snapshot()) == {"config", "queue", "queue_wait", "workers", "db_semaphore"}   # no "admission" block


def test_without_an_admission_controller_a_full_queue_still_gives_queue_full(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(3, 1, 1, fake)
    futures = fill(layer, fake, workers=1, queued=3)
    extra = layer.submit("X", 1)
    assert extra.done() and extra.result().code == QUEUE_FULL
    assert layer.snapshot()["queue"]["rejected_queue_full"] == 1
    gate.set()
    assert all(f.result(timeout=5).code == SUCCESS for f in futures)


# ----------------------------------------------------------------------------- admission

def test_a_request_is_refused_at_once_when_the_queue_is_at_the_admission_limit(make_layer, gate, caplog):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(20, 2, 2, fake, admission=admission(20, 3))
    caplog.set_level("INFO", logger="os_layer")
    futures = fill(layer, fake, workers=2, queued=3)                  # queue depth is now 3 == the limit
    refused = [layer.submit(f"R{i}", 1) for i in range(4)]

    for future in refused:
        assert future.done()                                           # answered immediately, never waited
        result = future.result()
        assert (result.code, result.message) == (ADMISSION_REJECTED, ADMISSION_REJECTED_MESSAGE)
        assert result.success is False
    snap = layer.snapshot()
    assert snap["admission"]["rejected"] == 4 and snap["admission"]["limit"] == 3
    assert snap["queue"]["rejected_queue_full"] == 0                  # not confused with a physically full queue
    assert snap["queue"]["max_depth"] <= 3
    events = log_events(caplog, "os_layer", "os_layer_rejected")
    assert [e["reason"] for e in events] == [ADMISSION_REJECTED] * 4

    gate.set()
    assert all(f.result(timeout=5).code == SUCCESS for f in futures)
    assert sorted(fake.calls) == sorted(f"F{i}" for i in range(2)) + [f"FQ{i}" for i in range(3)]   # refused ones never ran


def test_a_refused_request_never_reaches_the_registration_service(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(20, 1, 1, fake, admission=admission(20, 1))
    futures = fill(layer, fake, workers=1, queued=1)
    refused = [layer.submit(f"NEVER{i}", 1) for i in range(10)]
    gate.set()
    for f in futures:
        f.result(timeout=5)
    assert all(r.result().code == ADMISSION_REJECTED for r in refused)
    assert not any(c.startswith("NEVER") for c in fake.calls)


def test_the_queue_depth_never_exceeds_the_limit_while_load_keeps_arriving(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(50, 2, 2, fake, admission=admission(50, 7))
    fill(layer, fake, workers=2, queued=0)
    futures = [layer.submit(f"L{i}", 1) for i in range(200)]
    assert layer.queue.max_depth == 7
    codes = Counter()
    for f in futures:
        if f.done():
            codes[f.result().code] += 1
    assert codes == {ADMISSION_REJECTED: 193}                          # 7 admitted, the rest refused, none queue-full
    gate.set()


def test_admission_is_skipped_when_the_limit_equals_the_capacity_so_the_old_behaviour_is_kept(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(3, 1, 1, fake, admission=admission(3, 3))
    fill(layer, fake, workers=1, queued=3)
    extra = layer.submit("X", 1)
    assert extra.result().code == QUEUE_FULL and extra.result().message == "Request queue is full"
    snap = layer.snapshot()
    assert snap["queue"]["rejected_queue_full"] == 1 and snap["admission"]["rejected"] == 0
    gate.set()


def test_raising_the_limit_at_run_time_lets_requests_in_again(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    controller = admission(20, 2)
    layer = make_layer(20, 1, 1, fake, admission=controller)
    fill(layer, fake, workers=1, queued=2)
    assert layer.submit("A", 1).result().code == ADMISSION_REJECTED
    controller.set_limit(10)
    accepted = layer.submit("B", 1)
    assert not accepted.done()                                         # queued, waiting for a worker
    gate.set()
    assert accepted.result(timeout=5).code == SUCCESS


def test_a_shut_down_queue_keeps_its_own_refusal_and_admission_is_not_consulted(make_layer):
    class Recording:
        calls = 0

        def check(self, depth):
            Recording.calls += 1
            return False
    layer = make_layer(8, 1, 1, FakeRegistration(), admission=Recording())
    layer.stop(timeout_seconds=3)
    late = layer.submit("LATE", 1)
    assert late.result().code == SHUTTING_DOWN
    assert Recording.calls == 0


# ----------------------------------------------------------------------------- hooks can never fail a request

def test_if_the_admission_check_raises_the_request_is_admitted_and_the_error_is_logged_once(make_layer, caplog):
    class Broken:
        def check(self, depth):
            raise RuntimeError("admission exploded")
    layer = make_layer(8, 2, 2, FakeRegistration(), admission=Broken())
    caplog.set_level("INFO", logger="os_layer")
    results = [layer.submit(f"S{i}", 1).result(timeout=5) for i in range(6)]
    assert [r.code for r in results] == [SUCCESS] * 6                  # fail-open: the bounded queue still protects
    failures = log_events(caplog, "os_layer", "os_layer_hook_failed")
    assert len(failures) == 1 and failures[0]["hook"] == "admission" and "admission exploded" in failures[0]["error"]


def test_a_broken_stats_method_does_not_break_the_status_snapshot(make_layer):
    class BrokenStats:
        def check(self, depth):
            return True

        def stats(self):
            raise RuntimeError("no stats")
    layer = make_layer(8, 1, 1, FakeRegistration(), admission=BrokenStats())
    assert layer.snapshot()["admission"]["limit"] is None


def test_if_the_observer_raises_the_answer_and_the_workers_are_unaffected_and_it_is_logged_once(make_layer, caplog):
    class Broken:
        def on_completed(self, *args):
            raise RuntimeError("observer exploded")

        def on_cancelled(self):
            raise RuntimeError("observer exploded")
    layer = make_layer(8, 2, 2, FakeRegistration(), observer=Broken())
    caplog.set_level("INFO", logger="os_layer")
    results = [layer.submit(f"O{i}", 1).result(timeout=5) for i in range(8)]
    assert [r.code for r in results] == [SUCCESS] * 8
    assert wait_until(lambda: layer.workers.jobs_finished == 8)
    assert layer.workers.alive_workers() == 2 and layer.workers.unexpected_errors == 0
    assert len(log_events(caplog, "os_layer", "os_layer_hook_failed")) == 1


# ----------------------------------------------------------------------------- the observer feeds IASL's recorder

def test_every_outcome_is_recorded_with_its_code_after_the_caller_was_answered(make_layer):
    recorder = OutcomeRecorder()
    layer = make_layer(16, 2, 2, FakeRegistration(), observer=recorder)
    codes = [layer.submit(name, 1).result(timeout=5).code for name in ["A", "B", "C", "BAD1", "BAD2", "DB1"]]
    assert Counter(codes) == {SUCCESS: 3, ERROR: 3}
    assert wait_until(lambda: recorder.counters()["completed"] == 6)
    counters = recorder.counters()
    assert counters["by_outcome"] == {SUCCESS: 3, ERROR: 3} and counters["cancelled"] == 0
    assert recorder.window(__import__("time").monotonic(), 60, 1).samples == 6


def test_a_request_cancelled_while_queued_is_counted_as_cancelled_not_as_an_outcome(make_layer, gate):
    recorder = OutcomeRecorder()
    fake = FakeRegistration(gate=gate)
    layer = make_layer(8, 1, 1, fake, observer=recorder)
    first = layer.submit("FIRST", 1)
    assert wait_until(lambda: layer.workers.active == 1)
    second = layer.submit("SECOND", 1)
    assert second.cancel()
    gate.set()
    assert first.result(timeout=5).code == SUCCESS
    assert wait_until(lambda: recorder.counters()["cancelled"] == 1)
    counters = recorder.counters()
    assert counters["completed"] == 1 and "SECOND" not in fake.calls


def test_durations_recorded_are_consistent_with_each_other(make_layer, gate):
    recorder = OutcomeRecorder()
    fake = FakeRegistration(seconds=0.02)
    layer = make_layer(64, 1, 1, fake, observer=recorder)
    for f in [layer.submit(f"D{i}", 1) for i in range(30)]:
        f.result(timeout=10)
    assert wait_until(lambda: recorder.counters()["completed"] == 30)
    stats = recorder.window(__import__("time").monotonic(), 60, 1)
    assert stats.server_latency_p50_s >= stats.queue_wait_p50_s        # end-to-end includes the wait
    assert stats.server_latency_p99_s >= 0.02                          # at least the work itself


# ----------------------------------------------------------------------------- lifecycle stages are separate counters

def test_each_lifecycle_stage_has_its_own_counter_and_they_add_up(make_layer, gate):
    recorder = OutcomeRecorder()
    fake = FakeRegistration(gate=gate)
    layer = make_layer(10, 2, 2, fake, admission=admission(10, 4), observer=recorder)
    futures = fill(layer, fake, workers=2, queued=4)                   # received 6, admitted 6
    futures += [layer.submit(f"R{i}", 1) for i in range(5)]            # received 5 more, admission refuses all
    gate.set()
    for f in futures:
        f.result(timeout=5)
    assert wait_until(lambda: recorder.counters()["completed"] == 6)
    snap = layer.snapshot()
    received = 11
    admitted_into_queue = snap["queue"]["accepted"]
    refused = snap["queue"]["rejected_queue_full"] + snap["queue"]["rejected_shutting_down"] + snap["admission"]["rejected"]
    assert admitted_into_queue + refused == received                   # every request is exactly one of these
    assert (admitted_into_queue, snap["admission"]["rejected"]) == (6, 5)
    assert snap["workers"]["jobs_started"] == 6 == recorder.counters()["completed"]   # started != refused != completed
