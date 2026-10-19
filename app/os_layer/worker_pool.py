"""The worker pool: a fixed number of server-side threads that take jobs off the queue.

This is the SERVER-side pool. It is not the client-side pool inside the Day 2 workload generator.
It knows nothing about registrations: it only takes a job, calls `handle_job(job)`, and survives errors.
"""
import logging
import queue
import threading
import time

logger = logging.getLogger("os_layer")


class WorkerPool:
    def __init__(self, work_queue, worker_count, handle_job):
        self.work_queue = work_queue
        self.worker_count = worker_count
        self.handle_job = handle_job
        self._threads = []
        self._lock = threading.Lock()
        self.active = 0            # workers handling a job right now
        self.max_active = 0
        self.jobs_started = 0
        self.jobs_finished = 0
        self.unexpected_errors = 0  # handle_job raised; the worker survived

    def start(self):
        if self._threads:
            raise RuntimeError("the worker pool is already started")
        for number in range(1, self.worker_count + 1):
            thread = threading.Thread(target=self._worker_loop, name=f"worker-{number}", daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self, timeout_seconds=30):
        """Graceful stop: accept nothing new, let workers finish what the queue already holds.

        Returns the names of workers still running after the timeout (normally none).
        """
        self.work_queue.shutdown()
        deadline = time.monotonic() + timeout_seconds
        for thread in self._threads:
            thread.join(max(0, deadline - time.monotonic()))
        return [thread.name for thread in self._threads if thread.is_alive()]

    def alive_workers(self):
        return sum(1 for thread in self._threads if thread.is_alive())

    def _worker_loop(self):
        while True:
            try:
                job = self.work_queue.get()  # waits here while the queue is empty
            except queue.ShutDown:
                return  # queue is shut down and empty: nothing is left to do
            self._run_one(job)

    def _run_one(self, job):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.jobs_started += 1
        try:
            self.handle_job(job)
        except Exception:
            # One bad job must never kill a worker, or capacity would shrink silently.
            with self._lock:
                self.unexpected_errors += 1
            logger.exception("worker %s: handle_job raised unexpectedly", threading.current_thread().name)
        finally:
            with self._lock:
                self.active -= 1
                self.jobs_finished += 1
            # Tell the queue this job is done, even if it failed. Without this the queue's own
            # count of unfinished jobs only grows, and queue.join() could never return.
            self.work_queue.task_done()
