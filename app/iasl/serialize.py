"""Turn IASL's immutable objects into plain JSON-friendly dicts for the read-only API.

Pure functions, no FastAPI and no I/O. Every value is a number, text, bool, list, dict or None, so the
result can always be sent as JSON. Nothing is invented: a missing value stays None.
"""
from dataclasses import asdict

from app.iasl.types import UNAVAILABLE_METRICS

KINDS = {
    "gauges": "instantaneous values read at the moment of the sample",
    "interval": "rates and ratios derived from counter differences over interval_s (null on the first sample or after a restart)",
    "window": "percentiles over recent completions inside a sliding window (null below the minimum sample count)",
}


def sample_to_dict(sample, now=None):
    if sample is None:
        return None
    return {
        "wall_time": sample.wall_time,
        "age_s": None if now is None else round(sample.age(now), 3),
        "interval_s": sample.interval_s,
        "quality": sample.quality.value,
        "restart": sample.restart,
        "issues": list(sample.issues),
        "gauges": asdict(sample.gauges),
        "interval": None if sample.interval is None else asdict(sample.interval),
        "window": asdict(sample.window),
        "admission_limit": sample.admission_limit,
        "kinds": KINDS,
        "unavailable": dict(sample.unavailable or UNAVAILABLE_METRICS),
    }


def history_row(sample):
    """A compact row for charting a recent history without sending every field of every sample."""
    g, i, w = sample.gauges, sample.interval, sample.window
    return {
        "wall_time": sample.wall_time, "quality": sample.quality.value,
        "queue_utilization": g.queue_utilization, "worker_utilization": g.worker_utilization,
        "sem_utilization": g.sem_utilization, "admission_limit": sample.admission_limit,
        "arrivals_per_s": None if i is None else i.arrivals_per_s,
        "completed_per_s": None if i is None else i.completed_per_s,
        "queue_full_rejection_rate": None if i is None else i.queue_full_rejection_rate,
        "admission_rejections_per_s": None if i is None else i.admission_rejections_per_s,
        "queue_wait_p95_s": w.queue_wait_p95_s, "server_latency_p95_s": w.server_latency_p95_s,
    }


def assessment_to_dict(assessment):
    if assessment is None:
        return None
    transition = assessment.transition
    return {
        "state": assessment.state.value, "previous_state": assessment.previous_state.value,
        "quality": assessment.quality.value, "held": assessment.held,
        "this_sample_looks": None if assessment.candidate is None else assessment.candidate.value,
        "reason": assessment.reason,
        "streaks": {"worse": assessment.worse_streak, "better": assessment.better_streak},
        "signals": [{"name": s.name, "class": s.klass, "value": s.value, "level": s.level,
                     "pressure_threshold": s.pressure, "overload_threshold": s.overload} for s in assessment.signals],
        "transition": None if transition is None else {
            "from": transition.from_state.value, "to": transition.to_state.value, "at": transition.at_wall,
            "reason": transition.reason},
    }


def key_metrics(sample):
    """The handful of numbers an operator wants first, taken from the latest sample."""
    if sample is None:
        return None
    g, i, w = sample.gauges, sample.interval, sample.window
    return {
        "queue_depth": g.queue_depth, "queue_capacity": g.queue_capacity, "queue_utilization": g.queue_utilization,
        "worker_utilization": g.worker_utilization, "sem_utilization": g.sem_utilization,
        "arrivals_per_s": None if i is None else i.arrivals_per_s,
        "completed_per_s": None if i is None else i.completed_per_s,
        "queue_full_rejection_rate": None if i is None else i.queue_full_rejection_rate,
        "error_rate": None if i is None else i.error_rate,
        "queue_wait_p95_s": w.queue_wait_p95_s, "server_latency_p95_s": w.server_latency_p95_s,
    }
