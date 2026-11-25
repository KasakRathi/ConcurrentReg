"""IASL runtime: builds the pieces, connects them to the OS layer, and runs the control loop on one thread.

    attach(layer)  -> installs the admission controller and the outcome recorder on the layer
    start()/stop() -> the "iasl-controller" daemon thread
    tick()         -> ONE full pass: sample -> analyze -> decide -> check safety -> apply -> record
                      (public so tests drive it deterministically with an injected clock, no sleeping)
    snapshot()     -> an immutable copy of the latest state, for the read-only API

The loop never exits on an error: a failed tick is counted and enough consecutive failures put the
system in fallback. Everything it can change is the one admission limit; it cannot reach registrations
or the database (it imports neither).
"""
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.iasl.admission import AdmissionController
from app.iasl.analyzer import StateAnalyzer
from app.iasl.controller import AdaptiveController
from app.iasl.metrics import MetricsCollector
from app.iasl.telemetry import OutcomeRecorder
from app.iasl.types import MetricsSample, Assessment

logger = logging.getLogger("iasl")

HISTORY_SAMPLES = 120   # recent samples kept for the API (about a minute at the default interval)


@dataclass(frozen=True, eq=False)
class IASLSnapshot:
    """Everything the API shows, as one immutable object (replaced as a whole, so readers never lock)."""
    enabled: bool
    attached: bool
    running: bool
    updated_wall: Optional[str]
    ticks: int
    failed_ticks: int
    sample: Optional[MetricsSample]
    assessment: Optional[Assessment]
    controller: Optional[dict]
    admission: Optional[dict]


class IASLRuntime:
    def __init__(self, config, clock=time.monotonic, wall_clock=datetime.now):
        self.config = config
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.RLock()        # serialises tick() and attach(): the latter can run on a request thread
        self._layer = None
        self._recorder = None
        self.admission = None
        self.controller = None
        self.analyzer = StateAnalyzer(config)
        self.collector = MetricsCollector(config, lambda: self._layer, lambda: self._recorder, clock=clock, wall_clock=wall_clock)
        self._history = deque(maxlen=HISTORY_SAMPLES)
        self._history_view = ()               # immutable copy published each tick, so API readers never take the lock
        self._ticks = self._failed_ticks = 0
        self._thread = None
        self._stop = threading.Event()
        self._published = self._build_snapshot(None, None)

    # ------------------------------------------------------------------ wiring

    def attach(self, layer, strict=True):
        """Install IASL on `layer` (call before layer.start() at start-up, or on a replacement layer at run time).

        strict=True: an impossible IASL_ADMISSION_* combination raises ValueError (start-up refuses).
        strict=False: clamp instead, because the server is already running.
        """
        capacity, workers = layer.config.queue_capacity, layer.config.worker_count
        bounds = self.config.resolve_bounds(capacity, workers, strict=strict)
        fallback = self.config.fallback_limit(bounds, capacity)
        with self._lock:
            recorder = OutcomeRecorder(self.config.latency_ring_size, clock=self._clock)
            admission = AdmissionController(capacity, bounds.initial, fallback, self.config.watchdog_seconds, clock=self._clock)
            layer.admission, layer.observer = admission, recorder
            self._layer, self._recorder, self.admission = layer, recorder, admission
            reason = f"attached to a layer with queue capacity {capacity} and {workers} workers"
            if self.controller is None:
                self.controller = AdaptiveController(self.config, bounds, admission, fallback, self._clock, self._wall_clock)
            else:
                self.controller.reinitialize(bounds, fallback, reason, applier=admission)
            self.collector.reset()
            self.analyzer.reset()
            self._history.clear()
            self._history_view = ()
            logger.info(json.dumps({"event": "iasl_attached", "queue_capacity": capacity, "worker_count": workers,
                                    "admission_min": bounds.minimum, "admission_max": bounds.maximum,
                                    "admission_initial": bounds.initial, "fallback_limit": fallback,
                                    "fallback_mode": self.config.fallback_mode, "strict": strict}))
            self._published = self._build_snapshot(None, None)

    def start(self):
        if self._layer is None:
            raise RuntimeError("attach(layer) before start()")
        if self._thread is not None:
            raise RuntimeError("the IASL loop is already started")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="iasl-controller", daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds=5.0):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout_seconds)
            if thread.is_alive():
                logger.error(json.dumps({"event": "iasl_stop_timeout", "note": "the daemon thread will end with the process"}))

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ the loop

    def _loop(self):
        interval = self.config.sampling_interval_s
        deadline = self._clock() + interval
        while not self._stop.wait(max(0.0, deadline - self._clock())):
            try:
                self.tick()
            except Exception as error:   # tick() already contains its failures; this is the last line of defence
                logger.error(json.dumps({"event": "iasl_loop_error", "error": f"{type(error).__name__}: {error}"}))
            deadline += interval
            if deadline < self._clock():          # fell behind: do not fire a burst of catch-up ticks
                deadline = self._clock() + interval

    def tick(self):
        """One pass of the feedback loop. Never raises: a failure is counted and may trigger fallback."""
        with self._lock:
            if self._layer is None:
                return
            now = self._clock()
            self._ticks += 1
            try:
                sample = self.collector.sample()
                assessment = self.analyzer.assess(sample, now)
                self.controller.step(sample, assessment, now)
                self.controller.record_success()
                self._history.append(sample)
                self._history_view = tuple(self._history)
                self._published = self._build_snapshot(sample, assessment)
            except Exception as error:
                self._failed_ticks += 1
                self.controller.record_failure(error, now)
                self._published = self._build_snapshot(self._published.sample, self._published.assessment)

    # ------------------------------------------------------------------ read side

    def now(self):
        """The runtime's own clock reading (monotonic), the same clock sample ages are measured on."""
        return self._clock()

    def snapshot(self):
        return self._published

    def history(self):
        """Recent samples, oldest first. Lock-free: reads the tuple published by the last tick."""
        return list(self._history_view)

    def decisions(self, limit=None):
        return [] if self.controller is None else self.controller.decisions(limit)

    def describe(self):
        """A compact, JSON-friendly summary recorded inside experiment result files."""
        snap = self._published
        return {
            "enabled": True, "config": self.config.as_dict(),
            "state": snap.assessment.state.value if snap.assessment else None,
            "controller": snap.controller, "admission": snap.admission,
            "ticks": snap.ticks, "failed_ticks": snap.failed_ticks,
            "decisions_logged": len(self.decisions()),
        }

    def _build_snapshot(self, sample, assessment):
        return IASLSnapshot(
            enabled=True, attached=self._layer is not None, running=self.running,
            updated_wall=self._wall_clock().isoformat(timespec="milliseconds"),
            ticks=self._ticks, failed_ticks=self._failed_ticks, sample=sample, assessment=assessment,
            controller=None if self.controller is None else self.controller.status(self._clock()),
            admission=None if self.admission is None else self.admission.stats(),
        )
