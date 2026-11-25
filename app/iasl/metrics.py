"""The metrics collector: one MetricsSample per call, built from what the OS layer already reports.

Inputs
  * layer.snapshot()   (existing: gauges and cumulative counters). Reused, not duplicated.
  * an OutcomeRecorder (new, optional): per-outcome counts and a window of recent latencies.

It only READS. It never writes to the layer, never touches the database, and never invents a value:
anything missing or invalid becomes None and is named in `issues`. Interval values come from counter
DIFFERENCES between two samples, never from lifetime totals. A counter that goes backwards, or a
different layer object, is a RESTART: no interval values are produced for that sample.

Owned by the controller thread; a lock makes an accidental second caller safe, not fast.
"""
import math
import threading
import time
from datetime import datetime

from app.iasl.types import Gauges, IntervalRates, MetricQuality, MetricsSample, UNAVAILABLE_METRICS, WindowStats

LONG_INTERVAL_FACTOR = 5   # a gap this many times the sampling interval means the loop stalled

# Cumulative counters used for interval values: name -> (path in snapshot()).
_CUMULATIVE = {
    "accepted": ("queue", "accepted"),
    "rejected_queue_full": ("queue", "rejected_queue_full"),
    "rejected_shutting_down": ("queue", "rejected_shutting_down"),
    "queue_wait_total_s": ("queue_wait", "total_s"),
    "jobs_dequeued": ("queue_wait", "jobs_dequeued"),
    "jobs_finished": ("workers", "jobs_finished"),
}


class MetricsCollector:
    def __init__(self, config, get_layer, get_recorder=lambda: None, clock=time.monotonic, wall_clock=datetime.now):
        self.config = config
        self._get_layer = get_layer
        self._get_recorder = get_recorder
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._previous = None   # (taken_at, layer_id, {counter: value})

    def reset(self):
        """Forget the previous sample (the next one has no interval values)."""
        with self._lock:
            self._previous = None

    def sample(self):
        with self._lock:
            return self._sample_locked()

    # ------------------------------------------------------------------ internals

    def _sample_locked(self):
        now = self._clock()
        wall = self._wall_clock().isoformat(timespec="milliseconds")
        try:
            layer = self._get_layer()
            snap = layer.snapshot()
        except Exception as error:   # a broken snapshot must degrade IASL, never raise into the loop
            return MetricsSample(taken_at=now, wall_time=wall, interval_s=None, quality=MetricQuality.INVALID,
                                 restart=False, issues=(f"snapshot_failed:{type(error).__name__}",))

        issues = []        # validation problems  -> INVALID
        notes = []         # unusual but usable   -> DEGRADED
        gauges = self._gauges(snap, issues, notes)

        counters = {}
        for name, path in _CUMULATIVE.items():
            counters[name] = _number(snap, path, issues)
        # The "admission" block exists only once admission control is installed; before that, zero rejections.
        admission = snap.get("admission") if isinstance(snap, dict) else None
        admission_limit = None
        if isinstance(admission, dict):
            counters["rejected_admission"] = _number(admission, ("rejected",), issues)
            limit = admission.get("limit")
            if isinstance(limit, int) and not isinstance(limit, bool):
                admission_limit = limit
        else:
            counters["rejected_admission"] = 0

        recorder = self._get_recorder()
        outcome_totals = None
        if recorder is not None:
            try:
                outcome_totals = recorder.counters()
                counters["outcomes_completed"] = outcome_totals["completed"]
                counters["outcomes_error"] = outcome_totals["by_outcome"].get("ERROR", 0)
            except Exception as error:
                issues.append(f"recorder_failed:{type(error).__name__}")

        previous, restart = self._previous, False
        interval_s, interval = None, None
        if previous is not None:
            prev_time, prev_layer, prev_counters = previous
            decreased = [n for n, v in counters.items() if v is not None and prev_counters.get(n) is not None and v < prev_counters[n]]
            if prev_layer != id(layer):
                restart = True
                notes.append("layer_replaced")
            elif decreased:
                restart = True
                notes.append("counter_decreased:" + ",".join(sorted(decreased)))
            else:
                interval_s = now - prev_time
                if interval_s <= 0:
                    notes.append("non_positive_interval")
                    interval_s = None
                else:
                    if interval_s > LONG_INTERVAL_FACTOR * self.config.sampling_interval_s:
                        notes.append("long_interval")
                    interval = self._interval(counters, prev_counters, interval_s, recorder is not None)
        self._previous = (now, id(layer), counters)

        window = WindowStats()
        if recorder is not None:
            try:
                window = recorder.window(now, self.config.latency_window_seconds, self.config.min_latency_samples)
            except Exception as error:
                issues.append(f"recorder_failed:{type(error).__name__}")

        if issues:
            quality = MetricQuality.INVALID
        elif restart:
            quality = MetricQuality.RESTART
        elif notes:
            quality = MetricQuality.DEGRADED
        else:
            quality = MetricQuality.OK
        return MetricsSample(
            taken_at=now, wall_time=wall, interval_s=interval_s, quality=quality, restart=restart,
            issues=tuple(issues + notes), gauges=gauges, interval=interval, window=window,
            admission_limit=admission_limit, unavailable=dict(UNAVAILABLE_METRICS),
        )

    def _gauges(self, snap, issues, notes):
        depth = _number(snap, ("queue", "depth"), issues)
        capacity = _number(snap, ("queue", "capacity"), issues)
        alive = _number(snap, ("workers", "alive"), issues)
        active = _number(snap, ("workers", "active"), issues)
        permits = _number(snap, ("db_semaphore", "permits"), issues)
        in_use = _number(snap, ("db_semaphore", "in_critical_section"), issues)
        waiting = _number(snap, ("db_semaphore", "waiting"), issues)

        # Cross-checks: an impossible combination is reported and the offending value dropped, not clamped.
        if depth is not None and capacity is not None and depth > capacity:
            issues.append("queue.depth_exceeds_capacity")
            depth = None
        if active is not None and alive is not None and active > alive:
            issues.append("workers.active_exceeds_alive")
            active = None
        if in_use is not None and permits is not None and in_use > permits:
            issues.append("db_semaphore.in_use_exceeds_permits")
            in_use = None
        if alive == 0:
            notes.append("no_alive_workers")

        return Gauges(
            queue_depth=depth, queue_capacity=capacity,
            queue_utilization=_ratio(depth, capacity),
            workers_alive=alive, workers_active=active,
            workers_idle=None if alive is None or active is None else alive - active,
            worker_utilization=_ratio(active, alive),
            sem_permits=permits, sem_in_use=in_use,
            sem_available=None if permits is None or in_use is None else permits - in_use,
            sem_waiting=waiting, sem_utilization=_ratio(in_use, permits),
            sem_waiting_ratio=_ratio(waiting, permits),
        )

    @staticmethod
    def _interval(now, before, dt, have_recorder):
        def delta(name):
            a, b = now.get(name), before.get(name)
            return None if a is None or b is None else a - b

        accepted, full, shut, adm = delta("accepted"), delta("rejected_queue_full"), delta("rejected_shutting_down"), delta("rejected_admission")
        arrivals = None if None in (accepted, full, shut, adm) else accepted + full + shut + adm

        if have_recorder:
            completed, errors = delta("outcomes_completed"), delta("outcomes_error")
        else:
            completed, errors = delta("jobs_finished"), None   # layer-wide count; no per-outcome detail available
        dequeued, wait_total = delta("jobs_dequeued"), delta("queue_wait_total_s")

        return IntervalRates(
            arrivals_per_s=None if arrivals is None else arrivals / dt,
            queue_full_rejections_per_s=None if full is None else full / dt,
            admission_rejections_per_s=None if adm is None else adm / dt,
            completed_per_s=None if completed is None else completed / dt,
            # No arrivals means nothing was refused: 0.0, not "unknown".
            queue_full_rejection_rate=None if arrivals is None or full is None else (full / arrivals if arrivals > 0 else 0.0),
            error_rate=None if errors is None or not completed else errors / completed,
            avg_queue_wait_s=None if not dequeued or wait_total is None else wait_total / dequeued,
        )


def _number(snap, path, issues):
    """snap[path...] as a finite number >= 0, else None (and a named issue)."""
    value = snap
    for key in path:
        if not isinstance(value, dict) or key not in value:
            issues.append(f"{'.'.join(path)}_missing")
            return None
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        issues.append(f"{'.'.join(path)}_invalid")
        return None
    return value


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator
