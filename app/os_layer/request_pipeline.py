"""The Day 3 OS concurrency layer around the Day 1 registration service.

    submit() -> bounded queue -> worker threads -> DB semaphore -> register_student() -> MySQL

Each part has one job (see its own file). This file only connects them and records
what happened to every request. The registration transaction itself is unchanged Day 1 code.
"""
import json
import logging
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import asdict, dataclass
from datetime import datetime

from app.database import SessionLocal
from app.os_layer.bounded_queue import ADDED, FULL, BoundedRequestQueue
from app.os_layer.db_semaphore import DbSemaphore
from app.os_layer.worker_pool import WorkerPool
from app.registration_service import ERROR, RegistrationResult, register_student

logger = logging.getLogger("os_layer")

# Outcomes that exist only because of the OS layer. How they appear on the HTTP API
# is NOT decided in the Master MD yet; main.py holds a provisional mapping.
QUEUE_FULL = "QUEUE_FULL"
SHUTTING_DOWN = "SHUTTING_DOWN"
QUEUE_FULL_MESSAGE = "Request queue is full"
SHUTTING_DOWN_MESSAGE = "Server is shutting down"
INTERNAL_ERROR_MESSAGE = "Registration failed because of an internal error"


@dataclass
class Job:
    request_id: str
    student_code: str
    section_id: int
    enqueued_at: float            # time.perf_counter() when the request reached the layer
    queue_depth_at_arrival: int   # how many requests were already waiting
    future: Future                # the worker stores the RegistrationResult here


class OSConcurrencyLayer:
    def __init__(self, config):
        self.config = config
        self.queue = BoundedRequestQueue(config.queue_capacity)
        self.db_semaphore = DbSemaphore(config.db_semaphore_permits)
        self.workers = WorkerPool(self.queue, config.worker_count, self._process)
        self._clock_zero = time.perf_counter()  # log times are seconds since the layer started
        self._lock = threading.Lock()
        self._jobs_dequeued = 0
        self._queue_wait_total_s = 0.0
        self._queue_wait_max_s = 0.0

    # ---------------------------------------------------------------- lifecycle

    def start(self):
        self._clock_zero = time.perf_counter()
        self.workers.start()
        logger.info(json.dumps({
            "event": "os_layer_started",
            "started_at": datetime.now().isoformat(timespec="milliseconds"),
            **asdict(self.config),
        }))

    def stop(self, timeout_seconds=30):
        """Graceful: requests already accepted are finished, new ones are refused."""
        still_running = self.workers.stop(timeout_seconds)
        logger.info(json.dumps({
            "event": "os_layer_stopped",
            "workers_still_running": still_running,
            "final_counters": self.snapshot(),
        }))

    # ------------------------------------------------------------ request entry

    def submit(self, student_code, section_id):
        """Hand one registration request to the layer. Never waits.

        Returns a Future that will hold the RegistrationResult. If the request cannot
        be queued, the Future is already finished with a QUEUE_FULL or SHUTTING_DOWN result.
        """
        future = Future()
        job = Job(
            request_id=str(uuid.uuid4()),
            student_code=student_code,
            section_id=section_id,
            enqueued_at=time.perf_counter(),
            queue_depth_at_arrival=self.queue.qsize(),
            future=future,
        )

        # FUTURE INTEGRATION POINT (Day 4/5): the Admission Controller will decide here,
        # before the request may enter the bounded queue. Day 3 admits every request;
        # only the queue's own capacity can turn one away.

        outcome = self.queue.try_put(job)
        if outcome != ADDED:
            if outcome == FULL:
                result = RegistrationResult(QUEUE_FULL, QUEUE_FULL_MESSAGE)
            else:
                result = RegistrationResult(SHUTTING_DOWN, SHUTTING_DOWN_MESSAGE)
            future.set_result(result)
            self._log_rejection(job, result.code)
        return future

    # ---------------------------------------------------------- worker-side code

    def _process(self, job):
        """Runs on a worker thread, once per job taken from the queue."""
        if not job.future.set_running_or_notify_cancel():
            return  # the caller gave up while the request was still waiting in the queue

        worker_started = time.perf_counter()
        worker_name = threading.current_thread().name
        semaphore_wait = None
        semaphore_acquired = None
        error = None
        result = RegistrationResult(ERROR, INTERNAL_ERROR_MESSAGE)  # used only if something blows up

        try:
            with self.db_semaphore.hold() as semaphore_wait:
                semaphore_acquired = time.perf_counter()
                result = self._run_registration(job)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        worker_finished = time.perf_counter()  # the permit is already given back here

        # Answer the waiting request first; bookkeeping and logging come after.
        job.future.set_result(result)

        queue_wait = worker_started - job.enqueued_at
        self._note_queue_wait(queue_wait)
        self._log_request(job, worker_name, queue_wait, worker_started, semaphore_wait,
                          semaphore_acquired, worker_finished, result, error)

    def _run_registration(self, job):
        # A new session for this job, created and closed on this worker thread.
        # Sessions and ORM objects are never shared between threads.
        db = SessionLocal()
        try:
            return register_student(db, job.student_code, job.section_id, job.request_id)
        finally:
            db.close()

    # ------------------------------------------------------------ observability

    def snapshot(self):
        """A point-in-time copy of every counter (read without stopping the workers)."""
        with self._lock:
            dequeued = self._jobs_dequeued
            wait_total = self._queue_wait_total_s
            wait_max = self._queue_wait_max_s
        semaphore = self.db_semaphore
        return {
            "config": asdict(self.config),
            "queue": {
                "capacity": self.queue.capacity,
                "depth": self.queue.qsize(),
                "max_depth": self.queue.max_depth,
                "accepted": self.queue.accepted,
                "rejected_queue_full": self.queue.rejected_full,
                "rejected_shutting_down": self.queue.rejected_shut_down,
            },
            "queue_wait": {
                "jobs_dequeued": dequeued,
                "total_s": wait_total,
                "max_s": wait_max,
                "average_s": wait_total / dequeued if dequeued else None,
            },
            "workers": {
                "configured": self.workers.worker_count,
                "alive": self.workers.alive_workers(),
                "active": self.workers.active,
                "max_active": self.workers.max_active,
                "jobs_started": self.workers.jobs_started,
                "jobs_finished": self.workers.jobs_finished,
                "unexpected_errors": self.workers.unexpected_errors,
            },
            "db_semaphore": {
                "permits": semaphore.permits,
                "in_critical_section": semaphore.in_critical_section,
                "max_in_critical_section": semaphore.max_in_critical_section,
                "waiting": semaphore.waiting,
                "max_waiting": semaphore.max_waiting,
                "acquisitions": semaphore.acquisitions,
                "wait_total_s": semaphore.wait_total_s,
                "wait_max_s": semaphore.wait_max_s,
            },
        }

    def _note_queue_wait(self, seconds):
        with self._lock:
            self._jobs_dequeued += 1
            self._queue_wait_total_s += seconds
            self._queue_wait_max_s = max(self._queue_wait_max_s, seconds)

    def _since_start(self, moment):
        return None if moment is None else round(moment - self._clock_zero, 4)

    @staticmethod
    def _milliseconds(seconds):
        return None if seconds is None else round(seconds * 1000, 2)

    def _log_request(self, job, worker_name, queue_wait, worker_started, semaphore_wait,
                     semaphore_acquired, worker_finished, result, error):
        in_section = None if semaphore_acquired is None else worker_finished - semaphore_acquired
        logger.info(json.dumps({
            "event": "os_layer_request",
            "request_id": job.request_id,          # same id as the Day 1 "registration" log line
            "student_id": job.student_code,
            "section_id": job.section_id,
            **asdict(self.config),
            "worker": worker_name,
            "queue_depth_at_arrival": job.queue_depth_at_arrival,
            "enqueued_at_s": self._since_start(job.enqueued_at),
            "queue_wait_ms": self._milliseconds(queue_wait),
            "worker_started_at_s": self._since_start(worker_started),
            "semaphore_wait_ms": self._milliseconds(semaphore_wait),
            "semaphore_acquired_at_s": self._since_start(semaphore_acquired),
            "db_section_ms": self._milliseconds(in_section),
            "worker_finished_at_s": self._since_start(worker_finished),
            "worker_total_ms": self._milliseconds(worker_finished - worker_started),
            "result": result.code,
            "error": error,
        }))

    def _log_rejection(self, job, reason):
        logger.info(json.dumps({
            "event": "os_layer_rejected",
            "request_id": job.request_id,
            "student_id": job.student_code,
            "section_id": job.section_id,
            **asdict(self.config),
            "reason": reason,
            "queue_depth_at_arrival": job.queue_depth_at_arrival,
            "enqueued_at_s": self._since_start(job.enqueued_at),
        }))
