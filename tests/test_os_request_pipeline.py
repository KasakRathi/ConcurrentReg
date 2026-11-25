"""Tests of the whole OS layer (queue + workers + semaphore) with a controllable stand-in
for the registration service, so every situation can be created exactly.

The real registration transaction against MySQL is tested in test_os_layer_mysql.py.
The numbers here are test-fixture values, not research parameters.
"""
import json
import logging
import threading
import time

import pytest
from sqlalchemy.exc import OperationalError

from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import QUEUE_FULL, SHUTTING_DOWN, OSConcurrencyLayer
from app.registration_service import ERROR, SUCCESS, RegistrationResult
from tests.conftest import wait_until


class FakeRegistration:
    """Replaces register_student. Can wait on a gate, sleep, or fail, and counts overlapping calls."""

    def __init__(self, seconds=0.0, gate=None):
        self.seconds = seconds
        self.gate = gate
        self.lock = threading.Lock()
        self.inside = 0
        self.max_inside = 0
        self.calls = []

    def __call__(self, db, student_code, section_id, request_id=None):
        with self.lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
            self.calls.append(student_code)
        try:
            if self.gate is not None:
                self.gate.wait(timeout=10)
            time.sleep(self.seconds)
            if student_code.startswith("BAD"):
                raise RuntimeError("simulated failure")
            if student_code.startswith("DB"):
                raise OperationalError("UPDATE", {}, Exception("simulated database failure"))
            return RegistrationResult(SUCCESS, "Registration successful")
        finally:
            with self.lock:
                self.inside -= 1


@pytest.fixture
def gate():
    return threading.Event()


@pytest.fixture
def make_layer(monkeypatch, gate):
    layers = []

    def make(queue_capacity, worker_count, permits, fake):
        monkeypatch.setattr(request_pipeline, "register_student", fake)
        layer = OSConcurrencyLayer(OSLayerConfig(queue_capacity, worker_count, permits))
        layer.start()
        layers.append(layer)
        return layer

    yield make
    gate.set()                      # never leave a worker blocked, even if a test failed
    for layer in layers:
        layer.stop(timeout_seconds=3)   # short: a failing test must not stall for long


def log_events(caplog, event_name):
    records = []
    for record in caplog.records:
        if record.name == "os_layer" and record.getMessage().startswith("{"):
            data = json.loads(record.getMessage())
            if data["event"] == event_name:
                records.append(data)
    return records


# -------------------------------------------------- worker and semaphore bounds

def test_worker_and_semaphore_limits_are_reached_and_never_exceeded(make_layer):
    fake = FakeRegistration(seconds=0.05)
    layer = make_layer(queue_capacity=30, worker_count=4, permits=2, fake=fake)

    futures = [layer.submit(f"S{number}", 1) for number in range(20)]
    results = [future.result(timeout=10) for future in futures]
    snapshot = layer.snapshot()

    assert [r.code for r in results] == [SUCCESS] * 20
    assert snapshot["workers"]["max_active"] == 4                       # all 4 workers got busy ...
    assert fake.max_inside == 2                                         # ... but only 2 were ever in the DB section
    assert snapshot["db_semaphore"]["max_in_critical_section"] == 2
    assert snapshot["db_semaphore"]["max_waiting"] >= 1                 # the other workers waited for a permit
    assert snapshot["queue"]["max_depth"] <= 30


def test_semaphore_covers_only_the_db_section_not_the_queue_or_the_workers(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(queue_capacity=10, worker_count=3, permits=1, fake=fake)

    futures = [layer.submit(f"S{number}", 1) for number in range(6)]

    def settled():
        snap = layer.snapshot()
        return (snap["db_semaphore"]["in_critical_section"] == 1 and snap["db_semaphore"]["waiting"] == 2
                and snap["workers"]["active"] == 3 and snap["queue"]["depth"] == 3)
    assert wait_until(settled)
    # 6 requests: 1 inside the DB section (holds the only permit), 2 on workers waiting for the permit,
    # 3 still in the queue. Only the one inside the DB section holds a permit.
    assert layer.snapshot()["db_semaphore"]["in_critical_section"] == 1

    gate.set()
    assert [f.result(timeout=10).code for f in futures] == [SUCCESS] * 6
    # A worker answers first and then logs, so give the workers a moment to become idle.
    assert wait_until(lambda: layer.snapshot()["workers"]["active"] == 0)
    assert layer.snapshot()["db_semaphore"]["in_critical_section"] == 0


# --------------------------------------------------------------- queue behaviour

def test_queue_saturation_rejects_extra_requests_immediately_and_stays_bounded(make_layer, gate, caplog):
    caplog.set_level(logging.INFO, logger="os_layer")
    fake = FakeRegistration(gate=gate)
    layer = make_layer(queue_capacity=2, worker_count=1, permits=1, fake=fake)

    first = layer.submit("S1", 1)
    assert wait_until(lambda: layer.snapshot()["db_semaphore"]["in_critical_section"] == 1)  # the worker is busy
    queued = [layer.submit("S2", 1), layer.submit("S3", 1)]                                   # fills the queue
    refused = [layer.submit("S4", 1), layer.submit("S5", 1)]                                  # no room

    assert all(future.done() for future in refused)              # answered at once, nothing waited
    assert [f.result().code for f in refused] == [QUEUE_FULL, QUEUE_FULL]
    snapshot = layer.snapshot()
    assert snapshot["queue"]["depth"] == 2
    assert snapshot["queue"]["max_depth"] == 2                   # never above capacity
    assert snapshot["queue"]["accepted"] == 3
    assert snapshot["queue"]["rejected_queue_full"] == 2
    rejections = log_events(caplog, "os_layer_rejected")
    assert [r["reason"] for r in rejections] == [QUEUE_FULL, QUEUE_FULL]
    assert rejections[0]["queue_capacity"] == 2

    gate.set()
    assert [f.result(timeout=10).code for f in [first] + queued] == [SUCCESS] * 3
    assert sorted(fake.calls) == ["S1", "S2", "S3"]             # refused requests never reached the DB code


def test_queue_wait_is_observable(make_layer, caplog):
    caplog.set_level(logging.INFO, logger="os_layer")
    fake = FakeRegistration(seconds=0.1)
    layer = make_layer(queue_capacity=10, worker_count=1, permits=1, fake=fake)

    futures = [layer.submit(f"S{number}", 1) for number in range(4)]
    for future in futures:
        future.result(timeout=10)
    assert wait_until(lambda: len(log_events(caplog, "os_layer_request")) == 4)

    waits = [r["queue_wait_ms"] for r in log_events(caplog, "os_layer_request")]  # one worker => completion order = arrival order
    assert waits[0] < 50
    assert waits[1] >= 90 and waits[2] >= 190 and waits[3] >= 290       # each waits for those in front of it
    snapshot = layer.snapshot()
    assert snapshot["queue_wait"]["jobs_dequeued"] == 4
    assert snapshot["queue_wait"]["max_s"] >= 0.29
    assert snapshot["queue_wait"]["average_s"] > 0.1


def test_every_request_leaves_a_log_line_with_the_research_fields(make_layer, caplog):
    caplog.set_level(logging.INFO, logger="os_layer")
    layer = make_layer(queue_capacity=7, worker_count=2, permits=1, fake=FakeRegistration(seconds=0.01))

    layer.submit("S1", 1).result(timeout=10)
    assert wait_until(lambda: len(log_events(caplog, "os_layer_request")) == 1)

    record = log_events(caplog, "os_layer_request")[0]
    assert {"request_id", "student_id", "section_id", "worker", "queue_depth_at_arrival", "enqueued_at_s",
            "queue_wait_ms", "worker_started_at_s", "semaphore_wait_ms", "semaphore_acquired_at_s",
            "db_section_ms", "worker_finished_at_s", "worker_total_ms", "result", "error"} <= set(record)
    assert (record["queue_capacity"], record["worker_count"], record["db_semaphore_permits"]) == (7, 2, 1)
    assert record["worker"].startswith("worker-")
    assert record["result"] == SUCCESS and record["error"] is None
    assert record["enqueued_at_s"] <= record["worker_started_at_s"] <= record["semaphore_acquired_at_s"] <= record["worker_finished_at_s"]
    started = log_events(caplog, "os_layer_started")[0]
    assert (started["queue_capacity"], started["worker_count"], started["db_semaphore_permits"]) == (7, 2, 1)


# ---------------------------------------------------------------- exception safety

def test_exceptions_do_not_leak_permits_or_workers(make_layer):
    fake = FakeRegistration(seconds=0.005)
    layer = make_layer(queue_capacity=40, worker_count=2, permits=1, fake=fake)

    codes = ["OK1", "BAD1", "DB1", "OK2", "BAD2", "DB2", "OK3", "BAD3", "DB3", "OK4"]
    results = [layer.submit(code, 1).result(timeout=10) for code in codes]
    assert [r.code for r in results] == [SUCCESS, ERROR, ERROR, SUCCESS, ERROR, ERROR, SUCCESS, ERROR, ERROR, SUCCESS]
    assert results[1].message == request_pipeline.INTERNAL_ERROR_MESSAGE

    # Capacity is intact: another full round of requests still goes through one permit and two workers.
    later = [layer.submit(f"LATER{number}", 1).result(timeout=10) for number in range(5)]
    assert [r.code for r in later] == [SUCCESS] * 5
    assert wait_until(lambda: layer.snapshot()["workers"]["active"] == 0)   # idle again
    snapshot = layer.snapshot()
    assert snapshot["db_semaphore"]["in_critical_section"] == 0
    assert snapshot["db_semaphore"]["acquisitions"] == 15
    assert snapshot["workers"]["alive"] == 2
    assert snapshot["workers"]["active"] == 0


# ---------------------------------------------------------- cancellation, shutdown

def test_request_cancelled_while_queued_is_skipped(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(queue_capacity=5, worker_count=1, permits=1, fake=fake)

    first = layer.submit("S1", 1)
    assert wait_until(lambda: layer.snapshot()["workers"]["active"] == 1)
    second = layer.submit("S2", 1)
    assert second.cancel() is True                     # the client gave up while waiting in the queue

    gate.set()
    assert first.result(timeout=10).code == SUCCESS
    assert wait_until(lambda: layer.snapshot()["workers"]["jobs_finished"] == 2)
    assert fake.calls == ["S1"]                        # the cancelled request never reached the DB code


def test_stop_finishes_accepted_requests_and_refuses_new_ones(make_layer):
    fake = FakeRegistration(seconds=0.05)
    layer = make_layer(queue_capacity=10, worker_count=2, permits=2, fake=fake)
    futures = [layer.submit(f"S{number}", 1) for number in range(6)]

    layer.stop()

    assert [f.result(timeout=1).code for f in futures] == [SUCCESS] * 6    # nothing accepted was dropped
    assert layer.workers.alive_workers() == 0
    late = layer.submit("LATE", 1)
    assert late.done() and late.result().code == SHUTTING_DOWN
    assert layer.snapshot()["queue"]["rejected_shutting_down"] == 1


def test_stop_while_workers_wait_for_a_permit_finishes_everything_and_leaks_nothing(make_layer, gate):
    fake = FakeRegistration(gate=gate)
    layer = make_layer(queue_capacity=10, worker_count=3, permits=1, fake=fake)
    accepted = [layer.submit(f"S{number}", 1) for number in range(6)]

    def settled():
        snap = layer.snapshot()
        return (snap["db_semaphore"]["in_critical_section"] == 1 and snap["db_semaphore"]["waiting"] == 2
                and snap["workers"]["active"] == 3 and snap["queue"]["depth"] == 3)
    assert wait_until(settled)                      # 1 inside the DB section, 2 waiting for the permit, 3 still queued

    stopper = threading.Thread(target=layer.stop, daemon=True)
    stopper.start()                                 # shutdown begins while every worker is blocked
    assert wait_until(lambda: layer.queue.is_shutdown)
    late = layer.submit("LATE", 1)
    assert late.done() and late.result().code == SHUTTING_DOWN        # refused straight away
    stopper.join(timeout=0.3)
    assert stopper.is_alive()                       # stop() is waiting for the accepted work, not abandoning it

    gate.set()                                      # let the database work finish
    stopper.join(timeout=10)
    assert not stopper.is_alive()                   # no deadlock
    assert [future.result(timeout=1).code for future in accepted] == [SUCCESS] * 6   # no accepted request was dropped
    final = layer.snapshot()
    assert final["db_semaphore"]["in_critical_section"] == 0 and final["db_semaphore"]["waiting"] == 0   # no permit leaked
    assert final["queue"]["depth"] == 0 and layer.queue.unfinished_tasks == 0
    assert final["workers"]["alive"] == 0 and final["workers"]["active"] == 0
    assert sorted(fake.calls) == [f"S{number}" for number in range(6)]  # the refused request never reached the database code
