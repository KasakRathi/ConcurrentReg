"""Safety guardrails: every proposed change passes through here before anything is applied.

Pure functions over immutable values (no clock of their own: `now` is passed in), so they are
deterministic to test. The guardrails can only make a change smaller or refuse it; they never create
one. docs/iasl/IASL_DESIGN.md section 6.3.
"""

from app.iasl.types import ActionKind, GuardrailResult, ParameterState, Verdict


def review(proposed, param, state, now):
    """ALLOW, CLAMP or BLOCK a proposed INCREASE/DECREASE."""
    if proposed.parameter != param.name:
        return _block(state, "unknown_parameter", f"{proposed.parameter!r} is not a controllable parameter")
    if proposed.kind not in (ActionKind.INCREASE, ActionKind.DECREASE):
        return _block(state, "invalid_action", f"{proposed.kind} is not a change")
    target = proposed.target
    if isinstance(target, bool) or not isinstance(target, int):
        return _block(state, "invalid_target", f"target {target!r} is not a whole number")
    increasing = proposed.kind is ActionKind.INCREASE
    if (increasing and target <= state.value) or (not increasing and target >= state.value):
        return _block(state, "direction_mismatch", f"{proposed.kind.value} to {target} from {state.value}")

    # Step size, then hard bounds. Either may shrink the move; if nothing is left, there is nothing to do.
    final = target
    if abs(final - state.value) > param.max_move:
        final = state.value + param.max_move if increasing else state.value - param.max_move
    final = max(param.minimum, min(param.maximum, final))
    if final == state.value:
        return _block(state, "at_bound", f"already at {'maximum' if increasing else 'minimum'} ({state.value})")

    if now < state.hold_until:
        return _block(state, "oscillation_hold", f"holding for {state.hold_until - now:.1f}s more after repeated reversals")
    if state.last_change_at is not None:
        elapsed = now - state.last_change_at
        needed = param.increase_cooldown_s if increasing else param.cooldown_s
        if elapsed < needed:
            return _block(state, "cooldown", f"{elapsed:.1f}s since the last change; need {needed:g}s before this {proposed.kind.value}")
        if increasing and state.last_change_kind is ActionKind.DECREASE and elapsed < param.reversal_lockout_s:
            return _block(state, "reversal_lockout",
                          f"{elapsed:.1f}s since a decrease; need {param.reversal_lockout_s:g}s to observe its effect first")
    result = GuardrailResult.CLAMP if final != target else GuardrailResult.ALLOW
    note = "" if result is GuardrailResult.ALLOW else f"requested {target}, allowed {final} (step/bounds)"
    return Verdict(result, final, None, note)


def after_applied(state, param, kind, new_value, now):
    """The parameter state after a change was applied, plus whether repeated reversals were just detected."""
    reversals = tuple(t for t in state.reversal_times if now - t <= param.oscillation_window_s)
    flipped = state.last_change_kind in (ActionKind.INCREASE, ActionKind.DECREASE) and state.last_change_kind is not kind
    if flipped:
        reversals += (now,)
    oscillating = len(reversals) >= param.max_reversals
    hold_until = now + param.oscillation_hold_s if oscillating else state.hold_until
    return (
        ParameterState(value=new_value, last_change_at=now, last_change_kind=kind, hold_until=hold_until,
                       reversal_times=() if oscillating else reversals),
        oscillating,
    )


def _block(state, reason, note):
    return Verdict(GuardrailResult.BLOCK, state.value, reason, note)


__all__ = ["review", "after_applied"]
