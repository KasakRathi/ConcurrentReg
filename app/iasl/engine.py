"""The decision engine: a pure function from (assessment, parameter state) to ONE proposed action.

No side effects, no clock, no I/O, so every rule can be tested with plain values. It only PROPOSES;
the guardrails decide whether the proposal may happen. Rules are checked in order, first match wins
(docs/iasl/IASL_DESIGN.md section 6.2). Rule ids appear in every decision so a result can be traced
to the rule that produced it.
"""
from app.iasl.types import STATE_RANK, ActionKind, MetricQuality, ProposedAction, SystemState

QUEUE_RELATED = ("queue_utilization", "queue_full_rejection_rate")


def decide(assessment, param, state, in_fallback=False):
    value = state.value

    def hold(rule, reason):
        return ProposedAction(ActionKind.HOLD, param.name, None, rule, reason)

    if in_fallback:
        return hold("R0", "fallback active; limit pinned at the fallback value")
    if assessment.held or assessment.quality is not MetricQuality.OK:
        return hold("R1", f"metrics not reliable ({assessment.quality.value}): {assessment.reason}; never increasing on bad data")

    signals = {s.name: s for s in assessment.signals}
    effective, candidate = assessment.state, assessment.candidate
    # The analyzer's STATE is deliberately slow to recover; act on the state AND on what this sample shows.
    if STATE_RANK[candidate] < STATE_RANK[effective]:
        if candidate is SystemState.HEALTHY:
            return hold("R1b", f"state is still {effective.value} but this sample looks healthy; recovering, "
                               "so neither tightening further nor relaxing yet")
        effective = candidate    # partly recovered: use the milder rule, not the stale harsher one
    elif effective is SystemState.HEALTHY and candidate is not SystemState.HEALTHY:
        return hold("R1c", f"state is HEALTHY but this sample already shows {candidate.value}; "
                           "waiting for it to be confirmed, and not adding admission meanwhile")

    if effective is SystemState.OVERLOADED:
        if value <= param.minimum:
            return hold("R2", f"overloaded but already at the minimum ({param.minimum}); cannot restrict further")
        return ProposedAction(ActionKind.DECREASE, param.name, value - param.max_move, "R2",
                              f"overloaded: {_raised(signals)}; reducing by {param.max_move}")
    if effective is SystemState.UNDER_PRESSURE:
        if any(signals[n].level and signals[n].level >= 1 for n in QUEUE_RELATED if n in signals):
            if value <= param.minimum:
                return hold("R3", f"queue pressure but already at the minimum ({param.minimum})")
            return ProposedAction(ActionKind.DECREASE, param.name, value - param.step, "R3",
                                  f"queue pressure rising: {_raised(signals)}; reducing by {param.step}")
        return hold("R4", f"pressure is not queue-driven ({_raised(signals)}); not adding admission")
    # HEALTHY, and this sample agrees
    if value < param.maximum:
        return ProposedAction(ActionKind.INCREASE, param.name, value + param.step, "R5",
                              f"healthy for sustained samples; restoring admission by {param.step}")
    return hold("R6", "healthy and already at the maximum; no change needed")


def _raised(signals):
    raised = [f"{s.name}={s.value:.3g}" for s in signals.values() if s.level]
    return ", ".join(raised) if raised else "no signal above threshold"
