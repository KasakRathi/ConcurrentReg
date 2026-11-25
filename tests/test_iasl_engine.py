"""DecisionEngine: every rule, in order, as a pure function."""
import copy

import pytest

from app.iasl.config import IASLConfig
from app.iasl.engine import decide
from app.iasl.types import (
    ActionKind, Assessment, ControlParameter, MetricQuality, ParameterState, Signal, SystemState,
)

H, P, O = SystemState.HEALTHY, SystemState.UNDER_PRESSURE, SystemState.OVERLOADED
PRIMARY_NAMES = ("queue_utilization", "queue_wait_p95_s", "queue_full_rejection_rate", "error_rate")
CORROBORATING_NAMES = ("worker_utilization", "semaphore_waiting_ratio")


def make_param(minimum=8, maximum=208, initial=208):
    from app.iasl.config import AdmissionBounds
    return ControlParameter.from_config(IASLConfig(), AdmissionBounds(minimum, maximum, initial))


def make_assessment(state, levels=None, quality=MetricQuality.OK, held=False, reason="test"):
    levels = levels or {}
    signals = tuple(
        Signal(name, "primary" if name in PRIMARY_NAMES else "corroborating", 0.9 if levels.get(name) else 0.0,
               levels.get(name, 0), 0.5, 0.85)
        for name in PRIMARY_NAMES + CORROBORATING_NAMES
    )
    return Assessment(state=state, previous_state=state, quality=quality, held=held,
                      candidate=None if held else state, signals=signals, reason=reason)


PARAM = make_param()          # min 8, max 208, step round(0.1 * 200) = 20, overload move 40


def test_the_step_comes_from_the_span_and_is_at_least_one():
    assert PARAM.step == 20 and PARAM.max_move == 40
    assert make_param(minimum=5, maximum=8, initial=8).step == 1


def test_r0_fallback_holds():
    action = decide(make_assessment(O), PARAM, ParameterState(100), in_fallback=True)
    assert (action.kind, action.rule_id) == (ActionKind.HOLD, "R0")


@pytest.mark.parametrize("quality, held", [
    (MetricQuality.INVALID, True), (MetricQuality.DEGRADED, True), (MetricQuality.STALE, True),
    (MetricQuality.RESTART, True), (MetricQuality.OK, True),
])
def test_r1_unreliable_metrics_never_change_anything_even_when_the_held_state_is_healthy(quality, held):
    for state in (H, P, O):
        action = decide(make_assessment(state, quality=quality, held=held), PARAM, ParameterState(100))
        assert (action.kind, action.rule_id, action.target) == (ActionKind.HOLD, "R1", None)


def test_r2_overloaded_decreases_by_the_overload_move():
    action = decide(make_assessment(O, {"queue_utilization": 2, "worker_utilization": 1}), PARAM, ParameterState(150))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.DECREASE, "R2", 150 - 40)
    assert "queue_utilization" in action.reason


def test_r2_the_proposed_target_is_not_pre_clamped_so_the_guardrails_do_the_clamping():
    action = decide(make_assessment(O, {"queue_utilization": 2}), PARAM, ParameterState(20))
    assert action.target == -20                                      # below the minimum on purpose


def test_r2_at_the_minimum_overloaded_holds_and_says_it_cannot_restrict_further():
    action = decide(make_assessment(O, {"queue_utilization": 2}), PARAM, ParameterState(8))
    assert (action.kind, action.rule_id) == (ActionKind.HOLD, "R2") and "minimum" in action.reason


@pytest.mark.parametrize("driver", ["queue_utilization", "queue_full_rejection_rate"])
def test_r3_queue_driven_pressure_decreases_by_one_step(driver):
    action = decide(make_assessment(P, {driver: 1}), PARAM, ParameterState(150))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.DECREASE, "R3", 130)


def test_r3_at_the_minimum_holds():
    action = decide(make_assessment(P, {"queue_utilization": 1}), PARAM, ParameterState(8))
    assert (action.kind, action.rule_id) == (ActionKind.HOLD, "R3")


@pytest.mark.parametrize("driver", ["queue_wait_p95_s", "error_rate", "worker_utilization", "semaphore_waiting_ratio"])
def test_r4_pressure_that_is_not_queue_driven_holds_and_never_adds_admission(driver):
    action = decide(make_assessment(P, {driver: 1}), PARAM, ParameterState(150))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.HOLD, "R4", None)


def test_r4_a_queue_signal_at_level_zero_does_not_count_as_queue_driven():
    action = decide(make_assessment(P, {"queue_utilization": 0, "queue_wait_p95_s": 1}), PARAM, ParameterState(150))
    assert action.rule_id == "R4"


def test_r5_healthy_below_the_maximum_increases_by_one_step():
    action = decide(make_assessment(H), PARAM, ParameterState(150))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.INCREASE, "R5", 170)


def test_r6_healthy_at_the_maximum_holds():
    action = decide(make_assessment(H), PARAM, ParameterState(208))
    assert (action.kind, action.rule_id) == (ActionKind.HOLD, "R6")


def test_every_proposal_names_the_controlled_parameter():
    for state in (H, P, O):
        assert decide(make_assessment(state, {"queue_utilization": 2}), PARAM, ParameterState(100)).parameter == PARAM.name


def test_the_engine_is_pure_same_input_same_output_and_inputs_untouched():
    assessment, state = make_assessment(O, {"queue_utilization": 2}), ParameterState(120)
    before = copy.deepcopy((assessment.signals, state))
    first, second = decide(assessment, PARAM, state), decide(assessment, PARAM, state)
    assert first == second
    assert (assessment.signals, state) == before


# ----------------------------------------------------------------------------- act on the current sample, not only the slow state

def with_candidate(assessment, candidate):
    import dataclasses
    return dataclasses.replace(assessment, candidate=candidate)


@pytest.mark.parametrize("state", [P, O])
def test_r1b_while_the_state_is_still_bad_but_this_sample_is_healthy_the_engine_neither_tightens_nor_relaxes(state):
    a = with_candidate(make_assessment(state, {"queue_utilization": 2}), H)
    action = decide(a, PARAM, ParameterState(100))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.HOLD, "R1b", None)
    assert "recovering" in action.reason


def test_a_partly_recovered_overload_uses_the_milder_pressure_rule():
    a = with_candidate(make_assessment(O, {"queue_utilization": 1}), P)
    action = decide(a, PARAM, ParameterState(100))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.DECREASE, "R3", 100 - PARAM.step)   # not R2's bigger move


def test_r1c_a_healthy_state_never_adds_admission_while_this_sample_already_shows_pressure():
    for candidate in (P, O):
        a = with_candidate(make_assessment(H), candidate)
        action = decide(a, PARAM, ParameterState(100))
        assert (action.kind, action.rule_id) == (ActionKind.HOLD, "R1c")


def test_a_pressure_state_with_one_worse_sample_still_tightens_by_the_mild_step():
    a = with_candidate(make_assessment(P, {"queue_utilization": 1}), O)
    action = decide(a, PARAM, ParameterState(100))
    assert (action.kind, action.rule_id, action.target) == (ActionKind.DECREASE, "R3", 100 - PARAM.step)


def test_relaxing_needs_both_a_healthy_state_and_a_healthy_sample():
    a = with_candidate(make_assessment(H), H)
    assert decide(a, PARAM, ParameterState(100)).kind is ActionKind.INCREASE
