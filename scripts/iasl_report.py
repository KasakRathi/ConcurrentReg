"""Turn a directory of experiment cells into tables and apply the PRE-REGISTERED decision rules mechanically
(docs/iasl/IASL_EXPERIMENTS.md section 5). The rules are code here, written before any evaluation run, so the verdicts cannot be
chosen after seeing the data. Pure functions are unit-tested (tests/test_iasl_experiment_report.py).
"""
import glob
import json
import os

from scripts import iasl_analysis as ia

BASE, DEFAULT, SENSITIVE = "baseline", "iasl_default", "iasl_sensitive"


def load_cells(directory):
    """{(workload, arm, seed): record} for the final (non-superseded) cell files, plus the superseded invalid attempts."""
    cells, invalid = {}, []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        name = os.path.basename(path)
        if name.endswith(".server.log") or name == "calibration.json":
            continue
        record = json.load(open(path))
        if ".invalid_attempt" in name:
            invalid.append(record)
        elif "workload" in record:
            cells[(record["workload"], record["arm"], record["seed"])] = record
    return cells, invalid


def get(record, dotted):
    value = record
    for key in dotted.split("."):
        if value is None:
            return None
        value = value.get(key) if isinstance(value, dict) else None
    return value


def by_seed(cells, workload, arm, dotted, valid_only=True):
    out = {}
    for (w, a, seed), record in cells.items():
        if w == workload and a == arm and (record["valid_open_loop"] or not valid_only):
            out[seed] = get(record, dotted)
    return out


def ms(values):
    return {s: (None if v is None else v * 1000) for s, v in values.items()}


# ----------------------------------------------------------------------------- the pre-registered rules

def decide_h1(p95_pairs):
    """H1 (W4): service-latency p95 lower in >= 4 of 5 seeds AND median ratio <= 0.90."""
    if p95_pairs["seeds"] < 4:
        return "INSUFFICIENT DATA", f"only {p95_pairs['seeds']} valid paired seeds (need at least 4)"
    ok = p95_pairs["better_in"] >= 4 and p95_pairs["median_ratio"] is not None and p95_pairs["median_ratio"] <= 0.90
    return ("SUPPORTED" if ok else "NOT SUPPORTED"), (f"lower in {p95_pairs['better_in']} of {p95_pairs['seeds']} seeds, "
                                                      f"median ratio {p95_pairs['median_ratio']:.2f} (needs >= 4 seeds and <= 0.90)")


def decide_h2(goodput_pairs_by_workload):
    """H2 (W2, W4, W5): median goodput ratio >= 0.90 in each."""
    parts, ok = [], True
    for workload, pairs in goodput_pairs_by_workload.items():
        if pairs["seeds"] < 3 or pairs["median_ratio"] is None:
            return "INSUFFICIENT DATA", f"{workload}: only {pairs['seeds']} valid paired seeds"
        good = pairs["median_ratio"] >= 0.90
        ok &= good
        parts.append(f"{workload} median ratio {pairs['median_ratio']:.2f}{'' if good else ' (below 0.90)'}")
    return ("SUPPORTED" if ok else "NOT SUPPORTED"), "; ".join(parts)


def decide_h3(cells):
    """H3: every run (valid or not, every arm) passes the correctness check, and has no errors beyond refusals."""
    bad = []
    for key, record in cells.items():
        counts = record["metrics"]["counts"]
        errors = sum(counts.get(c, 0) for c in ia.ERRORS) + counts.get("CONNECTION_ERROR", 0)
        if not record["db_check"]["ok"] or errors:
            bad.append((key, record["db_check"], errors))
    if not cells:
        return "INSUFFICIENT DATA", "no runs"
    return ("SUPPORTED" if not bad else "NOT SUPPORTED"), (f"{len(cells)} runs checked; " + ("none failed" if not bad else f"FAILED: {bad[:5]}"))


def decide_h4(w1_rejected_by_seed, p95_pairs, goodput_pairs, restricted_by_seed):
    """H4 (W1): admission refusals < 1% in every seed, median p95 ratio in [0.80, 1.25], median goodput ratio >= 0.95,
    limit below capacity for < 5% of polls."""
    if not w1_rejected_by_seed or p95_pairs["seeds"] < 3:
        return "INSUFFICIENT DATA", "too few valid seeds"
    refused = max(v for v in w1_rejected_by_seed.values() if v is not None)
    restricted = max((v for v in restricted_by_seed.values() if v is not None), default=0.0)
    checks = [(refused < 0.01, f"max admission refusals {100 * refused:.2f}%"),
              (0.80 <= p95_pairs["median_ratio"] <= 1.25, f"median p95 ratio {p95_pairs['median_ratio']:.2f}"),
              (goodput_pairs["median_ratio"] >= 0.95, f"median goodput ratio {goodput_pairs['median_ratio']:.2f}"),
              (restricted < 0.05, f"limit below capacity in up to {100 * restricted:.1f}% of polls")]
    return ("SUPPORTED" if all(c for c, _ in checks) else "NOT SUPPORTED"), "; ".join(t + ("" if c else " (fails)") for c, t in checks)


def decide_h5(p95_pairs, goodput_pairs):
    """H5 (W3): median p95 ratio in [0.80, 1.25] and median goodput ratio >= 0.90."""
    if p95_pairs["seeds"] < 3 or goodput_pairs["seeds"] < 3:
        return "INSUFFICIENT DATA", "too few valid seeds"
    p, g = p95_pairs["median_ratio"], goodput_pairs["median_ratio"]
    ok = 0.80 <= p <= 1.25 and g >= 0.90
    note = "" if ok else (" (a clear latency improvement would be a surprise to report)" if p < 0.80 else "")
    return ("SUPPORTED" if ok else "NOT SUPPORTED"), f"median p95 ratio {p:.2f}, median goodput ratio {g:.2f}{note}"


def classify_recovery(baseline_by_seed, iasl_by_seed):
    """Per seed: both recovered (ratio), only IASL recovered, only baseline recovered, neither. None = not recovered."""
    out = {"both": {}, "iasl_only": [], "baseline_only": [], "neither": []}
    for seed in sorted(set(baseline_by_seed) & set(iasl_by_seed)):
        b, i = baseline_by_seed[seed], iasl_by_seed[seed]
        if b is not None and i is not None:
            out["both"][seed] = (i / b) if b else (1.0 if i == 0 else float("inf"))
        elif i is not None:
            out["iasl_only"].append(seed)
        elif b is not None:
            out["baseline_only"].append(seed)
        else:
            out["neither"].append(seed)
    return out


def decide_h6(classes):
    """H6 (W5): median recovery ratio <= 1.25, and no seed where only the baseline recovered."""
    total = sum(len(v) if isinstance(v, (list, dict)) else 0 for v in classes.values())
    if total < 3:
        return "INSUFFICIENT DATA", f"only {total} valid paired seeds"
    ratios = sorted(classes["both"].values())
    median = ratios[len(ratios) // 2] if ratios else None
    ok = not classes["baseline_only"] and (median is None or median <= 1.25)
    return ("SUPPORTED" if ok else "NOT SUPPORTED"), (
        f"recovered in both: {len(classes['both'])} seeds (median ratio {median if median is None else round(median, 2)}); "
        f"only IASL recovered: {len(classes['iasl_only'])}; only baseline recovered: {len(classes['baseline_only'])}; "
        f"neither: {len(classes['neither'])}")


# ----------------------------------------------------------------------------- report

METRICS = [("goodput /s", "metrics.goodput_per_s", 1, "{:.1f}"), ("registrations /s", "metrics.registrations_per_s", 1, "{:.1f}"),
           ("p50 ms", "metrics.service_latency_s.p50", 1000, "{:.0f}"), ("p95 ms", "metrics.service_latency_s.p95", 1000, "{:.0f}"),
           ("p99 ms", "metrics.service_latency_s.p99", 1000, "{:.0f}"),
           ("queue-full %", "metrics.rates.queue_full", 100, "{:.1f}"), ("admission-refused %", "metrics.rates.admission_rejected", 100, "{:.1f}"),
           ("refused total %", "metrics.rates.refused_total", 100, "{:.1f}"), ("timeout %", "metrics.rates.timeout", 100, "{:.2f}"),
           ("error %", "metrics.rates.error", 100, "{:.2f}"), ("queue util (mean)", "metrics.utilization.queue.mean", 1, "{:.2f}"),
           ("worker util (mean)", "metrics.utilization.workers.mean", 1, "{:.2f}"), ("semaphore util (mean)", "metrics.utilization.semaphore.mean", 1, "{:.2f}"),
           ("time restricted %", "metrics.fraction_time_restricted", 100, "{:.0f}")]


def cell_summary(cells, workload, arm, dotted, scale, fmt):
    values = [v for v in by_seed(cells, workload, arm, dotted).values() if v is not None]
    if not values:
        return "-"
    sp = ia.spread([v * scale for v in values])
    return f"{fmt.format(sp['median'])} ({fmt.format(sp['min'])} to {fmt.format(sp['max'])})"


def compute_verdicts(cells):
    def pairs(workload, dotted, lower, other=DEFAULT):
        return ia.paired(by_seed(cells, workload, BASE, dotted), by_seed(cells, workload, other, dotted), lower)
    verdicts = {}
    verdicts["H1"] = decide_h1(pairs("w4_overload", "metrics.service_latency_s.p95", True))
    verdicts["H2"] = decide_h2({w: pairs(w, "metrics.goodput_per_s", False) for w in ("w2_gradual", "w4_overload", "w5_burst_recovery")})
    verdicts["H3"] = decide_h3(cells)
    verdicts["H4"] = decide_h4(by_seed(cells, "w1_normal", DEFAULT, "metrics.rates.admission_rejected"),
                               pairs("w1_normal", "metrics.service_latency_s.p95", True), pairs("w1_normal", "metrics.goodput_per_s", False),
                               by_seed(cells, "w1_normal", DEFAULT, "metrics.fraction_time_restricted"))
    verdicts["H5"] = decide_h5(pairs("w3_burst", "metrics.service_latency_s.p95", True), pairs("w3_burst", "metrics.goodput_per_s", False))
    verdicts["H6"] = decide_h6(classify_recovery(by_seed(cells, "w5_burst_recovery", BASE, "metrics.recovery.recovery_s"),
                                                 by_seed(cells, "w5_burst_recovery", DEFAULT, "metrics.recovery.recovery_s")))
    return verdicts


HYPOTHESES = {"H1": "under sustained overload IASL lowers the latency of the requests it serves (W4)",
              "H2": "without a material loss of goodput (W2, W4, W5)", "H3": "it never compromises correctness (all runs)",
              "H4": "at normal load it changes nothing material (W1)", "H5": "an instantaneous burst makes no material difference (W3)",
              "H6": "it does not slow recovery after a burst (W5)"}


def render(cells, invalid):
    workloads = sorted({w for w, _, _ in cells}, key=lambda w: w)
    arms = [a for a in (BASE, DEFAULT, SENSITIVE) if any(k[1] == a for k in cells)]
    lines = ["## Results tables", "", "Each cell: **median** (min to max) over the valid seeds. Latency = service-latency set, "
             "intended-arrival basis (docs/iasl/IASL_EXPERIMENTS.md section 4).", ""]
    for workload in workloads:
        lines += [f"### {workload}", "", "| metric | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
        valid_counts = {a: sum(1 for (w, aa, _), r in cells.items() if w == workload and aa == a and r["valid_open_loop"]) for a in arms}
        total_counts = {a: sum(1 for (w, aa, _) in cells if w == workload and aa == a) for a in arms}
        lines.append("| valid runs | " + " | ".join(f"{valid_counts[a]} of {total_counts[a]}" for a in arms) + " |")
        for label, dotted, scale, fmt in METRICS:
            row = [cell_summary(cells, workload, a, dotted, scale, fmt) for a in arms]
            if any(c != "-" for c in row):
                lines.append(f"| {label} | " + " | ".join(row) + " |")
        if workload == "w5_burst_recovery":
            for label, dotted in (("recovery time s", "metrics.recovery.recovery_s"), ("queue drain time s", "metrics.drain_time_s")):
                row = []
                for a in arms:
                    vals = by_seed(cells, workload, a, dotted)
                    got = [v for v in vals.values() if v is not None]
                    row.append(f"{ia.spread(got)['median']:.1f} ({min(got):.1f} to {max(got):.1f}); not recovered {len(vals) - len(got)} of {len(vals)}" if got
                               else f"not recovered in {len(vals)} of {len(vals)}")
                lines.append(f"| {label} | " + " | ".join(row) + " |")
        lines.append("")
    verdicts = compute_verdicts(cells)
    lines += ["## Verdicts on the pre-registered hypotheses", "", "| id | hypothesis | verdict | evidence |", "|---|---|---|---|"]
    for key in ("H1", "H2", "H3", "H4", "H5", "H6"):
        verdict, why = verdicts[key]
        lines.append(f"| {key} | {HYPOTHESES[key]} | **{verdict}** | {why} |")
    lines += ["", "## Invalid attempts (instrument rule) that were re-run", ""]
    if invalid:
        for r in invalid:
            lines.append(f"* {r['workload']} / {r['arm']} / seed {r['seed']} attempt {r['attempt']}: {'; '.join(r['invalid_reasons'])} (load before: {r['load_before']})")
    else:
        lines.append("None.")
    final_invalid = [k for k, r in cells.items() if not r["valid_open_loop"]]
    lines += ["", "## Cells still invalid after the allowed attempts (excluded from performance comparisons)", ""]
    lines += [f"* {k}: {'; '.join(cells[k]['invalid_reasons'])}" for k in final_invalid] or ["None."]
    return "\n".join(lines), verdicts


def main(directory, out=None):
    cells, invalid = load_cells(directory)
    text, verdicts = render(cells, invalid)
    out = out or os.path.join(directory, "report.md")
    with open(out, "w") as handle:
        handle.write(text + "\n")
    with open(os.path.splitext(out)[0] + ".json", "w") as handle:
        json.dump({"verdicts": verdicts, "cells": len(cells), "invalid_attempts": len(invalid)}, handle, indent=1)
    print(text)
    print(f"\n[report] wrote {out}")
