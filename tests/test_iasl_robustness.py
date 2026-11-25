"""Stage 7 gap-filling: concurrency bounds, a client giving up, live-traffic metrics, stale/invalid data through the
real loop, quiet logs, determinism, and a fuzz of the whole analyzer->controller pipeline.

Numbers are test-fixture values, not research parameters. Runs on any database unless marked.
"""
import dataclasses
import random
import threading
import time
from collections import Counter

import httpx
import pytest

from app.iasl.admission import AdmissionController
from app.iasl.analyzer import StateAnalyzer
from app.iasl.config import AdmissionBounds, IASLConfig
from app.iasl.controller import AdaptiveController
from app.iasl.metrics import MetricsCollector
from app.iasl.runtime import IASLRuntime
from app.iasl.telemetry import OutcomeRecorder
from app.iasl.types import ActionKind, MetricQuality
from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import ADMISSION_REJECTED, QUEUE_FULL, OSConcurrencyLayer
from app.registration_service import SUCCESS
from tests.conftest import wait_until
from tests.test_iasl_analyzer import make_sample
from tests.test_iasl_controller import FakeApplier
from tests.test_os_request_pipeline import FakeRegistration


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def cfg(**changes):
    base = dict(enabled=True, sampling_interval_s=0.5, stale_metric_seconds=2.0, watchdog_seconds=30.0, smoothing_samples=1,
                escalate_samples=2, deescalate_samples=3, cooldown_seconds=1.0, increase_cooldown_seconds=2.0,
                reversal_lockout_seconds=2.0, queue_wait_p95_pressure_s=100.0, queue_wait_p95_overload_s=200.0)
    base.update(changes)
    return IASLConfig(**base)


@pytest.fixture
def gate():
    return threading.Event()


@pytest.fixture
def make_layer(monkeypatch, gate):
    layers = []

    def make(capacity, workers, permits, fake, admission=None, observer=None):
        monkeypatch.setattr(request_pipeline, "register_student", fake)
        layer = OSConcurrencyLayer(OSLayerConfig(capacity, workers, permits), admission, observer)
        layer.start()
        layers.append(layer)
        return layer

    yield make
    gate.set()
    for layer in layers:
        layer.stop(timeout_seconds=5)


# ----------------------------------------------------------------------------- concurrent admission

def test_with_one_submitter_the_limit_is_exact_and_with_many_it_overshoots_by_at_most_the_number_of_submitters(make_layer, gate):
    """Production calls submit() from the single event-loop thread, so the limit is exact there. Several threads can all
    pass the depth check before any of them enqueues, so the bound is soft by at most (submitters - 1); the queue's own
    capacity stays a hard bound either way."""
    limit, submitters, each = 5, 16, 50
    fake = FakeRegistration(gate=gate)
    layer = make_layer(100, 2, 2, fake, admission=AdmissionController(100, limit, 100, 3600.0))
    [layer.submit(f"W{i}", 1) for i in range(2)]
    assert wait_until(lambda: layer.workers.active == 2)

    codes, lock, start = Counter(), threading.Lock(), threading.Barrier(submitters)

    def submit_many(n):
        start.wait()
        local = Counter()
        for i in range(each):
            future = layer.submit(f"T{n}-{i}", 1)
            if future.done():
                local[future.result().code] += 1
            else:
                local["QUEUED"] += 1
        with lock:
            codes.update(local)

    threads = [threading.Thread(target=submit_many, args=(n,)) for n in range(submitters)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(codes.values()) == submitters * each                      # every request got exactly one answer
    assert limit <= layer.queue.max_depth <= limit + submitters - 1      # soft bound, honestly stated
    assert layer.queue.max_depth <= 100                                  # the hard bound is never in question
    assert codes[QUEUE_FULL] == 0 and codes["QUEUED"] == layer.queue.accepted - 2
    assert codes[ADMISSION_REJECTED] == layer.snapshot()["admission"]["rejected"]


def test_admission_and_semaphore_saturation_together_never_exceed_either_limit(make_layer):
    fake = FakeRegistration(seconds=0.003)
    layer = make_layer(64, 8, 1, fake, admission=AdmissionController(64, 16, 64, 3600.0), observer=OutcomeRecorder())
    results, lock = [], threading.Lock()

    def worker(n):
        out = [layer.submit(f"S{n}-{i}", 1).result(timeout=30).code for i in range(40)]
        with lock:
            results.extend(out)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # a worker answers the caller first and bumps jobs_finished a moment later, so wait for the bookkeeping to settle
    assert wait_until(lambda: layer.workers.jobs_finished == results.count(SUCCESS), timeout_seconds=5)
    snap = layer.snapshot()
    assert fake.max_inside <= 1 and snap["db_semaphore"]["max_in_critical_section"] == 1
    assert set(results) <= {SUCCESS, ADMISSION_REJECTED, QUEUE_FULL} and len(results) == 200
    assert snap["workers"]["jobs_finished"] == results.count(SUCCESS)


# ----------------------------------------------------------------------------- a client giving up (the only timeout that exists)

def test_clients_that_give_up_leave_every_counter_consistent_and_the_server_healthy(start_server, monkeypatch, gate):
    """There is no server-side request timeout (documented). A client that times out simply stops waiting; the server
    still finishes or cancels the job, and IASL's accounting must stay exact."""
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(gate=gate))
    url, layer = start_server(OSLayerConfig(32, 2, 2), cfg(sampling_interval_s=10.0, stale_metric_seconds=20.0, watchdog_seconds=60.0,
                                                          cooldown_seconds=10.0, increase_cooldown_seconds=10.0,
                                                          reversal_lockout_seconds=10.0))
    iasl = start_server.applications[-1].state.iasl
    outcomes = []

    def impatient(n):
        try:
            httpx.post(f"{url}/registrations", json={"student_id": f"G{n}", "section_id": 1}, timeout=0.3)
            outcomes.append("answered")
        except httpx.TimeoutException:
            outcomes.append("gave_up")

    threads = [threading.Thread(target=impatient, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("gave_up") == 12                               # the gate was closed: nobody got an answer
    gate.set()
    assert wait_until(lambda: layer.queue.qsize() == 0 and layer.workers.active == 0, timeout_seconds=10)

    snap = layer.snapshot()
    counters = iasl._recorder.counters()
    entered = snap["queue"]["accepted"]
    assert entered + snap["queue"]["rejected_queue_full"] + snap["admission"]["rejected"] == 12
    assert counters["completed"] + counters["cancelled"] == entered      # every admitted job ended exactly one way
    assert layer.workers.alive_workers() == 2 and layer.workers.unexpected_errors == 0
    assert httpx.post(f"{url}/registrations", json={"student_id": "AFTER", "section_id": 1}, timeout=5).status_code == 201


# ----------------------------------------------------------------------------- metrics under live concurrent traffic

def test_the_collector_stays_valid_while_many_threads_submit_and_complete_requests(make_layer):
    recorder = OutcomeRecorder()
    layer = make_layer(300, 8, 4, FakeRegistration(seconds=0.001), admission=AdmissionController(300, 300, 300, 3600.0),
                       observer=recorder)
    collector = MetricsCollector(cfg(), lambda: layer, lambda: recorder)
    samples, errors, stop = [], [], threading.Event()

    def sampler():
        try:
            while not stop.is_set():
                samples.append(collector.sample())
                time.sleep(0.002)
        except Exception as error:
            errors.append(error)

    sampling = threading.Thread(target=sampler)
    sampling.start()
    submitted = []

    def submit(n):
        futures = [layer.submit(f"L{n}-{i}", 1) for i in range(150)]
        submitted.extend(futures)

    threads = [threading.Thread(target=submit, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for f in submitted:
        f.result(timeout=30)
    assert wait_until(lambda: recorder.counters()["completed"] == layer.queue.accepted, timeout_seconds=10)
    assert wait_until(lambda: layer.workers.jobs_finished == layer.queue.accepted, timeout_seconds=10)   # bumped after the answer
    stop.set()
    sampling.join()

    assert not errors and len(samples) > 20
    assert not [s for s in samples if s.quality is MetricQuality.INVALID], [s.issues for s in samples if s.issues][:3]
    rates = [s.interval for s in samples if s.interval is not None]
    assert rates and all((r.arrivals_per_s or 0) >= 0 and (r.completed_per_s or 0) >= 0 for r in rates)
    assert all(0 <= (r.queue_full_rejection_rate or 0) <= 1 for r in rates)
    assert recorder.counters()["completed"] == layer.snapshot()["workers"]["jobs_finished"] == layer.queue.accepted


# ----------------------------------------------------------------------------- stale / invalid data through the real loop

@pytest.fixture
def rig(make_layer):
    clock = Clock()
    layer = make_layer(40, 2, 2, FakeRegistration())
    runtime = IASLRuntime(cfg(admission_initial=20, fallback_after_degraded=3, fallback_recovery_samples=3), clock=clock)
    runtime.attach(layer)
    return layer, runtime, clock


def tick(runtime, clock):
    clock.now += 1.0
    runtime.tick()


def test_stale_metrics_hold_the_limit_never_raise_it_and_eventually_enter_fallback(rig):
    layer, runtime, clock = rig
    for _ in range(3):
        tick(runtime, clock)
    before = layer.admission.effective_limit()                           # healthy warm-up may already have raised it
    real_sample = runtime.collector.sample
    runtime.collector.sample = lambda: dataclasses.replace(real_sample(), taken_at=clock.now - 10.0)   # 10 s old: stale
    seen = []
    for _ in range(3):
        tick(runtime, clock)
        seen.append((runtime.snapshot().assessment.quality, layer.admission.effective_limit()))
        if not runtime.controller.in_fallback:
            assert layer.admission.effective_limit() == before           # healthy data would have raised it; stale never does
    assert seen[0][0] is MetricQuality.STALE
    assert runtime.controller.in_fallback and layer.snapshot()["admission"]["fallback"] is True


def test_invalid_metrics_hold_the_limit_and_the_system_recovers_when_they_are_valid_again(rig):
    layer, runtime, clock = rig
    for _ in range(3):
        tick(runtime, clock)
    before = layer.admission.effective_limit()
    real_snapshot = layer.snapshot

    def broken():
        snap = real_snapshot()
        del snap["queue"]["depth"]
        return snap
    layer.snapshot = broken
    for _ in range(2):
        tick(runtime, clock)
        assert runtime.snapshot().assessment.quality is MetricQuality.INVALID
        assert layer.admission.effective_limit() == before               # never increased on bad data
    tick(runtime, clock)
    assert runtime.controller.in_fallback
    layer.snapshot = real_snapshot
    for _ in range(12):
        tick(runtime, clock)
    assert not runtime.controller.in_fallback and not layer.admission.in_fallback


def test_an_idle_system_produces_no_decision_noise_and_no_unbounded_growth(rig):
    layer, runtime, clock = rig
    for _ in range(1500):
        tick(runtime, clock)
    decisions = runtime.decisions()
    assert len(decisions) <= 40                                          # only real changes, never one record per tick
    assert runtime.controller.ticks == 1500 and len(runtime.history()) <= 120
    assert layer.admission.effective_limit() == 40                       # it relaxed to the maximum and stayed there
    assert [d for d in decisions if d.action is ActionKind.HOLD and d.blocked_by is None and d.guardrail is None] == []


# ----------------------------------------------------------------------------- determinism and the whole pipeline under fuzz

def scripted_samples(seed, count):
    rng = random.Random(seed)
    t, out = 0.0, []
    for _ in range(count):
        t += rng.choice([0.5, 0.5, 1.0, 2.0, 4.0, 9.0])
        kind = rng.random()
        out.append(make_sample(
            queue=rng.choice([0.0, 0.1, 0.4, 0.6, 0.9, 1.0]), worker=rng.choice([0.2, 0.9, 1.0]), sem=rng.choice([0.0, 1.5, 4.0]),
            wait_p95=rng.choice([None, 0.01, 0.3, 0.9]), rejection=rng.choice([0.0, 0.0, 0.02, 0.2]),
            error=rng.choice([None, 0.0, 0.05, 0.3]),
            quality=MetricQuality.INVALID if kind < 0.05 else MetricQuality.RESTART if kind < 0.08 else
            MetricQuality.DEGRADED if kind < 0.12 else MetricQuality.OK,
            interval=rng.random() > 0.05, taken_at=t, issues=("x",)))
    return out


def run_pipeline(seed, count=4000):
    config = cfg(decision_log_size=100)
    bounds = AdmissionBounds(8, 208, 208)
    applier = FakeApplier(208)
    controller = AdaptiveController(config, bounds, applier, 208, clock=lambda: 0.0)
    analyzer = StateAnalyzer(config)
    calls = []
    for sample in scripted_samples(seed, count):
        before = len(applier.calls)
        controller.step(sample, analyzer.assess(sample, now=sample.taken_at), now=sample.taken_at)
        calls.append(len([c for c in applier.calls[before:] if c[0] == "set_limit"]))
    return controller, applier, calls


def test_the_same_inputs_always_give_the_same_decisions():
    def signature(controller):
        return [(d.action, d.previous_value, d.new_value, d.rule, d.guardrail, d.blocked_by, d.previous_state, d.current_state)
                for d in controller.decisions()]
    first, _, _ = run_pipeline(seed=11)
    second, _, _ = run_pipeline(seed=11)
    other, _, _ = run_pipeline(seed=12)
    assert signature(first) == signature(second) and signature(first)
    assert signature(first) != signature(other)                          # and the comparison is not vacuous


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_fuzz_the_analyzer_and_controller_together_never_break_a_safety_invariant(seed):
    controller, applier, per_tick = run_pipeline(seed)
    assert max(per_tick) <= 1                                            # at most one limit change per tick
    assert 1 <= applier.limit <= 208 and 8 <= controller.value <= 208
    assert len(controller.decisions()) <= 100
    changes = [d for d in controller.decisions() if d.action in (ActionKind.INCREASE, ActionKind.DECREASE)]
    for d in changes:
        assert abs(d.new_value - d.previous_value) <= controller.param.max_move and 8 <= d.new_value <= 208
    for earlier, later in zip(changes, changes[1:]):
        gap = later.at_monotonic - earlier.at_monotonic
        assert gap >= (controller.param.increase_cooldown_s if later.action is ActionKind.INCREASE else controller.param.cooldown_s) - 1e-9
        if later.action is ActionKind.INCREASE and earlier.action is ActionKind.DECREASE:
            assert gap >= controller.param.reversal_lockout_s - 1e-9
    # nothing is ever raised on the strength of a bad sample: every INCREASE decision was made on an OK assessment
    assert all(d.metrics_used.get("quality") == "OK" for d in changes if d.action is ActionKind.INCREASE)
