"""The DB semaphore: limits how many workers are inside the database section at once.

Only the database work is wrapped by it (see request_pipeline.py), not the whole request.
"""
import threading
import time
from contextlib import contextmanager


class DbSemaphore:
    def __init__(self, permits):
        self.permits = permits
        # BoundedSemaphore raises an error if a permit is ever given back twice.
        self._semaphore = threading.BoundedSemaphore(permits)
        self._lock = threading.Lock()
        self.in_critical_section = 0       # workers holding a permit right now
        self.max_in_critical_section = 0
        self.waiting = 0                   # workers blocked, waiting for a permit
        self.max_waiting = 0
        self.acquisitions = 0
        self.wait_total_s = 0.0
        self.wait_max_s = 0.0

    @contextmanager
    def hold(self):
        """Wait for a permit, run the protected block, always give the permit back.

        Yields how many seconds this caller waited for the permit.
        """
        waited = self._acquire()
        try:
            yield waited
        finally:
            self._release()

    def _acquire(self):
        with self._lock:
            self.waiting += 1
            self.max_waiting = max(self.max_waiting, self.waiting)
        start = time.perf_counter()  # monotonic clock, as in the workload generator
        try:
            self._semaphore.acquire()
        finally:
            with self._lock:
                self.waiting -= 1
        waited = time.perf_counter() - start
        with self._lock:
            self.in_critical_section += 1
            self.max_in_critical_section = max(self.max_in_critical_section, self.in_critical_section)
            self.acquisitions += 1
            self.wait_total_s += waited
            self.wait_max_s = max(self.wait_max_s, waited)
        return waited

    def _release(self):
        # Count down first, then free the permit, so the counter can never read
        # higher than the number of permits.
        with self._lock:
            self.in_critical_section -= 1
        self._semaphore.release()
