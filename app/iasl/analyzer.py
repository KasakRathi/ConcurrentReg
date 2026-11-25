"""The system-state analyzer: turns a MetricsSample into HEALTHY, UNDER_PRESSURE or OVERLOADED.

It reads one sample, keeps a little history, and answers with an Assessment that says WHY. It never
acts on the system. All thresholds come from IASLConfig and are PROVISIONAL (uncalibrated).

Design points (docs/iasl/IASL_DESIGN.md section 5):
  * Several signals, never one. Backlog, delay, refusals and errors are "primary"; worker and
    semaphore utilisation only corroborate (all workers busy with an empty queue is a healthy,
    fully used system).
  * Admission-control refusals are deliberately NOT an input. If they were, lowering the admission
    limit would cause refusals, which would look like overload, which would lower the limit again.
  * Queue utilisation is measured against the queue's physical capacity, not against the admission limit.
  * Per-signal hysteresis (a level falls only below enter x exit_ratio), consecutive-sample validation
    between states (fast to worsen, slow to recover), smoothing of the jittery gauges.
  * A sample that cannot be trusted (invalid, stale, degraded, too few primary signals) HOLDS the
    state; it neither raises nor clears anything.
"""
from collections import deque

from app.iasl.types import (
    Assessment, MetricQuality, RANK_STATE, STATE_RANK, Signal, StateTransition, SystemState,
)

PRIMARY = "primary"
CORROBORATING = "corroborating"


class StateAnalyzer:
    def __init__(self, config):
        self.config = config
        self._smoothing = deque(maxlen=config.smoothing_samples)   # (queue_util, worker_util, sem_waiting_ratio)
        self.reset()

    def reset(self):
        """Forget history, levels and streaks; the state becomes HEALTHY (a fresh start)."""
        self._smoothing.clear()
        self._state = SystemState.HEALTHY
        self._levels = {}
        self._worse_streak = 0
        self._worse_floor = None      # the lowest "worse" candidate seen in the current streak
        self._better_streak = 0

    @property
    def state(self):
        return self._state

    # ------------------------------------------------------------------ public

    def assess(self, sample, now=None):
        """Evaluate one sample. `now` (monotonic) lets staleness be judged; omit it to skip that check."""
        previous = self._state
        if sample.quality is MetricQuality.RESTART:
            return self._after_restart(sample, previous)
        if now is not None and sample.is_stale(now, self.config.stale_metric_seconds):
            return self._held(previous, MetricQuality.STALE,
                              f"sample is {sample.age(now):.2f}s old (limit {self.config.stale_metric_seconds}s); state held")
        if sample.quality is MetricQuality.INVALID:
            return self._held(previous, MetricQuality.INVALID, "invalid metrics (" + ", ".join(sample.issues) + "); state held")
        if sample.quality is MetricQuality.DEGRADED:
            return self._held(previous, MetricQuality.DEGRADED, "degraded metrics (" + ", ".join(sample.issues) + "); state held")

        # Smoothed values are computed from a tentative history; it is only kept if the sample turns out usable.
        tentative = list(self._smoothing) + [(sample.gauges.queue_utilization, sample.gauges.worker_utilization,
                                              sample.gauges.sem_waiting_ratio)]
        tentative = tentative[-self._smoothing.maxlen:]
        values = self._values(sample, tentative)
        primary_available = sum(1 for name, (klass, v, p, o) in values.items() if klass == PRIMARY and v is not None)
        if primary_available < self.config.min_primary_signals:
            return self._held(previous, MetricQuality.DEGRADED,
                              f"only {primary_available} primary signal(s) available (need {self.config.min_primary_signals}); "
                              "state held (normal for the very first sample)")

        self._smoothing.append(tentative[-1])
        signals = self._levelled(values)
        candidate = self._candidate(signals)
        transition = self._advance(candidate, signals, sample.wall_time)
        reason = transition.reason if transition else self._steady_reason(candidate, signals)
        return Assessment(
            state=self._state, previous_state=previous, quality=MetricQuality.OK, held=False, candidate=candidate,
            signals=signals, transition=transition, reason=reason,
            worse_streak=self._worse_streak, better_streak=self._better_streak,
        )

    # ------------------------------------------------------------------ signals

    def _values(self, sample, history):
        """name -> (class, value, pressure threshold, overload threshold). Missing values are None."""
        c = self.config
        interval = sample.interval

        def mean(index):
            usable = [h[index] for h in history if h[index] is not None]
            return sum(usable) / len(usable) if usable else None

        return {
            "queue_utilization": (PRIMARY, mean(0), c.queue_util_pressure, c.queue_util_overload),
            "queue_wait_p95_s": (PRIMARY, sample.window.queue_wait_p95_s, c.queue_wait_p95_pressure_s, c.queue_wait_p95_overload_s),
            "queue_full_rejection_rate": (PRIMARY, None if interval is None else interval.queue_full_rejection_rate,
                                          c.rejection_rate_pressure, c.rejection_rate_overload),
            "error_rate": (PRIMARY, None if interval is None else interval.error_rate, c.error_rate_pressure, c.error_rate_overload),
            "worker_utilization": (CORROBORATING, mean(1), c.worker_util_pressure, c.worker_util_overload),
            "semaphore_waiting_ratio": (CORROBORATING, mean(2), c.sem_wait_ratio_pressure, c.sem_wait_ratio_overload),
        }

    def _levelled(self, values):
        ratio = self.config.exit_ratio
        signals = []
        for name, (klass, value, pressure, overload) in values.items():
            if value is None:
                self._levels[name] = 0      # no evidence is not carried forward as old pressure
                signals.append(Signal(name, klass, None, None, pressure, overload))
                continue
            previous = self._levels.get(name, 0)
            if value >= overload or (previous >= 2 and value >= overload * ratio):
                level = 2
            elif value >= pressure or (previous >= 1 and value >= pressure * ratio):
                level = 1
            else:
                level = 0
            self._levels[name] = level
            signals.append(Signal(name, klass, value, level, pressure, overload))
        return tuple(signals)

    @staticmethod
    def _candidate(signals):
        known = [s for s in signals if s.level is not None]
        over_primary = [s for s in known if s.klass == PRIMARY and s.level == 2]
        raised = [s for s in known if s.level >= 1]
        # Overloaded needs a primary signal at the top level AND corroboration from some other raised signal.
        if over_primary and len(raised) >= 2:
            return SystemState.OVERLOADED
        if any(s.klass == PRIMARY and s.level >= 1 for s in known):
            return SystemState.UNDER_PRESSURE
        if sum(1 for s in known if s.klass == CORROBORATING and s.level >= 1) >= 2:
            return SystemState.UNDER_PRESSURE
        return SystemState.HEALTHY

    # ------------------------------------------------------------------ state machine

    def _advance(self, candidate, signals, wall_time):
        current_rank, candidate_rank = STATE_RANK[self._state], STATE_RANK[candidate]
        if candidate_rank > current_rank:
            self._better_streak = 0
            self._worse_streak += 1
            self._worse_floor = candidate_rank if self._worse_floor is None else min(self._worse_floor, candidate_rank)
            if self._worse_streak >= self.config.escalate_samples:
                # Skip a level only if every sample in the streak was at the higher state.
                return self._move(RANK_STATE[self._worse_floor], signals, wall_time,
                                  f"{self._worse_streak} consecutive samples worse than {self._state.value}")
        elif candidate_rank < current_rank:
            self._worse_streak, self._worse_floor = 0, None
            self._better_streak += 1
            if self._better_streak >= self.config.deescalate_samples:
                return self._move(RANK_STATE[current_rank - 1], signals, wall_time,
                                  f"{self._better_streak} consecutive samples better than {self._state.value}")
        else:
            self._worse_streak, self._worse_floor, self._better_streak = 0, None, 0
        return None

    def _move(self, new_state, signals, wall_time, why):
        transition = StateTransition(
            from_state=self._state, to_state=new_state, at_wall=wall_time,
            reason=f"{self._state.value} -> {new_state.value}: {why}; {_describe(signals)}", signals=signals,
        )
        self._state = new_state
        self._worse_streak, self._worse_floor, self._better_streak = 0, None, 0
        return transition

    # ------------------------------------------------------------------ results

    def _held(self, previous, quality, reason):
        return Assessment(state=previous, previous_state=previous, quality=quality, held=True, candidate=None,
                          reason=reason, worse_streak=self._worse_streak, better_streak=self._better_streak)

    def _after_restart(self, sample, previous):
        had_changed = previous is not SystemState.HEALTHY
        self.reset()
        transition = None
        if had_changed:
            transition = StateTransition(previous, SystemState.HEALTHY, sample.wall_time,
                                         f"{previous.value} -> HEALTHY: counters restarted or the layer was replaced "
                                         f"({', '.join(sample.issues)}); history cleared")
        return Assessment(state=SystemState.HEALTHY, previous_state=previous, quality=MetricQuality.RESTART, held=True,
                          candidate=None, transition=transition,
                          reason="restart detected; analyzer history cleared, state reset to HEALTHY")

    def _steady_reason(self, candidate, signals):
        return f"{self._state.value} (this sample looks {candidate.value}); {_describe(signals)}"


def _describe(signals):
    """Plain-language list of the signals that reached a threshold (or 'no signal above threshold')."""
    raised = sorted((s for s in signals if s.level), key=lambda s: -s.level)
    if not raised:
        return "no signal above its threshold"
    parts = []
    for s in raised:
        threshold = s.overload if s.level == 2 else s.pressure
        parts.append(f"{s.name}={s.value:.3g} ({'overload' if s.level == 2 else 'pressure'}, threshold {threshold:g})")
    return ", ".join(parts)
