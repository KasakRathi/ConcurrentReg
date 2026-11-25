"""The experiment analysis (scripts/iasl_analysis.py), checked against synthetic data whose right answer is known by construction."""
import random

import pytest

from scripts import iasl_analysis as ia
from workload import workload_generator as generator


def row(seq, category, intended, latency, status=200, section=1):
    end = None if latency is None else intended + latency
    return [seq, section, category, status if latency is not None else None, intended, intended, end]


def make_rows(spec):
    """spec: list of (category, intended_s, latency_s)."""
    return [row(i, c, t, lat) for i, (c, t, lat) in enumerate(spec)]


def test_the_percentile_rule_is_the_generators():
    rng = random.Random(1)
    for n in list(range(1, 50)) + [200, 999]:
        values = sorted(rng.random() for _ in range(n))
        for p in (50, 95, 99):
            assert ia.percentile(values, p) == generator.percentile(values, p)


def test_stats_of_nothing_is_none_not_zero():
    assert ia.stats([]) is None
    assert ia.stats([2.0, 1.0, 3.0])["p50"] == 2.0


def test_compact_rows_keep_exactly_what_the_analysis_needs():
    record = {"sequence": 7, "section_id": 3, "category": "SUCCESS", "http_status": 201, "intended_offset_s": 1.0,
              "sent_offset_s": 1.01, "end_offset_s": 1.2, "extra": "dropped"}
    assert ia.compact_rows([record]) == [[7, 3, "SUCCESS", 201, 1.0, 1.01, 1.2]]


# ----------------------------------------------------------------------------- the service-latency set

def test_refusals_and_errors_never_enter_the_latency_set_but_timeouts_do_at_the_timeout_value():
    rows = make_rows([("SUCCESS", 0.0, 0.1), ("DUPLICATE", 0.0, 0.2), ("COURSE_FULL", 0.0, 0.3),
                      ("QUEUE_FULL", 0.0, 0.001), ("ADMISSION_REJECTED", 0.0, 0.001), ("SERVER_ERROR", 0.0, 0.5),
                      ("TIMEOUT", 0.0, None), ("CONNECTION_ERROR", 0.0, None)])
    assert sorted(ia.service_latencies_s(rows, timeout_s=5.0)) == [0.1, 0.2, 0.3, 5.0]


def test_a_system_that_refuses_most_work_cannot_look_faster_in_the_headline_latency():
    served_slowly = make_rows([("SUCCESS", i * 0.01, 1.0) for i in range(100)])
    refuses_nearly_all = make_rows([("SUCCESS", i * 0.01, 1.0) for i in range(10)] + [("ADMISSION_REJECTED", i * 0.01, 0.001) for i in range(90)])
    slow = ia.run_metrics(served_slowly, [], 100, 5.0)
    refusing = ia.run_metrics(refuses_nearly_all, [], 100, 5.0)
    assert slow["service_latency_s"]["p95"] == refusing["service_latency_s"]["p95"] == 1.0   # refusals did not lower it
    assert refusing["rates"]["admission_rejected"] == 0.9 and slow["rates"]["admission_rejected"] == 0.0
    assert refusing["all_answered_latency_s"]["p50"] < 0.01                                   # the misleading number exists, labelled as such
    assert refusing["goodput_per_s"] < slow["goodput_per_s"] / 5                               # and goodput exposes the lost work


def test_latency_is_measured_from_the_intended_arrival_not_from_when_the_generator_got_round_to_sending():
    late = [[0, 1, "SUCCESS", 201, 1.0, 1.5, 1.6]]                    # meant to arrive at 1.0, sent at 1.5, answered at 1.6
    assert ia.service_latencies_s(late, 5.0) == [pytest.approx(0.6)]


# ----------------------------------------------------------------------------- run metrics

def test_run_metrics_counts_rates_goodput_and_duration():
    rows = make_rows([("SUCCESS", 0.0, 0.1)] * 6 + [("DUPLICATE", 1.0, 0.1)] * 2 + [("QUEUE_FULL", 1.0, 0.0)] +
                     [("ADMISSION_REJECTED", 2.0, 0.0)] + [("SERVER_ERROR", 2.0, 0.1)] + [("TIMEOUT", 2.0, None)])
    m = ia.run_metrics(rows, [], 10, 5.0)
    assert m["total"] == 12 and m["counts"]["SUCCESS"] == 6
    assert m["duration_s"] == pytest.approx(2.1)                      # last response end (2.1) - first intended arrival (0.0)
    assert m["goodput_per_s"] == pytest.approx(8 / 2.1)               # 6 + 2 definitive answers
    assert m["registrations_per_s"] == pytest.approx(6 / 2.1)
    assert m["rates"]["queue_full"] == m["rates"]["admission_rejected"] == m["rates"]["error"] == m["rates"]["timeout"] == pytest.approx(1 / 12)
    assert m["rates"]["refused_total"] == pytest.approx(2 / 12)


def test_utilization_is_the_mean_and_max_of_the_polled_gauges_and_copes_with_missing_fields():
    polls = [{"t": 0, "depth": 0, "alive": 4, "active": 0, "permits": 2, "in_cs": 0},
             {"t": 1, "depth": 50, "alive": 4, "active": 4, "permits": 2, "in_cs": 2, "adm_limit": 80},
             {"t": 2, "depth": 100, "alive": 4, "active": 2, "permits": 2, "in_cs": 1, "adm_limit": 60}]
    u = ia.utilization(polls, 100)
    assert u["queue"] == {"mean": 0.5, "max": 1.0, "n": 3}
    assert u["workers"]["max"] == 1.0 and u["workers"]["mean"] == pytest.approx(0.5)
    assert u["semaphore"]["mean"] == pytest.approx(0.5)
    assert u["admission_limit"]["n"] == 2 and u["admission_limit"]["mean"] == 70
    assert ia.utilization([], 100) == {"queue": None, "workers": None, "semaphore": None, "admission_limit": None}


def test_fraction_below_max_counts_the_polls_where_admission_was_actually_restricting():
    polls = [{"adm_limit": 200}, {"adm_limit": 200}, {"adm_limit": 150}, {"adm_limit": 120}, {}]
    assert ia.fraction_below_max(polls, 200) == 0.5
    assert ia.fraction_below_max([{}], 200) is None


# ----------------------------------------------------------------------------- recovery time

def scenario(post_burst_latency, normal=0.01, burst_latency=2.0, per_s=20):
    """Arrivals 0-5 s normal, burst 5-8 s slow, then `post_burst_latency(t)` for t >= 8 (20 requests per second)."""
    spec = []
    for t in range(0, 20):
        for k in range(per_s):
            at = t + k / per_s
            if t < 5:
                lat = normal
            elif t < 8:
                lat = burst_latency
            else:
                lat = post_burst_latency(at)
            spec.append(("SUCCESS" if lat is not None else "TIMEOUT", at, lat))
    return make_rows(spec)


def test_recovery_time_is_measured_from_the_end_of_the_burst_to_the_first_run_of_good_seconds():
    rows = scenario(lambda t: 1.0 if t < 11 else 0.01)               # still slow until t=11, normal from 11
    r = ia.recovery_time(rows, burst_start_s=5, burst_end_s=8, schedule_end_s=20, timeout_s=5.0)
    assert r["baseline_p95_s"] == pytest.approx(0.01) and r["target_p95_s"] == pytest.approx(0.035)   # floor beats 1.5 x 0.01
    assert r["recovery_s"] == pytest.approx(3.0)                      # bins 11, 12, 13 are the first three good ones; 11 - 8
    assert r["censored_at_s"] == 12.0


def test_never_recovering_is_reported_as_none_with_the_censoring_point_not_as_a_number():
    rows = scenario(lambda t: 1.0)
    r = ia.recovery_time(rows, 5, 8, 20, 5.0)
    assert r["recovery_s"] is None and r["censored_at_s"] == 12.0


def test_one_good_second_is_not_recovery_it_takes_three_in_a_row():
    rows = scenario(lambda t: 0.01 if int(t) in (10, 12, 14) else 1.0)   # isolated good seconds, never three together
    assert ia.recovery_time(rows, 5, 8, 20, 5.0)["recovery_s"] is None


def test_a_bin_with_too_few_samples_proves_nothing_either_way():
    rows = scenario(lambda t: 0.01, per_s=4)                             # 4 requests/s after the burst: below the minimum of 5
    r = ia.recovery_time(rows, 5, 8, 20, 5.0, warmup_s=0.0)
    assert r["baseline_p95_s"] is None or r["recovery_s"] is None


def test_timeouts_after_the_burst_count_as_bad_seconds():
    rows = scenario(lambda t: None if t < 10 else 0.01)               # timeouts (censored at 5 s) until t=10
    r = ia.recovery_time(rows, 5, 8, 20, 5.0)
    assert r["recovery_s"] == pytest.approx(2.0)                      # bins 10, 11, 12 are the first good three; 10 - 8


def test_no_baseline_means_no_recovery_claim():
    rows = make_rows([("SUCCESS", 0.0, 0.01)] * 3)
    r = ia.recovery_time(rows, burst_start_s=5, burst_end_s=8, schedule_end_s=20, timeout_s=5.0)
    assert r["recovery_s"] is None and "too few" in r["note"]


def test_recovery_cannot_be_negative():
    rows = scenario(lambda t: 0.01)                                   # back to normal the instant the burst ends
    assert ia.recovery_time(rows, 5, 8, 20, 5.0)["recovery_s"] == 0.0


# ----------------------------------------------------------------------------- drain time

def test_drain_time_is_when_the_queue_stays_nearly_empty():
    polls = [{"t": t * 0.25, "depth": d} for t, d in enumerate([0, 150, 180, 120, 60, 9, 3, 2, 1, 1, 1])]
    # depth <= 10 (5% of 200) for three polls in a row first happens at poll index 5 (t=1.25): 1.25 - 0.75
    assert ia.drain_time(polls, 200, burst_end_s=0.75) == pytest.approx(0.5)


def test_a_queue_that_never_drains_has_no_drain_time():
    assert ia.drain_time([{"t": t, "depth": 150} for t in range(10)], 200, 0.0) is None
    assert ia.drain_time([], 200, 0.0) is None


def test_a_brief_dip_is_not_a_drain():
    polls = [{"t": t, "depth": d} for t, d in enumerate([100, 5, 100, 100, 5, 5, 100])]
    assert ia.drain_time(polls, 200, 0.0) is None


# ----------------------------------------------------------------------------- comparing arms

def test_paired_comparison_counts_seeds_where_the_other_arm_was_better_and_gives_a_median_ratio():
    base = {1: 100.0, 2: 200.0, 3: 300.0, 4: 400.0, 5: 500.0}
    other = {1: 50.0, 2: 100.0, 3: 330.0, 4: 200.0, 5: 250.0}
    p = ia.paired(base, other, lower_is_better=True)
    assert p["seeds"] == 5 and p["better_in"] == 4 and p["median_ratio"] == 0.5
    assert ia.paired(base, other, lower_is_better=False)["better_in"] == 1       # direction matters


def test_paired_ignores_seeds_missing_from_one_arm_and_missing_values_and_never_divides_by_zero():
    p = ia.paired({1: 10.0, 2: None, 3: 0.0, 4: 8.0}, {1: 5.0, 2: 1.0, 3: 1.0, 5: 9.0}, lower_is_better=True)
    assert p["seeds"] == 2 and set(p["ratios"]) == {1, 3} and p["ratios"][3] is None and p["median_ratio"] == 0.5


def test_spread_summarises_the_runs_of_one_cell():
    s = ia.spread([3.0, None, 1.0, 2.0])
    assert s == {"n": 3, "mean": 2.0, "min": 1.0, "max": 3.0, "median": 2.0}
    assert ia.spread([None]) is None
