"""The adaptive controller: owns the one control parameter and runs the observe-decide-check-apply-record cycle.

One call to step() is one pass of the brief's feedback loop for a single, already-assessed sample:

    3 select ONE action (decision engine)  ->  4 validate (guardrails)  ->  5 apply  ->  6 record
    (1 observe and 2 analyze happen before this call; 7 observe the result is the next tick)

The only thing it can change is the value of one ControlParameter, through an `applier` object with
set_limit(int), heartbeat(), enter_fallback() and exit_fallback() (the admission controller). It never
touches registrations or the database. Repeated idle or repeatedly-blocked ticks are COUNTED, not logged,
so a quiet system does not flood the decision log.
"""
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime

from app.iasl import engine, guardrails
from app.iasl.types import (
    ActionKind, ControlParameter, Decision, GuardrailResult, MetricQuality, ParameterState, SystemState, Verdict,
)

logger = logging.getLogger("iasl")

_UNTRUSTED = (MetricQuality.INVALID, MetricQuality.STALE, MetricQuality.DEGRADED)


class AdaptiveController:
    def __init__(self, config, bounds, applier, fallback_limit, clock=time.monotonic, wall_clock=datetime.now):
        self.config = config
        self._applier = applier
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()                       # guards the log and counters read by the API thread
        self._log = deque(maxlen=config.decision_log_size)
        self._next_id = 1
        self._suppressed_key = None
        self._suppressed_count = 0
        self.ticks = self.changes = self.blocks = 0
        self._last_state = SystemState.HEALTHY
        self._last_change = None
        self._configure(bounds, fallback_limit)

    def _configure(self, bounds, fallback_limit):
        self.param = ControlParameter.from_config(self.config, bounds)
        self._fallback_limit = max(self.param.minimum, min(self.param.maximum, fallback_limit))
        self._state = ParameterState(value=bounds.initial)
        self._in_fallback = False
        self._consecutive_failures = self._degraded_streak = self._ok_streak = 0

    # ------------------------------------------------------------------ read side

    @property
    def value(self):
        return self._state.value

    @property
    def in_fallback(self):
        return self._in_fallback

    def decisions(self, limit=None):
        with self._lock:
            items = list(self._log)
        return items if limit is None else items[-limit:]

    @property
    def last_decision(self):
        with self._lock:
            return self._log[-1] if self._log else None

    @property
    def last_control_action(self):
        with self._lock:
            return self._last_change

    def status(self, now=None):
        now = self._clock() if now is None else now
        last = self.last_decision
        action = self.last_control_action
        return {
            "parameter": {"name": self.param.name, "value": self._state.value, "minimum": self.param.minimum,
                          "maximum": self.param.maximum, "initial": self.param.initial, "step": self.param.step},
            "fallback_active": self._in_fallback, "fallback_limit": self._fallback_limit,
            "ticks": self.ticks, "changes": self.changes, "blocked_changes": self.blocks,
            "consecutive_failures": self._consecutive_failures, "untrusted_streak": self._degraded_streak,
            "oscillation_hold_remaining_s": max(0.0, round(self._state.hold_until - now, 3)),
            "suppressed_idle_ticks_pending": self._suppressed_count,
            "last_decision": last.as_dict() if last else None,
            "last_control_action": action.as_dict() if action else None,
        }

    # ------------------------------------------------------------------ the cycle

    def step(self, sample, assessment, now=None):
        """One pass of the loop. Returns the Decision recorded for this tick, or None if nothing was worth logging."""
        now = self._clock() if now is None else now
        self.ticks += 1
        self._last_state = assessment.state
        if self._in_fallback:
            decision = self._step_in_fallback(sample, assessment, now)
        else:
            untrusted = assessment.held and assessment.quality in _UNTRUSTED
            self._degraded_streak = self._degraded_streak + 1 if untrusted else 0
            if self._degraded_streak >= self.config.fallback_after_degraded:
                decision = self._enter_fallback(f"metrics unreliable for {self._degraded_streak} consecutive ticks "
                                                f"({assessment.quality.value}: {assessment.reason})", now, sample, assessment)
            else:
                proposed = engine.decide(assessment, self.param, self._state)
                decision = self._handle(proposed, sample, assessment, now)
        self._beat()
        return decision

    def record_failure(self, error, now=None):
        """The loop caught an exception in a tick. Enough consecutive failures put the system in fallback."""
        now = self._clock() if now is None else now
        self._consecutive_failures += 1
        logger.error(json.dumps({"event": "iasl_tick_failed", "error": f"{type(error).__name__}: {error}",
                                 "consecutive_failures": self._consecutive_failures}))
        if self._consecutive_failures >= self.config.fallback_after_failures and not self._in_fallback:
            return self._enter_fallback(f"{self._consecutive_failures} consecutive controller failures "
                                        f"(last: {type(error).__name__}: {error})", now)
        return None

    def record_success(self):
        self._consecutive_failures = 0

    def reinitialize(self, bounds, fallback_limit, reason="layer attached or replaced", now=None, applier=None):
        """The layer was replaced (re-attach): recompute the limits, switch to the new layer's admission controller
        and start again from the initial value."""
        now = self._clock() if now is None else now
        previous = self._state.value
        if applier is not None:
            self._applier = applier
        self._configure(bounds, fallback_limit)
        return self._record(ActionKind.RESET, previous, self._state.value, "RESET", reason, now, None, None)

    # ------------------------------------------------------------------ handling a proposal

    def _handle(self, proposed, sample, assessment, now):
        transition = assessment.transition
        if proposed.kind is ActionKind.HOLD:
            if transition is None:
                self._suppress(("HOLD", proposed.rule_id))
                return None
            return self._record(ActionKind.HOLD, self._state.value, self._state.value, proposed.rule_id,
                                f"state changed: {transition.reason}. {proposed.reason}", now, sample, assessment)

        verdict = guardrails.review(proposed, self.param, self._state, now)
        if verdict.result is GuardrailResult.BLOCK:
            self.blocks += 1
            key = ("BLOCK", proposed.kind, verdict.blocked_by)
            if transition is None and self._is_repeat(key):
                self._suppress(key)
                return None
            return self._record(ActionKind.HOLD, self._state.value, self._state.value, proposed.rule_id,
                                f"{proposed.kind.value} blocked ({verdict.blocked_by}): {verdict.note}. Wanted: {proposed.reason}",
                                now, sample, assessment, verdict, key=key)
        try:
            self._applier.set_limit(verdict.final_value)
        except Exception as error:   # the applier's own hard bound check, or any failure: nothing changed
            self.blocks += 1
            return self._record(ActionKind.HOLD, self._state.value, self._state.value, proposed.rule_id,
                                f"{proposed.kind.value} refused by the admission controller "
                                f"({type(error).__name__}: {error}). Wanted: {proposed.reason}",
                                now, sample, assessment, _blocked("applier_rejected"))
        previous = self._state.value
        self._state, oscillating = guardrails.after_applied(self._state, self.param, proposed.kind, verdict.final_value, now)
        self.changes += 1
        reason = proposed.reason + (f" ({verdict.note})" if verdict.note else "")
        decision = self._record(proposed.kind, previous, verdict.final_value, proposed.rule_id, reason, now, sample, assessment, verdict)
        if oscillating:
            self._record(ActionKind.HOLD, verdict.final_value, verdict.final_value, "GUARD",
                         f"repeated reversals ({self.param.max_reversals} within {self.param.oscillation_window_s:g}s): "
                         f"holding all changes for {self.param.oscillation_hold_s:g}s",
                         now, sample, assessment, _blocked("oscillation_detected"))
        return decision

    # ------------------------------------------------------------------ fallback

    def _step_in_fallback(self, sample, assessment, now):
        self._ok_streak = self._ok_streak + 1 if (assessment.quality is MetricQuality.OK and not assessment.held) else 0
        if self._ok_streak >= self.config.fallback_recovery_samples:
            return self._exit_fallback(sample, assessment, now)
        self._suppress(("HOLD", "R0"))
        return None

    def _enter_fallback(self, reason, now, sample=None, assessment=None):
        if self._in_fallback:
            return None
        previous = self._state.value
        self._call_applier("enter_fallback")
        self._in_fallback = True
        self._ok_streak = 0
        self._state = ParameterState(value=self._fallback_limit, last_change_at=now)
        return self._record(ActionKind.FALLBACK_ENTER, previous, self._fallback_limit, "FALLBACK",
                            f"entering fallback mode ({self.config.fallback_mode}): {reason}", now, sample, assessment)

    def _exit_fallback(self, sample, assessment, now):
        # Hand the limit back at the fallback value first, so leaving fallback causes no jump.
        try:
            self._applier.set_limit(self._fallback_limit)
        except Exception as error:
            logger.error(json.dumps({"event": "iasl_applier_failed", "error": f"{type(error).__name__}: {error}"}))
        self._call_applier("exit_fallback")
        self._in_fallback = False
        self._degraded_streak = self._consecutive_failures = 0
        self._state = ParameterState(value=self._fallback_limit, last_change_at=now)   # cooldown applies before the first change
        return self._record(ActionKind.FALLBACK_EXIT, self._fallback_limit, self._fallback_limit, "FALLBACK",
                            f"{self.config.fallback_recovery_samples} consecutive healthy ticks; resuming control "
                            f"stepwise from {self._fallback_limit}", now, sample, assessment)

    # ------------------------------------------------------------------ bookkeeping

    def _call_applier(self, method):
        try:
            getattr(self._applier, method)()
        except Exception as error:
            logger.error(json.dumps({"event": "iasl_applier_failed", "method": method, "error": f"{type(error).__name__}: {error}"}))

    def _beat(self):
        beat = getattr(self._applier, "heartbeat", None)
        if beat is not None:
            self._call_applier("heartbeat")

    def _is_repeat(self, key):
        return key == self._suppressed_key

    def _suppress(self, key):
        if key != self._suppressed_key:
            self._suppressed_key, self._suppressed_count = key, 0
        self._suppressed_count += 1

    def _record(self, kind, previous_value, new_value, rule, reason, now, sample, assessment, verdict=None, key=None):
        state = assessment.state if assessment else self._last_state
        before = assessment.previous_state if assessment else self._last_state
        with self._lock:
            decision = Decision(
                id=self._next_id, at_wall=self._wall_clock().isoformat(timespec="milliseconds"), at_monotonic=now,
                previous_state=before, current_state=state, metrics_used=_metrics_used(sample, assessment),
                action=kind, parameter=self.param.name, previous_value=previous_value, new_value=new_value,
                rule=rule, reason=reason, guardrail=verdict.result if verdict else None,
                blocked_by=verdict.blocked_by if verdict else None, suppressed_since_last=self._suppressed_count,
            )
            self._next_id += 1
            self._log.append(decision)
            if kind is not ActionKind.HOLD:
                self._last_change = decision   # a limit change, fallback or reset: what an operator means by 'last action'
        # The next identical blocked tick is a repeat of this one, so it is counted instead of logged.
        self._suppressed_key, self._suppressed_count = key, 0
        logger.info(json.dumps(decision.as_dict(), default=str))
        return decision


def _blocked(reason):
    """A BLOCK verdict used only to label a decision-log entry (no value is carried)."""
    return Verdict(GuardrailResult.BLOCK, 0, reason)


def _metrics_used(sample, assessment):
    used = {}
    if assessment is not None:
        used["signals"] = {s.name: {"value": s.value, "level": s.level, "pressure": s.pressure, "overload": s.overload}
                           for s in assessment.signals}
        used["quality"] = assessment.quality.value
        if assessment.transition is not None:
            used["transition"] = assessment.transition.reason
    if sample is not None:
        used["admission_limit_seen"] = sample.admission_limit
        used["sample_issues"] = list(sample.issues)
        used["interval_s"] = sample.interval_s
    return used
