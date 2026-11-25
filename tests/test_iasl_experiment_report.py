"""The pre-registered decision rules (scripts/iasl_report.py), checked at their boundaries on synthetic results."""
import json

import pytest

from scripts import iasl_analysis as ia
from scripts import iasl_report as rep


def pairs(ratios, lower=True):
    base = {i: 100.0 for i in range(len(ratios))}
    other = {i: 100.0 * r for i, r in enumerate(ratios)}
    return ia.paired(base, other, lower)


# ----------------------------------------------------------------------------- H1 and H2

def test_h1_needs_four_of_five_seeds_better_and_a_median_ratio_of_at_most_point_nine():
    assert rep.decide_h1(pairs([0.5, 0.6, 0.7, 0.8, 0.85]))[0] == "SUPPORTED"
    assert rep.decide_h1(pairs([0.5, 0.6, 0.7, 0.8, 1.2]))[0] == "SUPPORTED"          # 4 of 5 is enough
    assert rep.decide_h1(pairs([0.5, 0.6, 0.7, 1.1, 1.2]))[0] == "NOT SUPPORTED"      # only 3 of 5
    assert rep.decide_h1(pairs([0.95, 0.96, 0.97, 0.98, 0.99]))[0] == "NOT SUPPORTED"  # better every time but median 0.97 > 0.90
    assert rep.decide_h1(pairs([0.90, 0.90, 0.90, 0.90, 0.90]))[0] == "SUPPORTED"      # exactly 0.90 counts
    assert rep.decide_h1(pairs([0.5, 0.5, 0.5]))[0] == "INSUFFICIENT DATA"             # fewer than 4 valid pairs


def test_h2_needs_the_median_goodput_ratio_at_least_point_nine_in_every_workload():
    ok = {"w2": pairs([0.95] * 5, False), "w4": pairs([1.0] * 5, False), "w5": pairs([0.9] * 5, False)}
    assert rep.decide_h2(ok)[0] == "SUPPORTED"
    bad = dict(ok, w4=pairs([0.85] * 5, False))
    verdict, why = rep.decide_h2(bad)
    assert verdict == "NOT SUPPORTED" and "w4" in why and "below 0.90" in why
    assert rep.decide_h2({"w2": pairs([1.0, 1.0], False)})[0] == "INSUFFICIENT DATA"


# ----------------------------------------------------------------------------- H3 correctness

def fake_cell(workload="w1", arm="baseline", seed=1, valid=True, ok=True, counts=None, **extra):
    record = {"workload": workload, "arm": arm, "seed": seed, "valid_open_loop": valid, "invalid_reasons": [], "attempt": 1,
              "load_before": 1.0, "db_check": {"ok": ok}, "metrics": {"counts": counts or {"SUCCESS": 10}, "rates": {}, "utilization": {}}}
    record.update(extra)
    return (workload, arm, seed), record


def test_h3_fails_on_any_correctness_failure_or_error_in_any_run_even_an_invalid_one():
    good = dict([fake_cell(seed=1), fake_cell(seed=2, arm="iasl_default")])
    assert rep.decide_h3(good)[0] == "SUPPORTED"
    assert rep.decide_h3({**good, **dict([fake_cell(seed=3, ok=False)])})[0] == "NOT SUPPORTED"
    assert rep.decide_h3({**good, **dict([fake_cell(seed=3, valid=False, counts={"SUCCESS": 5, "SERVER_ERROR": 1})])})[0] == "NOT SUPPORTED"
    assert rep.decide_h3({**good, **dict([fake_cell(seed=3, counts={"CONNECTION_ERROR": 1})])})[0] == "NOT SUPPORTED"
    assert rep.decide_h3({**good, **dict([fake_cell(seed=3, counts={"SUCCESS": 5, "ADMISSION_REJECTED": 5, "QUEUE_FULL": 2, "TIMEOUT": 1})])})[0] == "SUPPORTED"
    assert rep.decide_h3({})[0] == "INSUFFICIENT DATA"


# ----------------------------------------------------------------------------- H4 and H5

def test_h4_every_condition_must_hold_at_normal_load():
    ok = rep.decide_h4({1: 0.0, 2: 0.002}, pairs([1.0, 1.1, 0.9]), pairs([1.0, 1.0, 0.98], False), {1: 0.0, 2: 0.01})
    assert ok[0] == "SUPPORTED"
    assert rep.decide_h4({1: 0.0, 2: 0.011}, pairs([1.0] * 3), pairs([1.0] * 3, False), {1: 0.0})[0] == "NOT SUPPORTED"     # >= 1% refused
    assert rep.decide_h4({1: 0.0}, pairs([1.4] * 3), pairs([1.0] * 3, False), {1: 0.0})[0] == "NOT SUPPORTED"                  # p95 out of band
    assert rep.decide_h4({1: 0.0}, pairs([0.7] * 3), pairs([1.0] * 3, False), {1: 0.0})[0] == "NOT SUPPORTED"                  # also if far better
    assert rep.decide_h4({1: 0.0}, pairs([1.0] * 3), pairs([0.9] * 3, False), {1: 0.0})[0] == "NOT SUPPORTED"                  # goodput < 0.95
    assert rep.decide_h4({1: 0.0}, pairs([1.0] * 3), pairs([1.0] * 3, False), {1: 0.06})[0] == "NOT SUPPORTED"                 # restricted >= 5%
    assert rep.decide_h4({}, pairs([1.0] * 3), pairs([1.0] * 3, False), {})[0] == "INSUFFICIENT DATA"


def test_h5_a_burst_is_supported_only_if_nothing_material_changed_and_a_surprise_is_flagged():
    assert rep.decide_h5(pairs([1.0, 1.1, 0.95]), pairs([1.0] * 3, False))[0] == "SUPPORTED"
    verdict, why = rep.decide_h5(pairs([0.5] * 3), pairs([1.0] * 3, False))
    assert verdict == "NOT SUPPORTED" and "surprise" in why
    assert rep.decide_h5(pairs([1.0] * 3), pairs([0.8] * 3, False))[0] == "NOT SUPPORTED"
    assert rep.decide_h5(pairs([1.0]), pairs([1.0], False))[0] == "INSUFFICIENT DATA"


# ----------------------------------------------------------------------------- H6

def test_recovery_classification_never_hides_a_run_that_did_not_recover():
    c = rep.classify_recovery({1: 4.0, 2: 6.0, 3: None, 4: 5.0, 5: None}, {1: 2.0, 2: None, 3: 3.0, 4: 5.0, 5: None})
    assert c["both"] == {1: 0.5, 4: 1.0} and c["baseline_only"] == [2] and c["iasl_only"] == [3] and c["neither"] == [5]
    assert rep.classify_recovery({1: 0.0}, {1: 0.0})["both"] == {1: 1.0}                 # both instant: no division by zero
    assert rep.classify_recovery({1: 0.0}, {1: 2.0})["both"][1] == float("inf")


def test_h6_fails_if_only_the_baseline_ever_recovered_or_if_recovery_is_clearly_slower():
    same = rep.classify_recovery({1: 4.0, 2: 4.0, 3: 4.0}, {1: 4.0, 2: 4.4, 3: 3.0})
    assert rep.decide_h6(same)[0] == "SUPPORTED"
    slower = rep.classify_recovery({1: 4.0, 2: 4.0, 3: 4.0}, {1: 8.0, 2: 8.0, 3: 8.0})
    assert rep.decide_h6(slower)[0] == "NOT SUPPORTED"
    worse = rep.classify_recovery({1: 4.0, 2: 4.0, 3: 4.0, 4: 4.0}, {1: 4.0, 2: 4.0, 3: 4.0, 4: None})
    verdict, why = rep.decide_h6(worse)
    assert verdict == "NOT SUPPORTED" and "only baseline recovered: 1" in why
    assert rep.decide_h6(rep.classify_recovery({1: 4.0}, {1: 4.0}))[0] == "INSUFFICIENT DATA"
    better = rep.classify_recovery({1: None, 2: None, 3: None}, {1: 5.0, 2: 5.0, 3: 5.0})
    assert rep.decide_h6(better)[0] == "SUPPORTED"                                         # IASL recovering where the baseline did not


# ----------------------------------------------------------------------------- loading and rendering

def test_loading_separates_final_cells_from_superseded_invalid_attempts(tmp_path):
    (tmp_path / "w1__baseline__seed1.json").write_text(json.dumps(fake_cell()[1]))
    attempt = fake_cell(valid=False)[1]
    attempt["attempt"] = 1
    (tmp_path / "w1__baseline__seed1.invalid_attempt1.json").write_text(json.dumps(attempt))
    (tmp_path / "w1__baseline__seed1.server.log").write_text("not json")
    (tmp_path / "report.json").write_text(json.dumps({"verdicts": {}}))
    cells, invalid = rep.load_cells(str(tmp_path))
    assert list(cells) == [("w1", "baseline", 1)] and len(invalid) == 1 and invalid[0]["valid_open_loop"] is False


def test_rendering_a_set_of_results_gives_tables_verdicts_and_the_invalid_attempt_list():
    def cell(workload, arm, seed, p95, goodput, valid=True, recovery=None, rejected=0.0):
        key, record = fake_cell(workload, arm, seed, valid)
        record["metrics"].update({"goodput_per_s": goodput, "service_latency_s": {"p50": p95 / 2, "p95": p95, "p99": p95 * 1.2},
                                  "rates": {"admission_rejected": rejected, "queue_full": 0.0, "refused_total": rejected, "timeout": 0.0, "error": 0.0},
                                  "recovery": {"recovery_s": recovery}, "drain_time_s": 1.0})
        return key, record
    cells = {}
    for seed in range(1, 6):
        for workload in ("w1_normal", "w2_gradual", "w3_burst", "w4_overload", "w5_burst_recovery"):
            cells.update([cell(workload, "baseline", seed, 1.0, 300.0, recovery=5.0)])
            cells.update([cell(workload, "iasl_default", seed, 0.6, 290.0, recovery=4.0, rejected=0.1 if workload != "w1_normal" else 0.0)])
    text, verdicts = rep.render(cells, [{"workload": "w4_overload", "arm": "baseline", "seed": 2, "attempt": 1,
                                         "invalid_reasons": ["12 requests were sent more than 250 ms after their intended arrival"],
                                         "load_before": 9.1}])
    assert verdicts["H1"][0] == "SUPPORTED" and verdicts["H3"][0] == "SUPPORTED" and verdicts["H6"][0] == "SUPPORTED"
    for needle in ("### w4_overload", "| p95 ms |", "Verdicts on the pre-registered hypotheses", "**SUPPORTED**", "attempt 1", "12 requests were sent"):
        assert needle in text
