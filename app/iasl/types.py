"""Plain data types shared by the IASL modules. No behaviour beyond small helpers."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MetricQuality(str, Enum):
    """How far one MetricsSample can be trusted. Staleness is judged where the sample is used."""
    OK = "OK"
    DEGRADED = "DEGRADED"   # usable, but something about it is unusual (see `issues`)
    INVALID = "INVALID"     # a field failed validation, or the snapshot could not be read
    RESTART = "RESTART"     # counters went backwards or the layer was replaced: no interval values
    STALE = "STALE"         # assigned at the point of use (never by the collector): the sample is too old


# Metrics IASL would like but cannot honestly provide. Reported as unavailable, never invented.
UNAVAILABLE_METRICS = {
    "timed_out_requests": "the server has no request timeout; client-side TIMEOUT appears only in result files",
    "timeout_rate": "the server has no request timeout",
    "db_timeouts": "no database-level timeout is configured",
    "db_lock_wait": "only readable from information_schema.innodb_trx on MySQL with the PROCESS privilege; "
                    "not read by application code (absent on SQLite)",
}


@dataclass(frozen=True)
class Gauges:
    """Instantaneous values, read at the moment of the sample. None = missing or failed validation."""
    queue_depth: Optional[int] = None
    queue_capacity: Optional[int] = None
    queue_utilization: Optional[float] = None
    workers_alive: Optional[int] = None
    workers_active: Optional[int] = None
    workers_idle: Optional[int] = None
    worker_utilization: Optional[float] = None
    sem_permits: Optional[int] = None
    sem_in_use: Optional[int] = None
    sem_available: Optional[int] = None
    sem_waiting: Optional[int] = None
    sem_utilization: Optional[float] = None
    sem_waiting_ratio: Optional[float] = None


@dataclass(frozen=True)
class IntervalRates:
    """Derived from counter differences over `interval_s` (never from lifetime totals)."""
    arrivals_per_s: Optional[float] = None
    queue_full_rejections_per_s: Optional[float] = None
    admission_rejections_per_s: Optional[float] = None
    completed_per_s: Optional[float] = None
    queue_full_rejection_rate: Optional[float] = None   # queue-full refusals / arrivals; 0.0 when no arrivals
    error_rate: Optional[float] = None                  # ERROR outcomes / completions; None without completions
    avg_queue_wait_s: Optional[float] = None            # mean wait of jobs dequeued in the interval


@dataclass(frozen=True)
class WindowStats:
    """Over the most recent completions inside a sliding window. Percentiles are None below the minimum sample count."""
    covered_s: float = 0.0
    samples: int = 0
    queue_wait_p50_s: Optional[float] = None
    queue_wait_p95_s: Optional[float] = None
    queue_wait_p99_s: Optional[float] = None
    server_latency_p50_s: Optional[float] = None
    server_latency_p95_s: Optional[float] = None
    server_latency_p99_s: Optional[float] = None


@dataclass(frozen=True, eq=False)
class MetricsSample:
    taken_at: float                     # monotonic clock, for ages and intervals
    wall_time: str                      # ISO text, for people
    interval_s: Optional[float]         # seconds since the previous sample; None on the first or after a restart
    quality: MetricQuality
    restart: bool
    issues: tuple = ()
    gauges: Gauges = field(default_factory=Gauges)
    interval: Optional[IntervalRates] = None
    window: WindowStats = field(default_factory=WindowStats)
    admission_limit: Optional[int] = None
    unavailable: dict = field(default_factory=lambda: dict(UNAVAILABLE_METRICS))

    def age(self, now):
        return now - self.taken_at

    def is_stale(self, now, stale_after_s):
        return self.age(now) > stale_after_s


class SystemState(str, Enum):
    HEALTHY = "HEALTHY"
    UNDER_PRESSURE = "UNDER_PRESSURE"
    OVERLOADED = "OVERLOADED"


STATE_RANK = {SystemState.HEALTHY: 0, SystemState.UNDER_PRESSURE: 1, SystemState.OVERLOADED: 2}
RANK_STATE = {rank: state for state, rank in STATE_RANK.items()}


@dataclass(frozen=True)
class Signal:
    """One input to the analyzer: its value, which class it belongs to, and the level it reached."""
    name: str
    klass: str                       # "primary" (backlog, delay, refusals, errors) or "corroborating" (utilisation)
    value: Optional[float]           # None = not available this time (excluded, never treated as zero)
    level: Optional[int]             # 0 ok, 1 pressure, 2 overload; None when value is None
    pressure: float                  # enter thresholds, shown so a reader can see why
    overload: float


@dataclass(frozen=True)
class StateTransition:
    from_state: SystemState
    to_state: SystemState
    at_wall: str
    reason: str
    signals: tuple = ()


@dataclass(frozen=True, eq=False)
class Assessment:
    """What the analyzer concluded from one sample, and why."""
    state: SystemState                         # the state in force after this sample
    previous_state: SystemState
    quality: MetricQuality                     # OK, or why the state was only held
    held: bool                                 # True: no evaluation was made, the state was kept
    candidate: Optional[SystemState]           # what this one sample alone looked like (None when held)
    signals: tuple = ()
    transition: Optional[StateTransition] = None
    reason: str = ""
    worse_streak: int = 0
    better_streak: int = 0


# ----------------------------------------------------------------------------- control (Stage 4)

class ActionKind(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    HOLD = "HOLD"
    FALLBACK_ENTER = "FALLBACK_ENTER"
    FALLBACK_EXIT = "FALLBACK_EXIT"
    RESET = "RESET"


class GuardrailResult(str, Enum):
    ALLOW = "ALLOW"
    CLAMP = "CLAMP"     # allowed, but the value was reduced to fit a bound or the step limit
    BLOCK = "BLOCK"     # refused; nothing changes


@dataclass(frozen=True)
class ControlParameter:
    """The one parameter IASL moves, with every limit that applies to it."""
    name: str
    minimum: int
    maximum: int
    initial: int
    step: int                      # one normal adjustment, in units of the parameter (>= 1)
    cooldown_s: float              # a DECREASE may follow the previous change after this long
    increase_cooldown_s: float     # an INCREASE may follow the previous change after this long (slower to relax)
    reversal_lockout_s: float      # an INCREASE may not follow a DECREASE sooner than this
    overload_multiplier: int       # the largest single move is step x this
    max_reversals: int
    oscillation_window_s: float
    oscillation_hold_s: float

    @classmethod
    def from_config(cls, config, bounds, name="admission_depth_limit"):
        step = max(1, round(config.adjustment_step * (bounds.maximum - bounds.minimum)))
        return cls(
            name=name, minimum=bounds.minimum, maximum=bounds.maximum, initial=bounds.initial, step=step,
            cooldown_s=config.cooldown_seconds, increase_cooldown_s=config.increase_cooldown_seconds,
            reversal_lockout_s=config.reversal_lockout_seconds, overload_multiplier=config.overload_step_multiplier,
            max_reversals=config.max_reversals, oscillation_window_s=config.oscillation_window_seconds,
            oscillation_hold_s=config.oscillation_hold_seconds,
        )

    @property
    def max_move(self):
        return self.step * self.overload_multiplier


@dataclass(frozen=True)
class ParameterState:
    """What the guardrails need to know about the parameter's recent history (immutable snapshot)."""
    value: int
    last_change_at: Optional[float] = None
    last_change_kind: Optional[ActionKind] = None
    hold_until: float = 0.0
    reversal_times: tuple = ()


@dataclass(frozen=True)
class ProposedAction:
    """What the decision engine wants. Nothing happens until the guardrails allow it."""
    kind: ActionKind
    parameter: str
    target: Optional[int]          # the value wanted, BEFORE bounds are applied (None for HOLD)
    rule_id: str
    reason: str


@dataclass(frozen=True)
class Verdict:
    result: GuardrailResult
    final_value: int
    blocked_by: Optional[str] = None
    note: str = ""


@dataclass(frozen=True, eq=False)
class Decision:
    """One entry of the decision log. Every field the brief asks for is here."""
    id: int
    at_wall: str
    at_monotonic: float
    previous_state: SystemState
    current_state: SystemState
    metrics_used: dict
    action: ActionKind
    parameter: str
    previous_value: int
    new_value: int
    rule: str
    reason: str
    guardrail: Optional[GuardrailResult] = None
    blocked_by: Optional[str] = None
    suppressed_since_last: int = 0   # identical idle/blocked ticks that were counted instead of logged

    def as_dict(self):
        return {
            "id": self.id, "event": "iasl_decision", "at_wall": self.at_wall, "at_monotonic": self.at_monotonic,
            "previous_state": self.previous_state.value, "current_state": self.current_state.value,
            "metrics_used": self.metrics_used, "action": self.action.value, "parameter": self.parameter,
            "previous_value": self.previous_value, "new_value": self.new_value, "rule": self.rule,
            "reason": self.reason, "guardrail": self.guardrail.value if self.guardrail else None,
            "blocked_by": self.blocked_by, "suppressed_since_last": self.suppressed_since_last,
        }
