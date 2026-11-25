"""OutcomeRecorder: counters, bounded window, nearest-rank percentiles, thread safety."""
import random
import threading

import pytest

from app.iasl.telemetry import CANCELLED, OutcomeRecorder, nearest_rank
from workload import workload_generator as generator


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_percentile_rule_is_identical_to_the_workload_generators():
    rng = random.Random(7)
    for length in list(range(1, 60)) + [100, 101, 999]:
        values = sorted(rng.random() for _ in range(length))
        for percent in (50, 95, 99):
            assert nearest_rank(values, percent) == generator.percentile(values, percent)


def test_counters_count_outcomes_and_keep_cancelled_jobs_out_of_the_completed_total():
    recorder = OutcomeRecorder(clock=FakeClock())
    for code in ("SUCCESS", "SUCCESS", "FULL", "ERROR"):
        recorder.on_completed(code, 0.01, 0.02, 0.03)
    recorder.on_cancelled()
    counters = recorder.counters()
    assert counters["by_outcome"] == {"SUCCESS": 2, "FULL": 1, "ERROR": 1, CANCELLED: 1}
    assert counters["completed"] == 4
    assert counters["cancelled"] == 1


def test_counters_are_a_copy():
    recorder = OutcomeRecorder(clock=FakeClock())
    recorder.on_completed("SUCCESS", 0.0, 0.0, 0.0)
    recorder.counters()["by_outcome"]["SUCCESS"] = 99
    assert recorder.counters()["by_outcome"]["SUCCESS"] == 1


def test_window_percentiles_come_from_the_samples_in_the_window():
    clock = FakeClock()
    recorder = OutcomeRecorder(clock=clock)
    for i in range(1, 101):                      # waits 0.001 .. 0.100
        recorder.on_completed("SUCCESS", i / 1000, 0.0, i / 500)
    stats = recorder.window(clock.now, window_s=5, min_samples=20)
    assert stats.samples == 100
    assert stats.queue_wait_p50_s == pytest.approx(0.050)
    assert stats.queue_wait_p95_s == pytest.approx(0.095)
    assert stats.queue_wait_p99_s == pytest.approx(0.099)
    assert stats.server_latency_p95_s == pytest.approx(0.190)


def test_percentiles_are_none_below_the_minimum_sample_count():
    clock = FakeClock()
    recorder = OutcomeRecorder(clock=clock)
    for _ in range(19):
        recorder.on_completed("SUCCESS", 0.01, 0.0, 0.02)
    stats = recorder.window(clock.now, window_s=5, min_samples=20)
    assert stats.samples == 19
    assert stats.queue_wait_p95_s is None and stats.server_latency_p99_s is None   # never extrapolated
    recorder.on_completed("SUCCESS", 0.01, 0.0, 0.02)
    assert recorder.window(clock.now, 5, 20).queue_wait_p95_s == pytest.approx(0.01)


def test_empty_window_is_valid_and_has_no_percentiles():
    stats = OutcomeRecorder(clock=FakeClock()).window(1000.0, 5, 20)
    assert stats.samples == 0 and stats.queue_wait_p95_s is None


def test_old_completions_fall_out_of_the_window():
    clock = FakeClock(0.0)
    recorder = OutcomeRecorder(clock=clock)
    for _ in range(30):
        recorder.on_completed("SUCCESS", 5.0, 0.0, 5.0)     # slow, long ago
    clock.now = 100.0
    for _ in range(30):
        recorder.on_completed("SUCCESS", 0.01, 0.0, 0.02)   # fast, just now
    stats = recorder.window(clock.now, window_s=5, min_samples=20)
    assert stats.samples == 30
    assert stats.queue_wait_p99_s == pytest.approx(0.01)


def test_when_the_ring_is_too_small_the_window_reports_the_shorter_span_it_really_covers():
    clock = FakeClock(0.0)
    recorder = OutcomeRecorder(ring_size=16, clock=clock)
    for second in range(40):                      # one completion per second, ring keeps the last 16
        clock.now = float(second)
        recorder.on_completed("SUCCESS", 0.01, 0.0, 0.02)
    stats = recorder.window(clock.now, window_s=30, min_samples=1)
    assert stats.samples == 16
    assert stats.covered_s == pytest.approx(39.0 - 24.0)   # oldest kept entry is at t=24
    assert stats.covered_s < 30


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), None, "x", True])
def test_unusable_durations_are_counted_but_never_enter_the_window(bad):
    clock = FakeClock()
    recorder = OutcomeRecorder(clock=clock)
    recorder.on_completed("SUCCESS", bad, 0.0, 0.02)
    recorder.on_completed("SUCCESS", 0.01, 0.0, bad)
    counters = recorder.counters()
    assert counters["completed"] == 2 and counters["invalid_observations"] == 2
    assert recorder.window(clock.now, 5, 1).samples == 0


def test_ring_size_must_be_positive():
    with pytest.raises(ValueError):
        OutcomeRecorder(ring_size=0)


def test_many_writer_threads_lose_no_counts_and_the_ring_stays_bounded():
    recorder = OutcomeRecorder(ring_size=500)
    threads_n, each = 8, 2000

    def write():
        for i in range(each):
            recorder.on_completed("SUCCESS" if i % 2 else "FULL", 0.001, 0.0, 0.002)

    threads = [threading.Thread(target=write) for _ in range(threads_n)]
    reader_errors = []

    def read():
        try:
            for _ in range(200):
                recorder.window(1e12, 1e12, 1)
                recorder.counters()
        except Exception as error:   # a reader racing the writers must never fail
            reader_errors.append(error)

    reader = threading.Thread(target=read)
    for t in threads + [reader]:
        t.start()
    for t in threads + [reader]:
        t.join()
    counters = recorder.counters()
    assert counters["completed"] == threads_n * each
    assert counters["by_outcome"]["SUCCESS"] == counters["by_outcome"]["FULL"] == threads_n * each // 2
    assert recorder.window(1e12, 1e12, 1).samples == 500
    assert not reader_errors
