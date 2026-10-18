from dataclasses import dataclass


@dataclass
class AdaptiveMetrics:
    queue_length: int
    active_requests: int
    max_concurrency: int
    contention_rate: float
    retry_rate: float


class AdaptiveController:
    """
    Deterministic adaptive concurrency controller for ConcurrentReg.

    The controller observes runtime metrics and decides whether the
    allowed concurrency should increase, remain unchanged, or decrease.
    """

    def __init__(
        self,
        initial_concurrency: int = 4,
        min_concurrency: int = 1,
        max_concurrency: int = 16,
        low_threshold: float = 0.3,
        high_threshold: float = 0.7,
        persistence: int = 2,
    ):
        if min_concurrency <= 0:
            raise ValueError("min_concurrency must be positive")

        if max_concurrency < min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")

        if not min_concurrency <= initial_concurrency <= max_concurrency:
            raise ValueError(
                "initial_concurrency must be between min_concurrency and "
                "max_concurrency"
            )

        if not 0 <= low_threshold < high_threshold <= 1:
            raise ValueError(
                "thresholds must satisfy 0 <= low_threshold < "
                "high_threshold <= 1"
            )

        if persistence <= 0:
            raise ValueError("persistence must be positive")

        self.current_concurrency = initial_concurrency
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency

        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

        self.persistence = persistence
        self._pending_action = None
        self._pending_count = 0

    def calculate_contention_score(self, metrics: AdaptiveMetrics) -> float:
        """
        Calculate a normalized contention score in the range [0, 1].

        The score combines:
        - queue pressure
        - active-request pressure
        - contention rate
        - retry rate
        """

        queue_pressure = min(
            metrics.queue_length / max(metrics.max_concurrency, 1),
            1.0,
        )

        active_pressure = min(
            metrics.active_requests / max(metrics.max_concurrency, 1),
            1.0,
        )

        contention = min(max(metrics.contention_rate, 0.0), 1.0)
        retry = min(max(metrics.retry_rate, 0.0), 1.0)

        score = (
            0.25 * queue_pressure
            + 0.25 * active_pressure
            + 0.30 * contention
            + 0.20 * retry
        )

        return round(min(max(score, 0.0), 1.0), 4)

    def classify_contention(self, score: float) -> str:
        """Classify contention as low, medium, or high."""

        if score < self.low_threshold:
            return "low"

        if score < self.high_threshold:
            return "medium"

        return "high"

    def _requested_action(self, state: str) -> str:
        """Map contention state to an adaptive action."""

        if state == "high":
            return "decrease"

        if state == "low":
            return "increase"

        return "maintain"

    def decide(self, metrics: AdaptiveMetrics) -> str:
        """
        Decide the next concurrency action.

        Persistence prevents the controller from changing state because
        of a single noisy measurement.
        """

        score = self.calculate_contention_score(metrics)
        state = self.classify_contention(score)
        action = self._requested_action(state)

        if action == "maintain":
            self._pending_action = None
            self._pending_count = 0
            return "maintain"

        if action != self._pending_action:
            self._pending_action = action
            self._pending_count = 1
            return "maintain"

        self._pending_count += 1

        if self._pending_count < self.persistence:
            return "maintain"

        self._pending_action = None
        self._pending_count = 0

        if action == "increase":
            if self.current_concurrency < self.max_concurrency:
                self.current_concurrency += 1
                return "increase"

            return "maintain"

        if action == "decrease":
            if self.current_concurrency > self.min_concurrency:
                self.current_concurrency -= 1
                return "decrease"

            return "maintain"

        return "maintain"