"""Guardrails: bounds, step size, cooldown, reversal lockout, oscillation, invalid proposals; plus a fuzz of the invariants."""
import random

import pytest

from app.iasl import guardrails
from app.iasl.config import AdmissionBounds, IASLConfig
from app.iasl.types import ActionKind, ControlParameter, GuardrailResult, ParameterState, ProposedAction

INC, DEC = ActionKind.INCREASE, ActionKind.DECREASE
NAME = "admission_depth_limit"
# min 8, max 208, step 20, max move 40, cooldown 2 s (decrease), 4 s (increase), reversal lockout 8 s
PARAM = ControlParameter.from_config(IASLConfig(), AdmissionBounds(8, 208, 208))


def propose(kind, target, parameter=NAME):
    return ProposedAction(kind, parameter, target, "T", "test")


def review(kind, target, state, now=100.0, parameter=NAME):
    return guardrails.review(propose(kind, target, parameter), PARAM, state, now)


# ----------------------------------------------------------------------------- allow / clamp / bounds

def test_an_ordinary_change_is_allowed_unchanged():
    v = review(DEC, 130, ParameterState(150))
    assert (v.result, v.final_value, v.blocked_by) == (GuardrailResult.ALLOW, 130, None)
    v = review(INC, 170, ParameterState(150))
    assert (v.result, v.final_value) == (GuardrailResult.ALLOW, 170)


def test_a_decrease_below_the_minimum_is_clamped_to_it():
    v = review(DEC, -20, ParameterState(20))
    assert (v.result, v.final_value) == (GuardrailResult.CLAMP, 8) and "requested -20" in v.note


def test_an_increase_above_the_maximum_is_clamped_to_it():
    v = review(INC, 400, ParameterState(200))
    assert (v.result, v.final_value) == (GuardrailResult.CLAMP, 208)


def test_a_move_larger_than_the_step_limit_is_cut_to_the_step_limit():
    v = review(DEC, 20, ParameterState(150))                         # asked for -130, limit is 40
    assert (v.result, v.final_value) == (GuardrailResult.CLAMP, 110)
    v = review(INC, 208, ParameterState(100))
    assert (v.result, v.final_value) == (GuardrailResult.CLAMP, 140)


@pytest.mark.parametrize("kind, target, value", [(DEC, 0, 8), (INC, 999, 208)])
def test_a_change_with_nowhere_to_go_is_blocked_at_the_bound(kind, target, value):
    v = review(kind, target, ParameterState(value))
    assert (v.result, v.blocked_by, v.final_value) == (GuardrailResult.BLOCK, "at_bound", value)


# ----------------------------------------------------------------------------- invalid proposals

def test_an_unknown_parameter_is_rejected():
    v = review(DEC, 100, ParameterState(150), parameter="worker_count")
    assert (v.result, v.blocked_by) == (GuardrailResult.BLOCK, "unknown_parameter")


@pytest.mark.parametrize("kind", [ActionKind.HOLD, ActionKind.FALLBACK_ENTER, ActionKind.RESET])
def test_only_increase_and_decrease_are_changes(kind):
    assert review(kind, 100, ParameterState(150)).blocked_by == "invalid_action"


@pytest.mark.parametrize("target", [None, True, 100.5, "100"])
def test_a_target_that_is_not_a_whole_number_is_rejected(target):
    assert review(DEC, target, ParameterState(150)).blocked_by == "invalid_target"


@pytest.mark.parametrize("kind, target", [(DEC, 150), (DEC, 160), (INC, 150), (INC, 140)])
def test_a_proposal_that_does_not_move_in_its_stated_direction_is_rejected(kind, target):
    assert review(kind, target, ParameterState(150)).blocked_by == "direction_mismatch"


# ----------------------------------------------------------------------------- timing

def test_cooldown_applies_per_direction_a_decrease_is_prompt_an_increase_is_slow():
    after_decrease = ParameterState(150, last_change_at=100.0, last_change_kind=DEC)
    assert review(DEC, 130, after_decrease, now=101.0).blocked_by == "cooldown"        # 1 s < 2 s
    assert review(DEC, 130, after_decrease, now=102.0).result is GuardrailResult.ALLOW  # 2 s >= 2 s
    assert review(INC, 170, after_decrease, now=103.0).blocked_by == "cooldown"        # 3 s < 4 s

    after_increase = ParameterState(150, last_change_at=100.0, last_change_kind=INC)
    # a needed decrease right after an increase only waits the SHORT cooldown
    assert review(DEC, 130, after_increase, now=102.5).result is GuardrailResult.ALLOW
    assert review(INC, 170, after_increase, now=102.5).blocked_by == "cooldown"
    assert review(INC, 170, after_increase, now=104.0).result is GuardrailResult.ALLOW


def test_an_increase_cannot_follow_a_decrease_before_the_lockout_has_passed():
    state = ParameterState(150, last_change_at=100.0, last_change_kind=DEC)
    blocked = review(INC, 170, state, now=105.0)                      # past the 4 s cooldown, inside the 8 s lockout
    assert blocked.blocked_by == "reversal_lockout"
    assert review(INC, 170, state, now=108.0).result is GuardrailResult.ALLOW


def test_the_lockout_does_not_apply_to_an_increase_after_an_increase():
    state = ParameterState(150, last_change_at=100.0, last_change_kind=INC)
    assert review(INC, 170, state, now=104.5).result is GuardrailResult.ALLOW


def test_the_first_ever_change_has_no_cooldown():
    assert review(DEC, 130, ParameterState(150)).result is GuardrailResult.ALLOW


def test_an_oscillation_hold_blocks_every_change_until_it_expires():
    state = ParameterState(150, hold_until=130.0)
    assert review(DEC, 130, state, now=120.0).blocked_by == "oscillation_hold"
    assert review(INC, 170, state, now=129.9).blocked_by == "oscillation_hold"
    assert review(DEC, 130, state, now=130.0).result is GuardrailResult.ALLOW


def test_bounds_are_reported_before_timing_so_the_reason_is_the_useful_one():
    state = ParameterState(8, last_change_at=100.0, last_change_kind=DEC, hold_until=999.0)
    assert review(DEC, 0, state, now=100.5).blocked_by == "at_bound"


# ----------------------------------------------------------------------------- oscillation bookkeeping

def test_after_applied_records_the_change_and_the_first_change_is_not_a_reversal():
    state, oscillating = guardrails.after_applied(ParameterState(150), PARAM, DEC, 130, now=10.0)
    assert (state.value, state.last_change_at, state.last_change_kind) == (130, 10.0, DEC)
    assert state.reversal_times == () and not oscillating


def test_same_direction_changes_are_not_reversals():
    state = ParameterState(150)
    for t in (10, 20, 30, 40):
        state, oscillating = guardrails.after_applied(state, PARAM, DEC, state.value - 10, now=float(t))
        assert state.reversal_times == () and not oscillating


def test_repeated_reversals_inside_the_window_start_a_hold():
    state, kinds = ParameterState(150), [DEC, INC, DEC, INC]
    flags = []
    for i, kind in enumerate(kinds):
        state, oscillating = guardrails.after_applied(state, PARAM, kind, 100 + i, now=10.0 * (i + 1))
        flags.append(oscillating)
    assert flags == [False, False, False, True]                      # 3 reversals (DEC>INC, INC>DEC, DEC>INC)
    assert state.hold_until == pytest.approx(40.0 + PARAM.oscillation_hold_s)
    assert state.reversal_times == ()                                 # cleared once the hold starts


def test_reversals_outside_the_window_are_forgotten():
    state = ParameterState(150)
    for i, kind in enumerate([DEC, INC, DEC, INC]):                   # 100 s apart: window is 60 s
        state, oscillating = guardrails.after_applied(state, PARAM, kind, 100 + i, now=100.0 * (i + 1))
        assert not oscillating
    assert len(state.reversal_times) == 1


# ----------------------------------------------------------------------------- invariants under fuzz

def test_fuzz_a_verdict_never_leaves_the_bounds_or_exceeds_the_step_limit():
    rng = random.Random(2026)
    for _ in range(20_000):
        value = rng.randint(PARAM.minimum, PARAM.maximum)
        state = ParameterState(
            value, last_change_at=rng.choice([None, 100.0 - rng.random() * 20]),
            last_change_kind=rng.choice([None, INC, DEC]), hold_until=rng.choice([0.0, 110.0]))
        kind = rng.choice([INC, DEC])
        target = rng.randint(-100, 400)
        v = review(kind, target, state, now=100.0 + rng.random() * 10)
        if v.result is GuardrailResult.BLOCK:
            assert v.final_value == value                               # a block never moves anything
            continue
        assert PARAM.minimum <= v.final_value <= PARAM.maximum
        assert 0 < abs(v.final_value - value) <= PARAM.max_move
        assert (v.final_value > value) == (kind is INC)                 # a verdict never reverses the proposal's direction
