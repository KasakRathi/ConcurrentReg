"""Outcome telemetry: per-outcome counters and a bounded window of recent latencies.

This is the ONLY new thing IASL writes from the request path, and it is written by a worker thread
AFTER the caller has been answered, so it can never delay a response. It knows nothing about
registrations: it receives an outcome code (text) and durations (numbers).

Percentiles use the same nearest-rank rule as the workload generator (workload_generator.percentile),
so server-side and client-side numbers are comparable.
"""
import math
import threading
import time
from collections import deque

from app.iasl.types import WindowStats

CANCELLED = "CANCELLED"   # the caller gave up while the job was still queued; no outcome was produced


def nearest_rank(sorted_values, percent):
    """Nearest-rank percentile of an already sorted, non-empty list (same rule as the workload generator)."""
    rank = math.ceil(percent / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


def _valid_duration(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


class OutcomeRecorder:
    def __init__(self, ring_size=2048, clock=time.monotonic):
        if ring_size < 1:
            raise ValueError("ring_size must be at least 1")
        self._lock = threading.Lock()
        self._ring = deque(maxlen=ring_size)   # (finished_at, queue_wait_s, server_s)
        self._counts = {}                      # outcome code -> how many
        self._invalid_observations = 0         # completions whose durations were unusable (counted, not stored)
        self.ring_size = ring_size
        self._clock = clock   # the SAME clock the readers pass to window(); never mix clocks

    # ------------------------------------------------------------------ writers (worker threads)

    def on_completed(self, code, queue_wait_s, db_section_s, server_s):
        """One job produced an outcome. The completion time is stamped here, with this recorder's own clock.

        db_section_s is accepted for completeness (it includes row-lock wait, so it is not pure DB time)
        but is not stored: the controller does not use it.
        """
        usable = _valid_duration(queue_wait_s) and _valid_duration(server_s)
        finished_at = self._clock()
        with self._lock:
            self._counts[code] = self._counts.get(code, 0) + 1
            if usable:
                self._ring.append((finished_at, queue_wait_s, server_s))
            else:
                self._invalid_observations += 1

    def on_cancelled(self):
        with self._lock:
            self._counts[CANCELLED] = self._counts.get(CANCELLED, 0) + 1

    # ------------------------------------------------------------------ readers (controller thread, API)

    def counters(self):
        """A copy of the outcome counts, plus the total of produced outcomes (cancelled jobs excluded)."""
        with self._lock:
            counts = dict(self._counts)
            invalid = self._invalid_observations
        produced = sum(n for code, n in counts.items() if code != CANCELLED)
        return {"by_outcome": counts, "completed": produced, "cancelled": counts.get(CANCELLED, 0),
                "invalid_observations": invalid}

    def window(self, now, window_s, min_samples):
        """Percentiles over completions in the last `window_s` seconds before `now`.

        Percentiles are None when fewer than `min_samples` completions are in the window: a value is never
        extrapolated from too little data. `covered_s` is the span actually covered, which is shorter than
        `window_s` if the ring was too small to hold the whole window.
        """
        with self._lock:
            entries = list(self._ring)              # copy under the lock, sort outside it
            full = len(self._ring) == self._ring.maxlen
        cutoff = now - window_s
        recent = [e for e in entries if e[0] >= cutoff]
        covered = window_s
        if full and entries and entries[0][0] > cutoff:
            covered = max(0.0, now - entries[0][0])   # the ring wrapped inside the window
        if len(recent) < max(1, min_samples):
            return WindowStats(covered_s=covered, samples=len(recent))
        waits = sorted(e[1] for e in recent)
        servers = sorted(e[2] for e in recent)
        return WindowStats(
            covered_s=covered, samples=len(recent),
            queue_wait_p50_s=nearest_rank(waits, 50), queue_wait_p95_s=nearest_rank(waits, 95),
            queue_wait_p99_s=nearest_rank(waits, 99),
            server_latency_p50_s=nearest_rank(servers, 50), server_latency_p95_s=nearest_rank(servers, 95),
            server_latency_p99_s=nearest_rank(servers, 99),
        )
