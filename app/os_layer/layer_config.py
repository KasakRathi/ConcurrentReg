"""Settings for the Day 3 OS concurrency layer: queue capacity, worker count, DB permits."""
import os
from dataclasses import dataclass

# Development defaults, only so the server can start locally.
# They are NOT experimental conclusions and NOT recommended values.
DEFAULT_QUEUE_CAPACITY = 16
DEFAULT_WORKER_COUNT = 4
DEFAULT_DB_SEMAPHORE_PERMITS = 2


@dataclass(frozen=True)
class OSLayerConfig:
    queue_capacity: int = DEFAULT_QUEUE_CAPACITY
    worker_count: int = DEFAULT_WORKER_COUNT
    db_semaphore_permits: int = DEFAULT_DB_SEMAPHORE_PERMITS

    def __post_init__(self):
        for name in ("queue_capacity", "worker_count", "db_semaphore_permits"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a whole number of at least 1, got {value!r}")

    @classmethod
    def from_environment(cls):
        """Read QUEUE_CAPACITY, WORKER_COUNT and DB_SEMAPHORE_PERMITS (each optional)."""
        return cls(
            queue_capacity=_read_whole_number("QUEUE_CAPACITY", DEFAULT_QUEUE_CAPACITY),
            worker_count=_read_whole_number("WORKER_COUNT", DEFAULT_WORKER_COUNT),
            db_semaphore_permits=_read_whole_number("DB_SEMAPHORE_PERMITS", DEFAULT_DB_SEMAPHORE_PERMITS),
        )


def _read_whole_number(variable_name, default):
    text = os.environ.get(variable_name)
    if text is None:
        return default
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{variable_name} must be a whole number, got {text!r}") from None
