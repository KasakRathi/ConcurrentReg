"""Defensive and edge paths that normal operation never reaches, each proven rather than assumed."""
import threading
import time

import pytest

from app.iasl.config import AdmissionBounds, IASLConfig
from app.iasl.controller import AdaptiveController
from app.iasl.metrics import MetricsCollector
from app.iasl.runtime import IASLRuntime
from app.iasl.types import ActionKind, MetricQuality
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import OSConcurrencyLayer
from tests.conftest import wait_until
from tests.test_iasl_controller import FakeApplier, HEALTHY, assessment
from tests.test_iasl_metrics import Clock, FakeLayer
from tests.test_iasl_analyzer import make_sample


@pytest.mark.parametrize("text, expected", [("1", True), ("true", True), ("YES", True), ("on", True),
                                            ("0", False), ("false", False), ("No", False), ("OFF", False)])
def test_every_documented_spelling_of_the_on_off_switch_is_understood(text, expected):
    assert IASLConfig.from_environment({"IASL_ENABLED": text}).enabled is expected


def test_the_switch_must_be_a_real_boolean_when_the_config_is_built_directly():
    for bad in ("yes", 1, None):
        with pytest.raises(ValueError, match="IASL_ENABLED"):
            IASLConfig(enabled=bad)


def test_resolving_bounds_for_an_impossible_layer_is_refused():
    for capacity, workers in ((0, 2), (10, 0)):
        with pytest.raises(ValueError):
            IASLConfig().resolve_bounds(capacity, workers)


def test_a_second_fallback_trigger_while_already_in_fallback_does_nothing():
    controller = AdaptiveController(IASLConfig(fallback_after_failures=1), AdmissionBounds(8, 208, 208), FakeApplier(208), 208,
                                    clock=lambda: 0.0)
    assert controller.record_failure(RuntimeError("a"), now=1.0).action is ActionKind.FALLBACK_ENTER
    assert controller.record_failure(RuntimeError("b"), now=2.0) is None
    assert sum(1 for d in controller.decisions() if d.action is ActionKind.FALLBACK_ENTER) == 1


def test_leaving_fallback_still_works_and_logs_if_the_admission_controller_refuses_the_hand_back(caplog):
    applier = FakeApplier(208)
    controller = AdaptiveController(IASLConfig(fallback_after_failures=1, fallback_recovery_samples=2), AdmissionBounds(8, 208, 208),
                                    applier, 208, clock=lambda: 0.0)
    controller.record_failure(RuntimeError("x"), now=1.0)
    applier.fail_set = True                                              # set_limit now raises
    with caplog.at_level("ERROR", logger="iasl"):
        controller.step(make_sample(taken_at=2.0), HEALTHY(), now=2.0)
        decision = controller.step(make_sample(taken_at=3.0), HEALTHY(), now=3.0)
    assert decision.action is ActionKind.FALLBACK_EXIT and not controller.in_fallback and not applier.fallback
    assert any("iasl_applier_failed" in r.getMessage() for r in caplog.records)


def test_a_recorder_whose_window_fails_makes_the_sample_invalid_instead_of_raising():
    class BadWindow:
        def counters(self):
            return {"completed": 0, "by_outcome": {}, "cancelled": 0, "invalid_observations": 0}

        def window(self, *args):
            raise RuntimeError("window exploded")
    collector = MetricsCollector(IASLConfig(), lambda: FakeLayer(), lambda: BadWindow(), clock=Clock())
    sample = collector.sample()
    assert sample.quality is MetricQuality.INVALID and any(i.startswith("recorder_failed:RuntimeError") for i in sample.issues)


def fast_config(**changes):
    base = dict(enabled=True, sampling_interval_s=0.1, stale_metric_seconds=0.5, watchdog_seconds=1.0, cooldown_seconds=0.1,
                increase_cooldown_seconds=0.1, reversal_lockout_seconds=0.1)
    base.update(changes)
    return IASLConfig(**base)


@pytest.fixture
def running_runtime():
    layer = OSConcurrencyLayer(OSLayerConfig(10, 2, 2))
    layer.start()
    runtime = IASLRuntime(fast_config())
    runtime.attach(layer)
    yield runtime
    runtime.stop(timeout_seconds=2)
    layer.stop(timeout_seconds=3)


def test_the_loops_last_line_of_defence_survives_even_a_tick_that_escapes_its_own_handling(running_runtime, caplog):
    attempts = []

    def explode():
        attempts.append(1)
        raise RuntimeError("escaped")
    running_runtime.tick = explode
    with caplog.at_level("ERROR", logger="iasl"):
        running_runtime.start()
        assert wait_until(lambda: len(attempts) >= 3, timeout_seconds=5)
        assert running_runtime.running                                   # the thread did not die
    assert any("iasl_loop_error" in r.getMessage() for r in caplog.records)


def test_a_slow_tick_makes_the_loop_skip_ahead_instead_of_firing_a_burst_of_catch_up_ticks(running_runtime):
    starts = []

    def slow():
        starts.append(time.monotonic())
        time.sleep(0.35)                                                 # more than three sampling intervals
    running_runtime.tick = slow
    running_runtime.start()
    time.sleep(1.4)
    running_runtime.stop(timeout_seconds=2)
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert len(starts) >= 3 and all(g >= 0.33 for g in gaps)             # never two ticks back to back to "catch up"
    assert len(starts) <= 5                                              # about 1.4 s / 0.35 s, not 14 ticks


def test_stopping_a_loop_that_will_not_stop_gives_up_after_the_timeout_and_says_so(caplog):
    layer = OSConcurrencyLayer(OSLayerConfig(10, 2, 2))
    layer.start()
    runtime = IASLRuntime(fast_config())
    runtime.attach(layer)
    release, entered = threading.Event(), threading.Event()

    def stuck():
        entered.set()
        release.wait(10)
    runtime.tick = stuck
    try:
        runtime.start()
        assert entered.wait(5)
        started = time.monotonic()
        with caplog.at_level("ERROR", logger="iasl"):
            runtime.stop(timeout_seconds=0.3)
        assert time.monotonic() - started < 2                            # it did not hang waiting for the stuck thread
        assert any("iasl_stop_timeout" in r.getMessage() for r in caplog.records)
    finally:
        release.set()
        layer.stop(timeout_seconds=3)
