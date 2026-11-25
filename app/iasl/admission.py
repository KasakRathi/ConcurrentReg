"""The admission controller: the only IASL code that runs on the request path.

submit() asks it one question per request, on the event-loop thread: "may this request enter the queue?".
It answers from a single integer (the admission depth limit) and the clock. It takes no lock, does no I/O,
and keeps no per-request state, so it cannot leak anything or slow a response measurably.

The limit is written only by the IASL controller thread through set_limit(), which enforces the hard
bound 1 <= limit <= queue capacity by itself (defence in depth: it does not trust its caller).

Two safety behaviours live here, not in the controller thread, so they work even if that thread dies:
  * a watchdog: if no heartbeat arrived within `watchdog_s`, the FALLBACK limit is used;
  * explicit fallback mode, entered and left by the controller.
At limit == capacity the check is skipped entirely, so behaviour is identical to running without IASL.
"""
import time


def _whole(name, value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number between {low} and {high}, got {value!r}")
    return value


class AdmissionController:
    def __init__(self, capacity, initial, fallback_limit, watchdog_s, clock=time.monotonic):
        self.capacity = _whole("capacity", capacity, 1, 10**9)
        self._limit = _whole("initial limit", initial, 1, capacity)
        self._fallback_limit = _whole("fallback limit", fallback_limit, 1, capacity)
        if not watchdog_s > 0:
            raise ValueError(f"watchdog_s must be positive, got {watchdog_s!r}")
        self._watchdog_s = watchdog_s
        self._clock = clock
        self._fallback = False
        self._heartbeat = clock()   # attach counts as the first sign of life

    # ------------------------------------------------------------------ request path

    def check(self, queue_depth):
        """True = admit. O(1), lock-free. At limit == capacity every request is admitted (the queue's own bound applies)."""
        limit = self.effective_limit()
        if limit >= self.capacity:
            return True
        return queue_depth < limit

    def effective_limit(self):
        """The limit in force right now: the fallback value if fallback is on or the controller thread went silent."""
        if self._fallback or (self._clock() - self._heartbeat) > self._watchdog_s:
            return self._fallback_limit
        return self._limit

    # ------------------------------------------------------------------ controller side

    def set_limit(self, value):
        """Set the limit. Refuses anything outside [1, capacity]; the previous value is kept."""
        self._limit = _whole("limit", value, 1, self.capacity)

    def heartbeat(self):
        self._heartbeat = self._clock()

    def enter_fallback(self):
        self._fallback = True

    def exit_fallback(self):
        self._fallback = False
        self._heartbeat = self._clock()

    # ------------------------------------------------------------------ read side

    @property
    def in_fallback(self):
        return self._fallback

    @property
    def watchdog_tripped(self):
        return (not self._fallback) and (self._clock() - self._heartbeat) > self._watchdog_s

    def stats(self):
        return {
            "limit": self.effective_limit(), "configured_limit": self._limit, "capacity": self.capacity,
            "fallback": self._fallback, "fallback_limit": self._fallback_limit,
            "watchdog_tripped": self.watchdog_tripped,
            "seconds_since_heartbeat": round(self._clock() - self._heartbeat, 3),
        }
