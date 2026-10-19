"""The bounded queue: holds admitted requests that are waiting for a worker.

It is Python's thread-safe queue.Queue(maxsize=capacity), so the upper bound is enforced
by the standard library: a put on a full queue is refused and never stored.
Order is first-in-first-out (a simple deterministic policy; see the code note).
"""
import queue
import threading

# Outcomes of try_put()
ADDED = "ADDED"
FULL = "FULL"
SHUT_DOWN = "SHUT_DOWN"


class BoundedRequestQueue(queue.Queue):
    def __init__(self, capacity):
        super().__init__(maxsize=capacity)
        self.capacity = capacity
        self.accepted = 0             # items that entered the queue
        self.max_depth = 0            # most items ever waiting at the same time
        self.rejected_full = 0        # refused because the queue was full
        self.rejected_shut_down = 0   # refused because the queue was shut down
        self._refusal_lock = threading.Lock()

    def _put(self, item):
        # queue.Queue calls this while holding its own lock, so these two numbers are exact.
        super()._put(item)
        self.accepted += 1
        self.max_depth = max(self.max_depth, self._qsize())

    def try_put(self, item):
        """Add `item` if there is room. Never waits. Returns ADDED, FULL or SHUT_DOWN."""
        try:
            self.put_nowait(item)
        except queue.Full:
            with self._refusal_lock:
                self.rejected_full += 1
            return FULL
        except queue.ShutDown:
            with self._refusal_lock:
                self.rejected_shut_down += 1
            return SHUT_DOWN
        return ADDED
