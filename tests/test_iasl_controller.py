"""AdaptiveController: apply/decide/record cycle, limits, cooldown, oscillation, fallback, decision records."""
import json
import random

import pytest

from app.iasl.config import AdmissionBounds, IASLConfig
from app.iasl.controller import AdaptiveController
from app.iasl.types import (
    ActionKind, Assessment, GuardrailResult, MetricQuality, Signal, StateTransition, SystemState,
)
from tests.test_iasl_analyzer import make_sample
from tests.test_iasl_engine import CORROBORATING_NAMES, PRIMARY_NAMES

H, P, O = SystemState.HEALTHY, SystemState.UNDER_PRESSURE, SystemState.OVERLOADED
INC, DEC, HOLD = ActionKind.INCREASE, ActionKind.DECREASE, ActionKind.HOLD

REQUIRED_FIELDS = {"id", "event", "at_wall", "at_monotonic", "previous_state", "current_state", "metrics_used", "action",
                   "parameter", "previous_value", "new_value", "rule", "reason", "guardrail", "blocked_by",
                   "suppressed_since_last"}


class FakeApplier:
    """Stands in for the admission controller; enforces the same hard bound."""

    def __init__(self, capacity=208, fail_set=False):
        self.capacity, self.limit, self.fail_set = capacity, capacity, fail_set
        self.calls, self.beats, self.fallback = [], 0, False

    def set_limit(self, value):
        if self.fail_set or not 1 <= value <= self.capacity:
            raise ValueError(f"limit {value} outside 1..{self.capacity}")
        self.limit = value
        self.calls.append(("set_limit", value))

    def heartbeat(self):
        self.beats += 1

    def enter_fallback(self):
        self.fallback = True
        self.calls.append(("enter_fallback",))

    def exit_fallback(self):
        self.fallback = False
        self.calls.append(("exit_fallback",))


def assessment(state, levels=None, quality=MetricQuality.OK, held=False, transition=None, reason="test"):
    levels = levels or {}
    signals = tuple(
        Signal(name, "primary" if name in PRIMARY_NAMES else "corroborating", 0.9 if levels.get(name) else 0.0,
               levels.get(name, 0), 0.5, 0.85)
        for name in PRIMARY_NAMES + CORROBORATING_NAMES)
    return Assessment(state=state, previous_state=state, quality=quality, held=held, candidate=None if held else state,
                      signals=signals, transition=transition, reason=reason)


OVERLOADED = lambda: assessment(O, {"queue_utilization": 2, "worker_utilization": 1})          # noqa: E731
PRESSURE = lambda: assessment(P, {"queue_utilization": 1})                                    # noqa: E731
HEALTHY = lambda: assessment(H)                                                               # noqa: E731
UNTRUSTED = lambda q=MetricQuality.INVALID: assessment(H, quality=q, held=True, reason="bad data")  # noqa: E731


def make_controller(applier=None, bounds=None, fallback_limit=None, **config_changes):
    bounds = bounds or AdmissionBounds(minimum=8, maximum=208, initial=208)
    applier = applier or FakeApplier(bounds.maximum)
    config = IASLConfig(**config_changes)
    controller = AdaptiveController(config, bounds, applier, bounds.maximum if fallback_limit is None else fallback_limit,
                                    clock=lambda: 0.0)
    return controller, applier


def tick(controller, a, now):
    return controller.step(make_sample(taken_at=now), a, now=now)


# ----------------------------------------------------------------------------- the cycle

def test_a_decrease_is_applied_through_the_admission_controller_and_recorded_completely():
    controller, applier = make_controller()
    decision = tick(controller, OVERLOADED(), now=10.0)
    assert decision.action is DEC and (decision.previous_value, decision.new_value) == (208, 168)
    assert controller.value == 168 and applier.limit == 168
    assert decision.guardrail is GuardrailResult.ALLOW and decision.blocked_by is None
    assert decision.rule == "R2" and decision.parameter == "admission_depth_limit"
    assert (decision.previous_state, decision.current_state) == (O, O)
    assert "signals" in decision.metrics_used and "queue_utilization" in decision.metrics_used["signals"]
    assert decision.at_wall and decision.at_monotonic == 10.0 and "overloaded" in decision.reason


def test_every_decision_record_has_all_the_required_fields_and_is_json_serialisable():
    controller, _ = make_controller()
    decision = tick(controller, OVERLOADED(), now=10.0)
    record = decision.as_dict()
    assert REQUIRED_FIELDS <= set(record)
    json.dumps(record)                                                # must not raise


def test_decisions_are_logged_as_json_on_the_iasl_logger(caplog):
    controller, _ = make_controller()
    with caplog.at_level("INFO", logger="iasl"):
        tick(controller, OVERLOADED(), now=10.0)
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "iasl"]
    assert lines and lines[0]["event"] == "iasl_decision" and lines[0]["action"] == "DECREASE"


def test_at_most_one_change_per_tick_and_never_more_than_the_step_limit():
    controller, applier = make_controller()
    tick(controller, OVERLOADED(), now=10.0)
    assert [c[0] for c in applier.calls] == ["set_limit"] and applier.calls[0][1] == 168      # 40 = 2 x 20, once


def test_healthy_raises_the_limit_back_one_step_at_a_time_with_the_slower_cooldown():
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 100), applier=FakeApplier(208))
    t, seen = 0.0, []
    for _ in range(12):
        t += 1.0                                                      # 1 s ticks; increase cooldown is 4 s
        d = tick(controller, HEALTHY(), now=t)
        if d and d.action is INC:
            seen.append((t, d.new_value))
    assert seen[0] == (1.0, 120)                                      # first change has no cooldown
    gaps = [b[0] - a[0] for a, b in zip(seen, seen[1:])]
    assert all(g >= 4.0 for g in gaps) and [v for _, v in seen] == [120, 140, 160][:len(seen)]


def test_the_limit_never_goes_below_the_minimum_or_above_the_maximum():
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 60), applier=FakeApplier(208))
    t = 0.0
    for _ in range(40):
        t += 3.0
        tick(controller, OVERLOADED(), now=t)
    assert controller.value == 8 and applier.limit == 8               # reached the floor, stopped there
    for _ in range(200):
        t += 5.0
        tick(controller, HEALTHY(), now=t)
    assert controller.value == 208 and applier.limit == 208           # climbed back, stopped at the ceiling


def test_overload_at_the_floor_holds_without_error_or_spam(caplog):
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 8), applier=FakeApplier(208))
    with caplog.at_level("INFO", logger="iasl"):
        results = [tick(controller, OVERLOADED(), now=3.0 * i) for i in range(1, 30)]
    assert applier.calls == [] and controller.value == 8
    assert sum(1 for r in results if r) <= 1                          # at most one record; the rest are counted
    assert controller.status(now=100.0)["suppressed_idle_ticks_pending"] >= 27


# ----------------------------------------------------------------------------- cooldown and blocking

def test_a_second_decrease_inside_the_cooldown_is_blocked_and_the_value_does_not_change():
    controller, applier = make_controller()
    tick(controller, OVERLOADED(), now=10.0)
    blocked = tick(controller, OVERLOADED(), now=10.5)                # cooldown is 2 s
    assert blocked.action is HOLD and blocked.guardrail is GuardrailResult.BLOCK and blocked.blocked_by == "cooldown"
    assert controller.value == 168 and len(applier.calls) == 1
    assert "blocked (cooldown)" in blocked.reason and "overloaded" in blocked.reason     # says what was wanted
    assert tick(controller, OVERLOADED(), now=12.0).new_value == 128                     # allowed once the cooldown passed


def test_repeated_identical_blocks_are_counted_not_logged_and_the_next_event_reports_the_count():
    controller, _ = make_controller()
    tick(controller, OVERLOADED(), now=10.0)
    first = tick(controller, OVERLOADED(), now=10.2)
    repeats = [tick(controller, OVERLOADED(), now=10.2 + 0.2 * i) for i in range(1, 6)]
    assert first is not None and all(r is None for r in repeats)
    nxt = tick(controller, OVERLOADED(), now=13.0)                    # applied: first event after the quiet stretch
    assert nxt.action is DEC and nxt.suppressed_since_last == 5


def test_the_applier_refusing_the_value_leaves_the_state_unchanged_and_is_recorded():
    controller, applier = make_controller(applier=FakeApplier(208, fail_set=True))
    decision = tick(controller, OVERLOADED(), now=10.0)
    assert decision.action is HOLD and decision.blocked_by == "applier_rejected"
    assert controller.value == 208 and applier.limit == 208


def test_a_state_transition_is_logged_even_when_no_limit_changes():
    controller, _ = make_controller(bounds=AdmissionBounds(8, 208, 208))
    transition = StateTransition(H, P, "t", "HEALTHY -> UNDER_PRESSURE: 2 consecutive samples")
    d = tick(controller, assessment(P, {"queue_wait_p95_s": 1}, transition=transition), now=10.0)
    assert d.action is HOLD and "state changed" in d.reason and d.metrics_used["transition"] == transition.reason


def test_unreliable_or_restart_samples_never_raise_the_limit():
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 100), applier=FakeApplier(208))
    for i, q in enumerate([MetricQuality.INVALID, MetricQuality.STALE, MetricQuality.RESTART, MetricQuality.DEGRADED]):
        tick(controller, assessment(H, quality=q, held=True), now=10.0 * (i + 1))
    assert applier.calls == [] and controller.value == 100


# ----------------------------------------------------------------------------- oscillation

def test_repeated_reversals_trigger_a_hold_that_blocks_further_changes():
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 100), applier=FakeApplier(208))
    t = 0.0
    kinds = []
    for a in (OVERLOADED, HEALTHY, OVERLOADED, HEALTHY):              # 10 s apart: cooldowns and lockout all satisfied
        t += 10.0
        d = tick(controller, a(), now=t)
        kinds.append(d.action if d else None)
    assert kinds == [DEC, INC, DEC, INC]
    assert any(d.blocked_by == "oscillation_detected" for d in controller.decisions())
    t += 10.0
    held = tick(controller, OVERLOADED(), now=t)                      # inside the 30 s hold
    assert held.action is HOLD and held.blocked_by == "oscillation_hold"
    value_during_hold = controller.value
    t += 31.0
    assert tick(controller, OVERLOADED(), now=t).action is DEC       # hold over
    assert controller.value < value_during_hold


# ----------------------------------------------------------------------------- fallback

def test_enough_consecutive_untrusted_ticks_enter_fallback_and_the_limit_goes_to_the_fallback_value():
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 100), applier=FakeApplier(208),
                                          fallback_limit=208, fallback_after_degraded=3)
    assert tick(controller, UNTRUSTED(), 1.0) is None and tick(controller, UNTRUSTED(), 2.0) is None
    d = tick(controller, UNTRUSTED(), 3.0)
    assert d.action is ActionKind.FALLBACK_ENTER and (d.previous_value, d.new_value) == (100, 208)
    assert controller.in_fallback and controller.value == 208 and applier.fallback
    assert "metrics unreliable for 3 consecutive ticks" in d.reason


def test_one_good_tick_resets_the_untrusted_streak():
    controller, applier = make_controller(fallback_after_degraded=3)
    tick(controller, UNTRUSTED(), 1.0)
    tick(controller, UNTRUSTED(), 2.0)
    tick(controller, HEALTHY(), 3.0)
    tick(controller, UNTRUSTED(), 4.0)
    tick(controller, UNTRUSTED(), 5.0)
    assert not controller.in_fallback


def test_a_single_restart_is_not_counted_as_unreliable():
    controller, _ = make_controller(fallback_after_degraded=2)
    tick(controller, assessment(H, quality=MetricQuality.RESTART, held=True), 1.0)
    tick(controller, assessment(H, quality=MetricQuality.RESTART, held=True), 2.0)
    assert not controller.in_fallback


def test_consecutive_tick_failures_enter_fallback_and_a_success_resets_the_count():
    controller, applier = make_controller(fallback_after_failures=3)
    controller.record_failure(RuntimeError("a"), now=1.0)
    controller.record_failure(RuntimeError("b"), now=2.0)
    controller.record_success()
    assert controller.record_failure(RuntimeError("c"), now=3.0) is None and not controller.in_fallback
    controller.record_failure(RuntimeError("d"), now=4.0)
    d = controller.record_failure(RuntimeError("e"), now=5.0)
    assert d.action is ActionKind.FALLBACK_ENTER and controller.in_fallback and "RuntimeError: e" in d.reason


def test_while_in_fallback_the_limit_is_pinned_whatever_the_metrics_say():
    controller, applier = make_controller(fallback_limit=150, fallback_after_failures=1)
    controller.record_failure(RuntimeError("x"), now=1.0)
    before = list(applier.calls)
    for i in range(5):
        tick(controller, OVERLOADED(), now=2.0 + i)
    assert applier.calls == before and controller.value == 150


def test_fallback_exits_after_enough_healthy_ticks_without_a_jump_then_resumes_stepwise():
    controller, applier = make_controller(fallback_limit=150, fallback_after_failures=1, fallback_recovery_samples=3)
    controller.record_failure(RuntimeError("x"), now=1.0)
    tick(controller, HEALTHY(), 2.0)
    tick(controller, UNTRUSTED(), 3.0)                                # breaks the healthy run
    tick(controller, HEALTHY(), 4.0)
    tick(controller, HEALTHY(), 5.0)
    d = tick(controller, HEALTHY(), 6.0)
    assert d.action is ActionKind.FALLBACK_EXIT and not controller.in_fallback and not applier.fallback
    assert applier.calls[-2:] == [("set_limit", 150), ("exit_fallback",)]       # handed back at the fallback value first
    assert controller.value == 150
    assert tick(controller, OVERLOADED(), 6.5) .blocked_by == "cooldown"        # no immediate move after exit
    assert tick(controller, OVERLOADED(), 9.0).new_value == 110                 # then one normal step from 150


def test_the_fallback_value_is_kept_inside_the_bounds():
    controller, _ = make_controller(bounds=AdmissionBounds(8, 50, 50), applier=FakeApplier(50), fallback_limit=500,
                                    fallback_after_failures=1)
    assert controller.record_failure(RuntimeError("x"), now=1.0).new_value == 50
    controller, _ = make_controller(bounds=AdmissionBounds(8, 50, 50), applier=FakeApplier(50), fallback_limit=1,
                                    fallback_after_failures=1)
    assert controller.record_failure(RuntimeError("x"), now=1.0).new_value == 8


def test_the_heartbeat_is_sent_every_tick_and_a_failing_heartbeat_does_not_break_the_loop():
    controller, applier = make_controller()
    for i in range(4):
        tick(controller, HEALTHY(), float(i))
    assert applier.beats == 4

    def broken():
        raise RuntimeError("no heartbeat")
    applier.heartbeat = broken
    tick(controller, HEALTHY(), 10.0)                                 # must not raise


# ----------------------------------------------------------------------------- reinitialise, log, status

def test_reinitialize_recomputes_the_bounds_clears_fallback_and_records_a_reset():
    controller, applier = make_controller(fallback_after_failures=1)
    controller.record_failure(RuntimeError("x"), now=1.0)
    d = controller.reinitialize(AdmissionBounds(4, 40, 40), fallback_limit=40, now=2.0)
    assert d.action is ActionKind.RESET and not controller.in_fallback
    assert (controller.param.minimum, controller.param.maximum, controller.value) == (4, 40, 40)
    assert controller.param.step == 4                                 # round(0.1 * 36)


def test_the_decision_log_is_bounded_and_ordered():
    controller, _ = make_controller(decision_log_size=10)
    t = 0.0
    for _ in range(60):
        t += 1.0
        tick(controller, OVERLOADED() if int(t) % 2 else HEALTHY(), now=t)
    decisions = controller.decisions()
    assert len(decisions) == 10
    assert [d.id for d in decisions] == sorted(d.id for d in decisions)
    assert controller.decisions(limit=3) == decisions[-3:]
    assert controller.last_decision is decisions[-1]


def test_status_summarises_the_controller_for_the_api():
    controller, _ = make_controller()
    tick(controller, OVERLOADED(), now=10.0)
    status = controller.status(now=11.0)
    assert status["parameter"] == {"name": "admission_depth_limit", "value": 168, "minimum": 8, "maximum": 208,
                                   "initial": 208, "step": 20}
    assert status["changes"] == 1 and status["ticks"] == 1 and status["fallback_active"] is False
    assert status["last_decision"]["action"] == "DECREASE"
    json.dumps(status)


# ----------------------------------------------------------------------------- invariants under fuzz

def test_fuzz_the_whole_loop_never_breaks_a_safety_invariant():
    rng = random.Random(4242)
    controller, applier = make_controller(bounds=AdmissionBounds(8, 208, 208), applier=FakeApplier(208),
                                          fallback_after_degraded=6, fallback_recovery_samples=4, decision_log_size=50)
    generators = [OVERLOADED, PRESSURE, HEALTHY, UNTRUSTED,
                  lambda: assessment(P, {"queue_wait_p95_s": 1}),
                  lambda: assessment(H, quality=MetricQuality.RESTART, held=True)]
    t = 0.0
    for _ in range(6000):
        t += rng.choice([0.1, 0.5, 1.0, 2.5, 5.0, 12.0])
        calls_before = len(applier.calls)
        if rng.random() < 0.02:
            controller.record_failure(RuntimeError("fuzz"), now=t)
        else:
            tick(controller, rng.choice(generators)(), now=t)
            controller.record_success()
        new_calls = applier.calls[calls_before:]
        limit_changes = [c for c in new_calls if c[0] == "set_limit"]
        assert len(limit_changes) <= 1                                           # one change per tick
        assert 1 <= applier.limit <= 208 and 8 <= controller.value <= 208        # hard bounds
        assert len(controller.decisions()) <= 50                                 # bounded log
    applied = [d for d in controller.decisions() if d.action in (INC, DEC)]
    for d in applied:
        assert abs(d.new_value - d.previous_value) <= controller.param.max_move
        assert 8 <= d.new_value <= 208
    for earlier, later in zip(applied, applied[1:]):
        gap = later.at_monotonic - earlier.at_monotonic
        needed = controller.param.increase_cooldown_s if later.action is INC else controller.param.cooldown_s
        assert gap >= needed - 1e-9                                              # cooldown always respected
        if later.action is INC and earlier.action is DEC:
            assert gap >= controller.param.reversal_lockout_s - 1e-9            # lockout always respected
