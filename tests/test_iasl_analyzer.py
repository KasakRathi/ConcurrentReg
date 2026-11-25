"""StateAnalyzer: classification, hysteresis, consecutive-sample validation, noise, missing data, explainability."""
import dataclasses

import pytest

from app.iasl.analyzer import StateAnalyzer
from app.iasl.config import IASLConfig
from app.iasl.types import Gauges, IntervalRates, MetricQuality, MetricsSample, SystemState, WindowStats

H, P, O = SystemState.HEALTHY, SystemState.UNDER_PRESSURE, SystemState.OVERLOADED


def make_sample(queue=0.0, wait_p95=None, rejection=0.0, error=None, worker=0.5, sem=0.0,
                quality=MetricQuality.OK, interval=True, taken_at=100.0, issues=(), admission_per_s=0.0):
    return MetricsSample(
        taken_at=taken_at, wall_time="2026-11-25T10:00:00.000", interval_s=0.5 if interval else None,
        quality=quality, restart=quality is MetricQuality.RESTART, issues=issues,
        gauges=Gauges(queue_utilization=queue, worker_utilization=worker, sem_waiting_ratio=sem),
        interval=IntervalRates(queue_full_rejection_rate=rejection, error_rate=error,
                               admission_rejections_per_s=admission_per_s) if interval else None,
        window=WindowStats(queue_wait_p95_s=wait_p95, samples=50 if wait_p95 is not None else 0),
    )


def analyzer(**changes):
    changes.setdefault("smoothing_samples", 1)       # isolate the rules from smoothing unless a test wants it
    return StateAnalyzer(IASLConfig(**changes))


def feed(a, *samples, now=None):
    return [a.assess(s, now=now) for s in samples]


CALM = dict(queue=0.05, worker=0.4)
BUSY_BACKLOG = dict(queue=0.60, worker=0.95)                      # primary pressure + a corroborating signal
OVERLOAD = dict(queue=0.95, worker=1.0, rejection=0.10)           # primary overload + corroboration


# ----------------------------------------------------------------------------- classification

def test_calm_system_is_healthy_with_no_transition():
    results = feed(analyzer(), *[make_sample(**CALM)] * 10)
    assert all(r.state is H and r.transition is None and r.candidate is H for r in results)
    assert all(r.quality is MetricQuality.OK and not r.held for r in results)


@pytest.mark.parametrize("sample_args, name", [
    (dict(queue=0.60), "queue_utilization"),
    (dict(wait_p95=0.20), "queue_wait_p95_s"),
    (dict(rejection=0.02), "queue_full_rejection_rate"),
    (dict(error=0.03), "error_rate"),
])
def test_one_primary_signal_at_pressure_level_means_under_pressure(sample_args, name):
    a = analyzer()
    first, second = feed(a, make_sample(**sample_args), make_sample(**sample_args))
    assert first.candidate is P and first.state is H                # one sample is not yet enough
    assert second.state is P and second.transition.to_state is P
    assert {s.name: s.level for s in second.signals}[name] == 1


def test_latency_only_pressure_is_possible_with_an_empty_queue():
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.0, wait_p95=0.30)] * 2)
    assert results[-1].state is P


def test_busy_workers_alone_are_not_pressure():
    """All workers and permits in use with no backlog is a healthy, fully used system."""
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.0, worker=1.0, sem=0.0)] * 10)
    assert all(r.state is H and r.candidate is H for r in results)


def test_one_corroborating_signal_alone_is_not_pressure_but_two_are():
    a = analyzer()
    assert feed(a, *[make_sample(queue=0.0, worker=1.0, sem=0.0)] * 4)[-1].state is H
    a = analyzer()
    assert feed(a, *[make_sample(queue=0.0, worker=0.95, sem=1.5)] * 2)[-1].state is P


def test_overload_needs_a_primary_signal_at_the_top_level_plus_corroboration():
    # primary at overload level but nothing else raised -> only UNDER_PRESSURE
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.90, worker=0.3, sem=0.0)] * 3)
    assert all(r.candidate is P for r in results)
    # the same with a corroborating signal -> OVERLOADED
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.90, worker=0.95)] * 2)
    assert results[0].candidate is O and results[-1].state is O


def test_two_primary_signals_corroborate_each_other():
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.90, error=0.20, worker=0.3)] * 2)   # queue overload + error overload
    assert results[-1].state is O


def test_a_corroborating_signal_cannot_make_the_system_overloaded_by_itself():
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.0, worker=1.0, sem=9.0)] * 6)
    assert max(r.state.value for r in results) != O.value
    assert results[-1].state is P


def test_admission_refusals_are_not_an_input():
    """Otherwise lowering the limit would cause refusals, look like overload, and lower the limit again."""
    a = analyzer()
    results = feed(a, *[make_sample(**CALM, admission_per_s=10_000.0)] * 8)
    assert all(r.state is H for r in results)
    assert not any("admission" in s.name for r in results for s in r.signals)


# ----------------------------------------------------------------------------- state machine

def test_a_single_bad_sample_does_not_change_the_state_and_resets_the_streak():
    a = analyzer()
    results = feed(a, make_sample(**BUSY_BACKLOG), make_sample(**CALM), make_sample(**BUSY_BACKLOG), make_sample(**CALM))
    assert [r.state for r in results] == [H, H, H, H]
    assert [r.worse_streak for r in results] == [1, 0, 1, 0]


def test_escalation_can_skip_a_level_only_if_every_sample_was_at_the_higher_state():
    a = analyzer()
    assert feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))[-1].state is O
    a = analyzer()
    # 0.40 is below queue utilisation's overload exit threshold (0.85 x 0.7 = 0.595) but inside the pressure band
    mixed = feed(a, make_sample(**OVERLOAD), make_sample(queue=0.40, worker=0.95))   # OVERLOADED, then only UNDER_PRESSURE
    assert [r.candidate for r in mixed] == [O, P]
    assert mixed[-1].state is P                                                # floor of the streak, not the peak


def test_a_reading_just_below_the_overload_threshold_stays_overloaded_inside_the_hysteresis_band():
    a = analyzer()
    feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))
    result = a.assess(make_sample(queue=0.60, worker=0.95))                    # 0.60 >= 0.595: still "overload" level
    assert result.candidate is O and {s.name: s.level for s in result.signals}["queue_utilization"] == 2


def test_de_escalation_is_one_level_at_a_time_and_needs_more_samples():
    a = analyzer()
    feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))
    assert a.state is O
    calm = [a.assess(make_sample(**CALM)) for _ in range(5)]
    assert [r.state for r in calm] == [O, O, O, O, P]                          # 5 samples to drop one level
    assert calm[-1].transition.from_state is O and calm[-1].transition.to_state is P
    calm = [a.assess(make_sample(**CALM)) for _ in range(5)]
    assert [r.state for r in calm] == [P, P, P, P, H]


def test_a_relapse_during_recovery_restarts_the_recovery_count():
    a = analyzer()
    feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))
    feed(a, *[make_sample(**CALM)] * 4)                                       # one short of dropping
    a.assess(make_sample(**OVERLOAD))                                         # relapse: same state, resets streaks
    assert a.state is O
    assert [a.assess(make_sample(**CALM)).state for _ in range(5)] == [O, O, O, O, P]


def test_streak_lengths_are_configurable():
    a = analyzer(escalate_samples=4, deescalate_samples=2)
    assert [r.state for r in feed(a, *[make_sample(**BUSY_BACKLOG)] * 4)] == [H, H, H, P]
    assert [r.state for r in feed(a, *[make_sample(**CALM)] * 2)] == [P, H]


# ----------------------------------------------------------------------------- hysteresis and noise

def test_a_signal_falls_back_only_below_its_exit_threshold():
    a = analyzer()
    levels = []
    for value in (0.55, 0.45, 0.40, 0.30):                                    # enter 0.50, exit 0.50 * 0.7 = 0.35
        result = a.assess(make_sample(queue=value, worker=0.3))
        levels.append({s.name: s.level for s in result.signals}["queue_utilization"])
    assert levels == [1, 1, 1, 0]


def test_a_value_hovering_at_the_threshold_causes_one_transition_not_a_flapping_state():
    a = analyzer()
    results = feed(a, *[make_sample(queue=0.52 if i % 2 == 0 else 0.48, worker=0.3) for i in range(40)])
    transitions = [r for r in results if r.transition]
    assert len(transitions) == 1 and transitions[0].transition.to_state is P
    assert results[-1].state is P


def test_alternating_extreme_samples_never_escalate():
    a = analyzer()
    samples = [make_sample(**OVERLOAD) if i % 2 == 0 else make_sample(**CALM) for i in range(60)]
    results = feed(a, *samples)
    assert all(r.state is H for r in results) and not any(r.transition for r in results)


def test_smoothing_absorbs_a_single_spike_in_a_jittery_gauge():
    a = analyzer(smoothing_samples=3)
    feed(a, make_sample(queue=0.0), make_sample(queue=0.0))
    spike = a.assess(make_sample(queue=1.0, worker=0.3))                      # mean of (0, 0, 1) = 0.33 < 0.50
    assert {s.name: s.level for s in spike.signals}["queue_utilization"] == 0
    sustained = feed(a, *[make_sample(queue=1.0, worker=0.3)] * 3)            # mean rises to 1.0
    assert {s.name: s.level for s in sustained[-1].signals}["queue_utilization"] == 2


# ----------------------------------------------------------------------------- missing, invalid, stale

def test_a_signal_with_no_value_is_excluded_not_treated_as_zero_or_carried_forward():
    a = analyzer()
    a.assess(make_sample(queue=0.0, wait_p95=2.0))                            # latency at overload level
    quiet = a.assess(make_sample(queue=0.0, wait_p95=None))                   # no completions this time
    by_name = {s.name: s for s in quiet.signals}
    assert by_name["queue_wait_p95_s"].value is None and by_name["queue_wait_p95_s"].level is None
    assert quiet.candidate is H                                               # old latency is not carried forward


def test_too_few_primary_signals_holds_the_state_and_says_so():
    a = analyzer()
    feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))
    assert a.state is O
    held = a.assess(make_sample(queue=0.0, interval=False))                   # only queue utilisation is known
    assert held.held and held.quality is MetricQuality.DEGRADED and held.state is O and held.candidate is None
    assert "primary signal" in held.reason


def test_the_first_sample_without_interval_values_is_held_not_misjudged():
    a = analyzer()
    first = a.assess(make_sample(queue=0.9, worker=1.0, interval=False))      # looks terrible, but cannot be corroborated
    assert first.held and first.state is H


@pytest.mark.parametrize("quality", [MetricQuality.INVALID, MetricQuality.DEGRADED])
def test_untrustworthy_samples_hold_the_state_and_are_not_evaluated(quality):
    a = analyzer()
    feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))
    held = a.assess(make_sample(**CALM, quality=quality, issues=("queue.depth_invalid",)))
    assert held.held and held.state is O and held.quality is quality
    assert "queue.depth_invalid" in held.reason and held.signals == ()


def test_a_stale_sample_holds_the_state():
    a = analyzer()
    feed(a, make_sample(**OVERLOAD, taken_at=100.0), make_sample(**OVERLOAD, taken_at=100.5))
    stale = a.assess(make_sample(**CALM, taken_at=100.5), now=110.0)          # 9.5 s old, limit 2 s
    assert stale.held and stale.quality is MetricQuality.STALE and stale.state is O
    fresh = a.assess(make_sample(**CALM, taken_at=110.0), now=110.1)
    assert not fresh.held


def test_held_samples_freeze_the_streaks_they_do_not_reset_them():
    a = analyzer()
    a.assess(make_sample(**BUSY_BACKLOG))                                     # streak 1 of 2
    a.assess(make_sample(**CALM, quality=MetricQuality.INVALID))              # frozen
    result = a.assess(make_sample(**BUSY_BACKLOG))                            # streak 2 -> transition
    assert result.state is P


def test_a_held_sample_does_not_pollute_the_smoothing_history():
    a = analyzer(smoothing_samples=2)
    a.assess(make_sample(queue=0.0))
    a.assess(make_sample(queue=1.0, quality=MetricQuality.INVALID))           # must not enter the history
    result = a.assess(make_sample(queue=0.0))
    assert {s.name: s.value for s in result.signals}["queue_utilization"] == 0.0


def test_restart_resets_to_healthy_clears_history_and_explains_it():
    a = analyzer()
    feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))
    result = a.assess(make_sample(**CALM, quality=MetricQuality.RESTART, issues=("layer_replaced",)))
    assert result.state is H and result.quality is MetricQuality.RESTART and result.held
    assert result.transition.from_state is O and result.transition.to_state is H
    assert "layer_replaced" in result.transition.reason
    assert a.assess(make_sample(**CALM)).state is H and a._levels == {k: 0 for k in a._levels}


def test_restart_while_already_healthy_makes_no_transition():
    a = analyzer()
    result = a.assess(make_sample(**CALM, quality=MetricQuality.RESTART, issues=("layer_replaced",)))
    assert result.transition is None and result.state is H


# ----------------------------------------------------------------------------- explainability

def test_every_transition_names_the_signals_and_thresholds_that_caused_it():
    a = analyzer()
    result = feed(a, make_sample(**OVERLOAD), make_sample(**OVERLOAD))[-1]
    transition = result.transition
    assert (transition.from_state, transition.to_state) == (H, O)
    assert "queue_utilization=0.95" in transition.reason and "threshold 0.85" in transition.reason
    assert "queue_full_rejection_rate" in transition.reason
    assert transition.reason == result.reason
    assert {s.name for s in transition.signals} == {s.name for s in result.signals}
    assert all(dataclasses.is_dataclass(s) for s in transition.signals)


def test_a_steady_assessment_explains_itself_too():
    a = analyzer()
    result = a.assess(make_sample(**CALM))
    assert "HEALTHY" in result.reason and "no signal above its threshold" in result.reason


def test_thresholds_come_from_the_configuration():
    a = analyzer(queue_util_pressure=0.2, queue_util_overload=0.3)
    results = feed(a, *[make_sample(queue=0.25, worker=0.3)] * 2)
    assert results[-1].state is P                                             # 0.25 would be healthy under the defaults
