"""IASLRuntime: attach, the whole feedback loop on a real layer with a fake clock, fallback, watchdog, the loop thread."""
import json
import threading
import time

import pytest

from app.iasl.config import IASLConfig
from app.iasl.runtime import IASLRuntime
from app.iasl.types import ActionKind, MetricQuality, SystemState
from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import ADMISSION_REJECTED, QUEUE_FULL, OSConcurrencyLayer
from app.registration_service import SUCCESS
from tests.conftest import wait_until
from tests.test_os_request_pipeline import FakeRegistration


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def config(**changes):
    """Test-speed settings. Queue-wait thresholds are set high so real (wall-clock) waits never matter here."""
    base = dict(enabled=True, sampling_interval_s=0.5, stale_metric_seconds=2.0, watchdog_seconds=30.0,
                smoothing_samples=1, escalate_samples=2, deescalate_samples=3, cooldown_seconds=1.0,
                increase_cooldown_seconds=2.0, reversal_lockout_seconds=2.0,
                queue_wait_p95_pressure_s=100.0, queue_wait_p95_overload_s=200.0)
    base.update(changes)
    return IASLConfig(**base)


@pytest.fixture
def gate():
    return threading.Event()


@pytest.fixture
def world(monkeypatch, gate):
    """Factory: a started layer with IASL attached, a shared fake clock, and the gated stand-in registration."""
    made = []

    def build(queue_capacity=40, workers=2, permits=2, cfg=None, fake=None, attach=True):
        fake = fake or FakeRegistration(gate=gate)
        monkeypatch.setattr(request_pipeline, "register_student", fake)
        clock = Clock()
        layer = OSConcurrencyLayer(OSLayerConfig(queue_capacity, workers, permits))
        runtime = IASLRuntime(cfg or config(), clock=clock)
        if attach:
            runtime.attach(layer)
        layer.start()
        made.append((layer, runtime))
        return layer, runtime, clock, fake

    yield build
    gate.set()
    for layer, runtime in made:
        runtime.stop()
        layer.stop(timeout_seconds=3)


def overload(layer, workers=2, queued=40, extra=3):
    """Occupy every worker and fill the queue to the brim (plus a few requests the full queue turns away)."""
    futures = [layer.submit(f"W{i}", 1) for i in range(workers)]
    assert wait_until(lambda: layer.workers.active == workers)
    futures += [layer.submit(f"Q{i}", 1) for i in range(queued + extra)]
    return futures


def tick(runtime, clock, seconds=1.0):
    clock.now += seconds
    runtime.tick()


# ----------------------------------------------------------------------------- attach

def test_attach_installs_an_admission_controller_and_a_recorder_with_the_right_bounds(world):
    layer, runtime, *_ = world(queue_capacity=40, workers=2)
    assert layer.admission is runtime.admission and layer.observer is runtime._recorder
    param = runtime.controller.param
    assert (param.minimum, param.maximum, param.initial, param.step) == (2, 40, 40, 4)
    assert runtime.admission.effective_limit() == 40                      # starts exactly as permissive as no IASL
    assert layer.snapshot()["admission"]["limit"] == 40


def test_an_impossible_setting_refuses_to_attach_at_start_up_naming_the_variable(world):
    layer = OSConcurrencyLayer(OSLayerConfig(10, 2, 2))
    with pytest.raises(ValueError, match="IASL_ADMISSION_MIN"):
        IASLRuntime(config(admission_min=50)).attach(layer)


def test_re_attaching_to_a_replacement_layer_resets_control_and_leaves_the_old_layer_alone(world):
    layer1, runtime, clock, _ = world(queue_capacity=40, workers=2)
    old_admission = runtime.admission
    runtime.admission.set_limit(10)
    layer2 = OSConcurrencyLayer(OSLayerConfig(10, 3, 2))
    runtime.attach(layer2, strict=False)
    assert layer2.admission is runtime.admission is not old_admission
    assert layer1.admission is old_admission                              # the old layer keeps its own controller
    param = runtime.controller.param
    assert (param.minimum, param.maximum, param.initial) == (3, 10, 10)   # recomputed from the new size
    assert runtime.controller.value == 10 and runtime.admission.effective_limit() == 10
    assert runtime.controller.last_decision.action is ActionKind.RESET


def test_a_lenient_re_attach_clamps_where_a_strict_one_would_refuse(world):
    _, runtime, *_ = world(cfg=config(admission_min=30))
    small = OSConcurrencyLayer(OSLayerConfig(10, 2, 2))
    with pytest.raises(ValueError):
        runtime.attach(small, strict=True)
    runtime.attach(small, strict=False)                                   # the running server must not refuse
    assert (runtime.controller.param.minimum, runtime.controller.param.maximum) == (10, 10)


def test_start_needs_a_layer_and_cannot_be_started_twice():
    runtime = IASLRuntime(config())
    with pytest.raises(RuntimeError, match="attach"):
        runtime.start()
    runtime.attach(OSConcurrencyLayer(OSLayerConfig(10, 2, 2)))
    runtime.start()
    try:
        with pytest.raises(RuntimeError, match="already"):
            runtime.start()
    finally:
        runtime.stop()


def test_tick_before_attach_does_nothing_and_does_not_raise():
    IASLRuntime(config()).tick()


# ----------------------------------------------------------------------------- the whole loop, deterministic

def test_closed_loop_overload_lowers_the_limit_and_recovery_raises_it_back(world, gate):
    layer, runtime, clock, fake = world(queue_capacity=40, workers=2, permits=2)
    admission = runtime.admission
    overload(layer)                                                       # 2 running, 40 queued, 3 refused: queue full

    tick(runtime, clock)                                                  # first sample: no interval values yet, state held
    assert runtime.snapshot().assessment.held and admission.effective_limit() == 40
    tick(runtime, clock)                                                  # overloaded (1 of 2 samples needed)
    assert runtime.snapshot().assessment.state is SystemState.HEALTHY and admission.effective_limit() == 40
    tick(runtime, clock)                                                  # second consecutive: state OVERLOADED, one step down
    assessment = runtime.snapshot().assessment
    assert assessment.state is SystemState.OVERLOADED and assessment.transition is not None
    assert admission.effective_limit() == 32                              # 40 - 2 x step(4): the overload move

    refused = layer.submit("AFTER", 1)                                    # depth 40 >= 32: admission now refuses at once
    assert refused.done() and refused.result().code == ADMISSION_REJECTED

    tick(runtime, clock)                                                  # still overloaded; cooldown (1 s) has passed
    assert admission.effective_limit() == 24

    gate.set()                                                            # the load clears: queued work drains
    assert wait_until(lambda: layer.queue.qsize() == 0 and layer.workers.active == 0)
    limits = []
    for _ in range(30):
        tick(runtime, clock)
        limits.append(admission.effective_limit())
    assert limits[-1] == 40 and runtime.snapshot().assessment.state is SystemState.HEALTHY   # climbed all the way back
    increases = [b - a for a, b in zip([24] + limits, limits) if b != a]
    assert increases and all(step == 4 for step in increases)             # slowly, one normal step at a time
    assert all(2 <= value <= 40 for value in limits)

    kinds = [d.action for d in runtime.decisions()]
    assert kinds.count(ActionKind.DECREASE) == 2 and kinds.count(ActionKind.INCREASE) == 4
    first = next(d for d in runtime.decisions() if d.action is ActionKind.DECREASE)
    assert (first.previous_value, first.new_value, first.rule) == (40, 32, "R2")
    assert first.current_state is SystemState.OVERLOADED and first.metrics_used["signals"]["queue_utilization"]["level"] == 2


def test_the_published_snapshot_reflects_the_latest_tick(world):
    layer, runtime, clock, _ = world()
    assert runtime.snapshot().ticks == 0 and runtime.snapshot().sample is None
    tick(runtime, clock)
    tick(runtime, clock)
    snap = runtime.snapshot()
    assert snap.ticks == 2 and snap.failed_ticks == 0 and snap.attached
    assert snap.sample.quality in (MetricQuality.OK, MetricQuality.DEGRADED) and snap.sample.admission_limit == 40
    assert snap.controller["parameter"]["value"] == 40 and snap.admission["limit"] == 40
    assert len(runtime.history()) == 2
    json.dumps(runtime.describe())                                         # recorded into result files


# ----------------------------------------------------------------------------- failure and fallback

def test_repeated_failures_enter_fallback_requests_keep_flowing_and_it_recovers(world):
    cfg = config(fallback_mode="conservative", fallback_after_failures=3, fallback_recovery_samples=3)
    layer, runtime, clock, fake = world(queue_capacity=40, workers=2, cfg=cfg, fake=FakeRegistration())
    for _ in range(3):
        tick(runtime, clock)                                               # some healthy history first
    good_sample = runtime.collector.sample

    def broken():
        raise RuntimeError("sampler exploded")
    runtime.collector.sample = broken
    for _ in range(3):
        tick(runtime, clock)
    assert runtime.snapshot().failed_ticks == 3
    assert runtime.controller.in_fallback and runtime.admission.in_fallback
    snapshot = layer.snapshot()["admission"]
    assert snapshot["fallback"] is True and snapshot["limit"] == 20        # conservative: capacity // 2
    assert layer.submit("DURING", 1).result(timeout=5).code == SUCCESS     # registrations keep working in fallback

    runtime.collector.sample = good_sample
    for _ in range(12):
        tick(runtime, clock)
    assert not runtime.controller.in_fallback and not runtime.admission.in_fallback
    actions = [d.action for d in runtime.decisions()]
    assert ActionKind.FALLBACK_ENTER in actions and ActionKind.FALLBACK_EXIT in actions
    assert 20 <= runtime.admission.effective_limit() <= 40


def test_a_dead_controller_thread_is_caught_by_the_request_path_watchdog_with_no_help_from_it(world, gate):
    cfg = config(fallback_mode="conservative", watchdog_seconds=5.0)
    layer, runtime, clock, fake = world(queue_capacity=40, workers=2, cfg=cfg)
    futures = overload(layer, workers=2, queued=25, extra=0)               # depth 25
    assert layer.submit("ALIVE", 1).done() is False                        # controller considered alive: limit 40, admitted
    clock.now += 100.0                                                     # no tick, no heartbeat: the thread "died"
    refused = layer.submit("DEAD", 1)
    assert refused.done() and refused.result().code == ADMISSION_REJECTED  # fallback limit 20 <= depth 26
    assert layer.snapshot()["admission"]["watchdog_tripped"] is True
    gate.set()
    assert futures[0].result(timeout=5).code == SUCCESS


def test_the_baseline_fallback_is_identical_to_running_without_iasl(world, gate):
    layer, runtime, clock, fake = world(queue_capacity=10, workers=1, cfg=config(fallback_mode="baseline", watchdog_seconds=5.0))
    overload(layer, workers=1, queued=10, extra=0)
    clock.now += 100.0                                                     # watchdog trips
    extra = layer.submit("X", 1)
    assert extra.result().code == QUEUE_FULL                               # the plain full-queue answer, not an admission one
    assert layer.snapshot()["admission"]["rejected"] == 0


# ----------------------------------------------------------------------------- the loop thread

def test_the_loop_thread_ticks_on_its_own_and_stops_cleanly():
    layer = OSConcurrencyLayer(OSLayerConfig(10, 2, 2))
    layer.start()
    runtime = IASLRuntime(config(sampling_interval_s=0.1, stale_metric_seconds=0.5, watchdog_seconds=1.0, cooldown_seconds=0.1,
                                 increase_cooldown_seconds=0.1, reversal_lockout_seconds=0.1))
    runtime.attach(layer)
    try:
        runtime.start()
        assert runtime.running and runtime._thread.name == "iasl-controller" and runtime._thread.daemon
        assert wait_until(lambda: runtime.snapshot().ticks >= 4, timeout_seconds=5)
        assert runtime.snapshot().failed_ticks == 0
    finally:
        runtime.stop()
        layer.stop(timeout_seconds=3)
    assert not runtime.running
    runtime.stop()                                                         # stopping twice is harmless


def test_the_loop_survives_errors_in_a_tick_and_keeps_ticking():
    layer = OSConcurrencyLayer(OSLayerConfig(10, 2, 2))
    layer.start()
    runtime = IASLRuntime(config(sampling_interval_s=0.1, stale_metric_seconds=0.5, watchdog_seconds=1.0, cooldown_seconds=0.1,
                                 increase_cooldown_seconds=0.1, reversal_lockout_seconds=0.1, fallback_after_failures=100))
    runtime.attach(layer)

    def boom(*args):
        raise RuntimeError("analyzer exploded")
    runtime.analyzer.assess = boom
    try:
        runtime.start()
        assert wait_until(lambda: runtime.snapshot().failed_ticks >= 3, timeout_seconds=5)
        assert runtime.running                                             # the thread did not die
    finally:
        runtime.stop()
        layer.stop(timeout_seconds=3)
    assert layer.admission.effective_limit() == 10                         # and the admission limit was never disturbed
