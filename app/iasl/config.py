"""IASL settings: parsed from environment variables, validated, with safe defaults.

Follows the project convention of OSLayerConfig (frozen dataclass, ValueError naming the setting,
a bad value stops start-up). It is a SEPARATE class on purpose: OSLayerConfig is compared for exact
equality by an existing test and must not gain fields.

Every numeric default here is PROVISIONAL and UNCALIBRATED. None is an experimentally validated value.
"""
import math
import os
from dataclasses import dataclass, fields

DEFAULT_ENABLED = False
FALLBACK_MODES = ("baseline", "conservative")

# field name -> environment variable
_ENV = {f: "IASL_" + f.upper() for f in (
    "enabled", "sampling_interval_s", "stale_metric_seconds", "watchdog_seconds",
    "admission_min", "admission_max", "admission_initial",
    "adjustment_step", "overload_step_multiplier", "cooldown_seconds", "increase_cooldown_seconds",
    "reversal_lockout_seconds", "max_reversals", "oscillation_window_seconds", "oscillation_hold_seconds",
    "queue_util_pressure", "queue_util_overload", "queue_wait_p95_pressure_s", "queue_wait_p95_overload_s",
    "rejection_rate_pressure", "rejection_rate_overload", "error_rate_pressure", "error_rate_overload",
    "worker_util_pressure", "worker_util_overload", "sem_wait_ratio_pressure", "sem_wait_ratio_overload",
    "exit_ratio", "smoothing_samples", "escalate_samples", "deescalate_samples", "min_primary_signals",
    "latency_window_seconds", "latency_ring_size", "min_latency_samples",
    "fallback_mode", "fallback_after_failures", "fallback_after_degraded", "fallback_recovery_samples",
    "decision_log_size",
)}

ENV_NAMES = dict(_ENV)   # public copy: field name -> environment variable (listed by GET /iasl/config)

# (low, high) inclusive. None = unbounded on that side. Applies to numeric fields only.
_RANGES = {
    "sampling_interval_s": (0.1, 10.0),
    "adjustment_step": (0.01, 0.5),
    "overload_step_multiplier": (1, 4),
    "exit_ratio": (0.1, 0.95),
    "smoothing_samples": (1, 20),
    "escalate_samples": (1, None), "deescalate_samples": (1, None),
    "min_primary_signals": (1, 4),
    "latency_window_seconds": (0.5, 3600.0), "latency_ring_size": (16, 1_000_000), "min_latency_samples": (1, None),
    "fallback_after_failures": (1, None), "fallback_after_degraded": (1, None), "fallback_recovery_samples": (1, None),
    "decision_log_size": (10, 10_000),
    "max_reversals": (1, None), "oscillation_window_seconds": (1.0, None), "oscillation_hold_seconds": (1.0, None),
    "cooldown_seconds": (0.0, None), "increase_cooldown_seconds": (0.0, None), "reversal_lockout_seconds": (0.0, None),
    "stale_metric_seconds": (0.0, None), "watchdog_seconds": (0.0, None),
    "admission_min": (1, None), "admission_max": (1, None), "admission_initial": (1, None),
}

# (pressure field, overload field, upper limit or None): 0 < pressure < overload <= limit
_THRESHOLD_PAIRS = (
    ("queue_util_pressure", "queue_util_overload", 1.0),
    ("queue_wait_p95_pressure_s", "queue_wait_p95_overload_s", None),
    ("rejection_rate_pressure", "rejection_rate_overload", 1.0),
    ("error_rate_pressure", "error_rate_overload", 1.0),
    ("worker_util_pressure", "worker_util_overload", 1.0),
    ("sem_wait_ratio_pressure", "sem_wait_ratio_overload", None),
)

_INTEGER_FIELDS = {
    "overload_step_multiplier", "max_reversals", "smoothing_samples", "escalate_samples", "deescalate_samples",
    "min_primary_signals", "latency_ring_size", "min_latency_samples", "fallback_after_failures",
    "fallback_after_degraded", "fallback_recovery_samples", "decision_log_size",
    "admission_min", "admission_max", "admission_initial",
}
_OPTIONAL_INTEGER_FIELDS = {"admission_min", "admission_max", "admission_initial"}   # None = "auto"


@dataclass(frozen=True)
class AdmissionBounds:
    minimum: int
    maximum: int
    initial: int


@dataclass(frozen=True)
class IASLConfig:
    enabled: bool = DEFAULT_ENABLED
    sampling_interval_s: float = 0.5
    stale_metric_seconds: float = 2.0
    watchdog_seconds: float = 5.0
    # None = automatic: min = worker count, max = queue capacity, initial = max (identical to no IASL)
    admission_min: object = None
    admission_max: object = None
    admission_initial: object = None
    adjustment_step: float = 0.10                # fraction of (max - min)
    overload_step_multiplier: int = 2
    cooldown_seconds: float = 2.0                # after a decrease
    increase_cooldown_seconds: float = 4.0       # after an increase (slower to relax)
    reversal_lockout_seconds: float = 8.0
    max_reversals: int = 3
    oscillation_window_seconds: float = 60.0
    oscillation_hold_seconds: float = 30.0
    queue_util_pressure: float = 0.50
    queue_util_overload: float = 0.85
    queue_wait_p95_pressure_s: float = 0.10
    queue_wait_p95_overload_s: float = 0.50
    rejection_rate_pressure: float = 0.01
    rejection_rate_overload: float = 0.05
    error_rate_pressure: float = 0.02
    error_rate_overload: float = 0.10
    worker_util_pressure: float = 0.90
    worker_util_overload: float = 0.99
    sem_wait_ratio_pressure: float = 1.0
    sem_wait_ratio_overload: float = 3.0
    exit_ratio: float = 0.7
    smoothing_samples: int = 3
    escalate_samples: int = 2
    deescalate_samples: int = 5
    min_primary_signals: int = 2
    latency_window_seconds: float = 5.0
    latency_ring_size: int = 2048
    min_latency_samples: int = 20
    fallback_mode: str = "baseline"
    fallback_after_failures: int = 3
    fallback_after_degraded: int = 10
    fallback_recovery_samples: int = 10
    decision_log_size: int = 500

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError(f"{_ENV['enabled']} must be true or false, got {self.enabled!r}")
        if self.fallback_mode not in FALLBACK_MODES:
            raise ValueError(f"{_ENV['fallback_mode']} must be one of {FALLBACK_MODES}, got {self.fallback_mode!r}")
        for name, (low, high) in _RANGES.items():
            value = getattr(self, name)
            if value is None and name in _OPTIONAL_INTEGER_FIELDS:
                continue
            _check_number(name, value, name in _INTEGER_FIELDS)
            if (low is not None and value < low) or (high is not None and value > high):
                raise ValueError(f"{_ENV[name]} must be between {low} and {high}, got {value!r}")
        for pressure, overload, limit in _THRESHOLD_PAIRS:
            p, o = getattr(self, pressure), getattr(self, overload)
            _check_number(pressure, p, False)
            _check_number(overload, o, False)
            if not 0 < p < o or (limit is not None and o > limit):
                bound = f" and at most {limit}" if limit is not None else ""
                raise ValueError(f"{_ENV[pressure]} and {_ENV[overload]} must satisfy 0 < pressure < overload{bound}, got {p!r} and {o!r}")
        interval = self.sampling_interval_s
        if self.stale_metric_seconds < 2 * interval:
            raise ValueError(f"{_ENV['stale_metric_seconds']} must be at least 2 x {_ENV['sampling_interval_s']} ({2 * interval})")
        if self.watchdog_seconds < 3 * interval:
            raise ValueError(f"{_ENV['watchdog_seconds']} must be at least 3 x {_ENV['sampling_interval_s']} ({3 * interval})")
        if self.cooldown_seconds < interval:
            raise ValueError(f"{_ENV['cooldown_seconds']} must be at least {_ENV['sampling_interval_s']}")
        if self.increase_cooldown_seconds < self.cooldown_seconds:
            raise ValueError(f"{_ENV['increase_cooldown_seconds']} must be at least {_ENV['cooldown_seconds']}")
        if self.reversal_lockout_seconds < self.cooldown_seconds:
            raise ValueError(f"{_ENV['reversal_lockout_seconds']} must be at least {_ENV['cooldown_seconds']}")
        if self.admission_min is not None and self.admission_max is not None and self.admission_min > self.admission_max:
            raise ValueError(f"{_ENV['admission_min']} ({self.admission_min}) must not exceed {_ENV['admission_max']} ({self.admission_max})")
        if self.admission_initial is not None:
            if self.admission_min is not None and self.admission_initial < self.admission_min:
                raise ValueError(f"{_ENV['admission_initial']} must not be below {_ENV['admission_min']}")
            if self.admission_max is not None and self.admission_initial > self.admission_max:
                raise ValueError(f"{_ENV['admission_initial']} must not exceed {_ENV['admission_max']}")

    # ------------------------------------------------------------------ capacity-dependent values

    def resolve_bounds(self, queue_capacity, worker_count, strict=True):
        """Turn the automatic settings into concrete numbers once the layer's size is known.

        strict=True (start-up): an impossible combination raises ValueError naming the variables.
        strict=False (the layer was replaced while running): clamp into range instead, because the
        server is already up and must not refuse.
        """
        if queue_capacity < 1 or worker_count < 1:
            raise ValueError("queue_capacity and worker_count must be at least 1")
        maximum = queue_capacity if self.admission_max is None else min(self.admission_max, queue_capacity)
        minimum = worker_count if self.admission_min is None else self.admission_min
        if minimum > maximum:
            if strict and self.admission_min is not None:
                raise ValueError(f"{_ENV['admission_min']} ({minimum}) exceeds the usable maximum ({maximum}); "
                                 f"the queue capacity is {queue_capacity}")
            minimum = maximum   # automatic minimum (worker count) larger than the queue, or a lenient clamp
        initial = maximum if self.admission_initial is None else self.admission_initial
        if not minimum <= initial <= maximum:
            if strict and self.admission_initial is not None:
                raise ValueError(f"{_ENV['admission_initial']} ({initial}) must be between {minimum} and {maximum}")
            initial = max(minimum, min(initial, maximum))
        return AdmissionBounds(minimum=minimum, maximum=maximum, initial=initial)

    def fallback_limit(self, bounds, queue_capacity):
        """The limit used in fallback mode. `baseline` equals running without IASL; always inside the bounds."""
        if self.fallback_mode == "baseline":
            return queue_capacity
        return max(bounds.minimum, queue_capacity // 2)

    # ------------------------------------------------------------------ environment

    @classmethod
    def from_environment(cls, environ=None):
        """Read the IASL_* variables (each optional). A bad value raises ValueError naming the variable."""
        environ = os.environ if environ is None else environ
        values = {}
        defaults = {f.name: f.default for f in fields(cls)}
        for name, variable in _ENV.items():
            text = environ.get(variable)
            if text is None or text.strip() == "":
                continue
            values[name] = _parse(name, variable, text.strip(), defaults[name])
        return cls(**values)

    def as_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _check_number(name, value, integer):
    ok = isinstance(value, int) and not isinstance(value, bool) if integer else (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))
    if not ok:
        kind = "a whole number" if integer else "a finite number"
        raise ValueError(f"{_ENV[name]} must be {kind}, got {value!r}")


def _parse(name, variable, text, default):
    if name == "enabled":
        lowered = text.lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{variable} must be true or false, got {text!r}")
    if name == "fallback_mode":
        return text.lower()
    if name in _INTEGER_FIELDS:
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"{variable} must be a whole number, got {text!r}") from None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{variable} must be a number, got {text!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{variable} must be a finite number, got {text!r}")
    return value
