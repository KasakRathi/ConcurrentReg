"""MetricsCollector: valid samples, intervals, restart, missing/invalid/stale data, recorder, concurrency."""
import copy
import threading

import pytest

from app.iasl.config import IASLConfig
from app.iasl.metrics import MetricsCollector
from app.iasl.telemetry import OutcomeRecorder
from app.iasl.types import MetricQuality
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import OSConcurrencyLayer


def make_snapshot(**changes):
    """The exact shape of OSConcurrencyLayer.snapshot(), with overridable leaf values (group__field=value)."""
    snap = {
        "config": {"queue_capacity": 100, "worker_count": 8, "db_semaphore_permits": 4},
        "queue": {"capacity": 100, "depth": 10, "max_depth": 10, "accepted": 0, "rejected_queue_full": 0,
                  "rejected_shutting_down": 0},
        "queue_wait": {"jobs_dequeued": 0, "total_s": 0.0, "max_s": 0.0, "average_s": None},
        "workers": {"configured": 8, "alive": 8, "active": 4, "max_active": 4, "jobs_started": 0,
                    "jobs_finished": 0, "unexpected_errors": 0},
        "db_semaphore": {"permits": 4, "in_critical_section": 2, "max_in_critical_section": 2, "waiting": 1,
                         "max_waiting": 1, "acquisitions": 0, "wait_total_s": 0.0, "wait_max_s": 0.0},
    }
    for key, value in changes.items():
        group, field = key.split("__")
        snap[group][field] = value
    return snap


class FakeLayer:
    def __init__(self, **changes):
        self.snap = make_snapshot(**changes)
        self.fail = None

    def set(self, **changes):
        for key, value in changes.items():
            group, field = key.split("__")
            self.snap[group][field] = value

    def snapshot(self):
        if self.fail:
            raise self.fail
        return copy.deepcopy(self.snap)


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def setup():
    layer, clock, recorder = FakeLayer(), Clock(), OutcomeRecorder(clock=Clock())
    recorder._clock = clock
    holder = {"layer": layer}
    collector = MetricsCollector(IASLConfig(), lambda: holder["layer"], lambda: recorder, clock=clock)
    return collector, layer, clock, recorder, holder


# ----------------------------------------------------------------------------- valid data

def test_first_sample_has_gauges_but_no_interval_values(setup):
    collector, layer, clock, *_ = setup
    sample = collector.sample()
    assert sample.quality is MetricQuality.OK and not sample.issues and not sample.restart
    assert sample.interval is None and sample.interval_s is None
    g = sample.gauges
    assert (g.queue_depth, g.queue_capacity, g.queue_utilization) == (10, 100, 0.10)
    assert (g.workers_alive, g.workers_active, g.workers_idle, g.worker_utilization) == (8, 4, 4, 0.5)
    assert (g.sem_permits, g.sem_in_use, g.sem_available, g.sem_utilization, g.sem_waiting_ratio) == (4, 2, 2, 0.5, 0.25)
    assert sample.wall_time and sample.taken_at == clock.now


def test_interval_rates_come_from_counter_differences(setup):
    collector, layer, clock, recorder, _ = setup
    collector.sample()
    clock.now += 2.0
    layer.set(queue__accepted=60, queue__rejected_queue_full=20, queue__rejected_shutting_down=0,
              queue_wait__jobs_dequeued=40, queue_wait__total_s=4.0, workers__jobs_finished=40)
    for code in ["SUCCESS"] * 36 + ["ERROR"] * 4:
        recorder.on_completed(code, 0.1, 0.0, 0.2)
    s = collector.sample()
    assert s.quality is MetricQuality.OK and s.interval_s == pytest.approx(2.0)
    i = s.interval
    assert i.arrivals_per_s == pytest.approx(40.0)                  # (60 + 20) / 2 s
    assert i.queue_full_rejections_per_s == pytest.approx(10.0)
    assert i.queue_full_rejection_rate == pytest.approx(0.25)       # 20 of 80 arrivals
    assert i.completed_per_s == pytest.approx(20.0)                 # 40 outcomes / 2 s
    assert i.error_rate == pytest.approx(0.10)                      # 4 of 40
    assert i.avg_queue_wait_s == pytest.approx(0.1)                 # 4.0 s over 40 jobs
    assert i.admission_rejections_per_s == 0.0


def test_a_later_interval_uses_only_the_new_activity_not_lifetime_totals(setup):
    collector, layer, clock, *_ = setup
    layer.set(queue__accepted=1000, queue__rejected_queue_full=500)
    collector.sample()
    clock.now += 1.0
    layer.set(queue__accepted=1010)                                  # 10 new arrivals, none refused
    s = collector.sample()
    assert s.interval.arrivals_per_s == pytest.approx(10.0)
    assert s.interval.queue_full_rejection_rate == 0.0


def test_idle_system_is_ok_with_zero_rejection_rate_and_no_error_rate(setup):
    collector, layer, clock, *_ = setup
    collector.sample()
    clock.now += 0.5
    s = collector.sample()
    assert s.quality is MetricQuality.OK
    assert s.interval.arrivals_per_s == 0.0
    assert s.interval.queue_full_rejection_rate == 0.0              # nothing arrived, so nothing was refused
    assert s.interval.error_rate is None and s.interval.avg_queue_wait_s is None
    assert s.window.samples == 0 and s.window.queue_wait_p95_s is None   # no traffic is not "degraded"


def test_window_statistics_are_attached_from_the_recorder(setup):
    collector, layer, clock, recorder, _ = setup
    for i in range(1, 51):
        recorder.on_completed("SUCCESS", i / 100, 0.0, i / 50)
    s = collector.sample()
    assert s.window.samples == 50
    assert s.window.queue_wait_p95_s == pytest.approx(0.48)


def test_without_a_recorder_completions_come_from_the_layer_and_error_rate_is_unavailable():
    layer, clock = FakeLayer(), Clock()
    collector = MetricsCollector(IASLConfig(), lambda: layer, clock=clock)
    collector.sample()
    clock.now += 1.0
    layer.set(workers__jobs_finished=30)
    s = collector.sample()
    assert s.interval.completed_per_s == pytest.approx(30.0)
    assert s.interval.error_rate is None
    assert s.window.samples == 0


def test_admission_block_is_optional_and_used_when_present(setup):
    collector, layer, clock, *_ = setup
    s = collector.sample()
    assert s.admission_limit is None                                 # no admission control installed yet
    layer.snap["admission"] = {"enabled": True, "limit": 40, "rejected": 0, "fallback": False}
    collector.sample()
    clock.now += 2.0
    layer.snap["admission"]["rejected"] = 30
    layer.set(queue__accepted=10)
    s = collector.sample()
    assert s.admission_limit == 40
    assert s.interval.admission_rejections_per_s == pytest.approx(15.0)
    assert s.interval.arrivals_per_s == pytest.approx(20.0)         # 10 accepted + 30 admission-refused, over 2 s
    assert s.interval.queue_full_rejection_rate == 0.0              # self-inflicted refusals are not queue-full


def test_unavailable_metrics_are_listed_with_reasons_and_not_shared_between_samples(setup):
    collector, *_ = setup
    s = collector.sample()
    assert set(s.unavailable) >= {"timed_out_requests", "timeout_rate", "db_timeouts", "db_lock_wait"}
    s.unavailable["x"] = "mutation"
    assert "x" not in collector.sample().unavailable


# ----------------------------------------------------------------------------- restart

def test_counters_going_backwards_is_a_restart_without_interval_values(setup):
    collector, layer, clock, *_ = setup
    layer.set(queue__accepted=500)
    collector.sample()
    clock.now += 1.0
    layer.set(queue__accepted=3)
    s = collector.sample()
    assert s.quality is MetricQuality.RESTART and s.restart
    assert s.interval is None and s.interval_s is None
    assert any(i.startswith("counter_decreased") and "accepted" in i for i in s.issues)
    clock.now += 1.0
    layer.set(queue__accepted=13)
    nxt = collector.sample()                                          # intervals resume from the new baseline
    assert nxt.quality is MetricQuality.OK and nxt.interval.arrivals_per_s == pytest.approx(10.0)


def test_a_different_layer_object_is_a_restart_even_if_counters_look_normal(setup):
    collector, layer, clock, _, holder = setup
    collector.sample()
    holder["layer"] = FakeLayer()                                     # e.g. replaced by POST /demo/os-layer
    clock.now += 1.0
    s = collector.sample()
    assert s.restart and s.quality is MetricQuality.RESTART and "layer_replaced" in s.issues
    assert s.interval is None


def test_recorder_counters_going_backwards_is_also_a_restart(setup):
    collector, layer, clock, recorder, _ = setup
    recorder.on_completed("SUCCESS", 0.0, 0.0, 0.0)
    collector.sample()
    recorder._counts.clear()
    clock.now += 1.0
    s = collector.sample()
    assert s.restart and any("outcomes_completed" in i for i in s.issues)


def test_reset_makes_the_next_sample_a_fresh_start(setup):
    collector, layer, clock, *_ = setup
    collector.sample()
    collector.reset()
    clock.now += 1.0
    s = collector.sample()
    assert s.interval is None and s.quality is MetricQuality.OK


# ----------------------------------------------------------------------------- missing / invalid

@pytest.mark.parametrize("group, field, label", [
    ("queue", "depth", "queue.depth"), ("queue", "capacity", "queue.capacity"),
    ("workers", "alive", "workers.alive"), ("workers", "active", "workers.active"),
    ("db_semaphore", "permits", "db_semaphore.permits"), ("db_semaphore", "waiting", "db_semaphore.waiting"),
])
def test_a_missing_field_makes_the_sample_invalid_and_is_named_not_guessed(setup, group, field, label):
    collector, layer, *_ = setup
    del layer.snap[group][field]
    s = collector.sample()
    assert s.quality is MetricQuality.INVALID
    assert f"{label}_missing" in s.issues


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), "7", None, True, [1]])
def test_an_invalid_value_becomes_none_and_is_reported(setup, bad):
    collector, layer, *_ = setup
    layer.set(queue__depth=bad)
    s = collector.sample()
    assert s.quality is MetricQuality.INVALID
    assert s.gauges.queue_depth is None and s.gauges.queue_utilization is None
    assert "queue.depth_invalid" in s.issues
    assert s.gauges.queue_capacity == 100                             # other fields are still reported


def test_a_whole_missing_group_is_reported_for_each_field(setup):
    collector, layer, *_ = setup
    del layer.snap["db_semaphore"]
    s = collector.sample()
    assert s.quality is MetricQuality.INVALID
    assert s.gauges.sem_permits is None and s.gauges.sem_utilization is None


@pytest.mark.parametrize("changes, issue", [
    ({"queue__depth": 101}, "queue.depth_exceeds_capacity"),
    ({"workers__active": 9}, "workers.active_exceeds_alive"),
    ({"db_semaphore__in_critical_section": 5}, "db_semaphore.in_use_exceeds_permits"),
])
def test_impossible_combinations_are_reported_and_the_value_dropped_not_clamped(setup, changes, issue):
    collector, layer, *_ = setup
    layer.set(**changes)
    s = collector.sample()
    assert s.quality is MetricQuality.INVALID and issue in s.issues


def test_a_snapshot_that_raises_gives_an_invalid_sample_instead_of_an_exception(setup):
    collector, layer, clock, *_ = setup
    layer.fail = RuntimeError("boom")
    s = collector.sample()
    assert s.quality is MetricQuality.INVALID and s.issues == ("snapshot_failed:RuntimeError",)
    assert s.interval is None and s.gauges.queue_depth is None
    layer.fail = None
    clock.now += 0.5
    assert collector.sample().quality is MetricQuality.OK            # recovers by itself


def test_a_broken_recorder_degrades_the_sample_but_does_not_raise(setup):
    collector, layer, clock, recorder, _ = setup

    def explode():
        raise RuntimeError("bad recorder")
    recorder.counters = explode
    s = collector.sample()
    assert s.quality is MetricQuality.INVALID and any(i.startswith("recorder_failed") for i in s.issues)


def test_zero_alive_workers_is_noted_and_has_no_utilisation(setup):
    collector, layer, *_ = setup
    layer.set(workers__alive=0, workers__active=0)
    s = collector.sample()
    assert s.quality is MetricQuality.DEGRADED and "no_alive_workers" in s.issues
    assert s.gauges.worker_utilization is None


# ----------------------------------------------------------------------------- time

def test_a_long_gap_is_flagged_degraded_but_rates_are_still_computed(setup):
    collector, layer, clock, *_ = setup
    collector.sample()
    clock.now += 60.0                                                 # the loop stalled
    layer.set(queue__accepted=600)
    s = collector.sample()
    assert s.quality is MetricQuality.DEGRADED and "long_interval" in s.issues
    assert s.interval.arrivals_per_s == pytest.approx(10.0)


def test_a_clock_that_did_not_advance_gives_no_interval(setup):
    collector, *_ = setup
    collector.sample()
    s = collector.sample()                                            # same instant
    assert s.interval is None and "non_positive_interval" in s.issues


def test_staleness_is_judged_by_age_at_the_time_of_use(setup):
    collector, _, clock, *_ = setup
    s = collector.sample()
    assert not s.is_stale(clock.now + 1.9, stale_after_s=2.0)
    assert s.is_stale(clock.now + 2.1, stale_after_s=2.0)
    assert s.age(clock.now + 5) == pytest.approx(5.0)


# ----------------------------------------------------------------------------- real layer + concurrency

def test_the_collector_reads_the_real_layers_snapshot_without_any_issue():
    """Guards against drift: if snapshot() changes shape, this fails instead of IASL silently going blind."""
    layer = OSConcurrencyLayer(OSLayerConfig(queue_capacity=20, worker_count=3, db_semaphore_permits=2))
    layer.start()
    try:
        collector = MetricsCollector(IASLConfig(), lambda: layer)
        first = collector.sample()
        second = collector.sample()
    finally:
        layer.stop(timeout_seconds=3)
    for s in (first, second):
        assert s.quality in (MetricQuality.OK, MetricQuality.DEGRADED)
        assert not [i for i in s.issues if i.endswith(("_missing", "_invalid")) or "exceeds" in i]
        assert s.gauges.queue_capacity == 20 and s.gauges.workers_alive == 3 and s.gauges.sem_permits == 2


def test_concurrent_callers_never_corrupt_the_collector_or_raise(setup):
    collector, layer, clock, *_ = setup
    errors = []

    def hammer():
        try:
            for _ in range(300):
                clock.now += 0.001
                collector.sample()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
