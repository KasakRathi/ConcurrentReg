"""Pure analysis for the IASL experiments: no I/O, no environment, no database. Everything here is unit-tested
(tests/test_iasl_experiment_analysis.py) because the experimental claims rest on it.

A request row is: [seq, section_id, category, http_status, intended_s, sent_s, end_s] (seconds since the run began).

Definitions (fixed before any evaluation run; see docs/iasl/IASL_EXPERIMENTS.md):
  definitive answer   category SUCCESS, DUPLICATE or COURSE_FULL: the database decided the request.
  service-latency set definitive answers PLUS client TIMEOUTs counted at the timeout value. A timeout is a
                      lower bound on a latency that was too slow to observe, so leaving it out would let a slow
                      system look faster. Requests refused up front (queue full / admission) are NOT in this set;
                      they are reported as rejection rates instead, so refusing work can never masquerade as speed.
  latency             end - INTENDED arrival (the delay a user would feel, including any generator lateness).
  goodput             definitive answers per second over the whole run (first intended arrival to last response).
"""
import math

DEFINITIVE = ("SUCCESS", "DUPLICATE", "COURSE_FULL")
ERRORS = ("SERVER_ERROR", "CLIENT_ERROR", "UNKNOWN")
REFUSALS = ("QUEUE_FULL", "ADMISSION_REJECTED")
SEQ, SECTION, CATEGORY, STATUS, INTENDED, SENT, END = range(7)

RECOVERY_FACTOR = 1.5          # recovered when p95 <= max(1.5 x baseline p95, baseline + FLOOR)
RECOVERY_FLOOR_S = 0.025       # keeps a near-zero baseline from making the target unreachable
RECOVERY_BINS = 3              # this many consecutive recovered one-second bins
RECOVERY_MIN_SAMPLES = 5       # a bin with fewer service-latency samples says nothing either way
DRAIN_FRACTION = 0.05          # queue "drained" at or below this fraction of capacity ...
DRAIN_POLLS = 3                # ... for this many consecutive polls


def percentile(sorted_values, percent):
    """Nearest-rank percentile (the same rule the workload generator and IASL use)."""
    rank = math.ceil(percent / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


def stats(values):
    values = sorted(values)
    if not values:
        return None
    return {"n": len(values), "mean": sum(values) / len(values), "p50": percentile(values, 50),
            "p95": percentile(values, 95), "p99": percentile(values, 99), "max": values[-1]}


def compact_rows(results):
    """Reduce the generator's per-request records to the few fields the analysis needs."""
    return [[r["sequence"], r["section_id"], r["category"], r["http_status"], r.get("intended_offset_s"),
             r.get("sent_offset_s"), r.get("end_offset_s")] for r in results]


def service_latencies_s(rows, timeout_s):
    """Latencies (seconds) of the service-latency set: definitive answers, plus timeouts at the timeout value."""
    out = []
    for row in rows:
        if row[CATEGORY] in DEFINITIVE:
            out.append(row[END] - row[INTENDED])
        elif row[CATEGORY] == "TIMEOUT":
            out.append(float(timeout_s))
    return out


def run_metrics(rows, polls, queue_capacity, timeout_s):
    """Everything measured about one run, from the client's rows and the server polls."""
    total = len(rows)
    counts = {}
    for row in rows:
        counts[row[CATEGORY]] = counts.get(row[CATEGORY], 0) + 1
    definitive = sum(counts.get(c, 0) for c in DEFINITIVE)
    ends = [r[END] for r in rows if r[END] is not None]
    starts = [r[INTENDED] for r in rows if r[INTENDED] is not None]
    duration = (max(ends) - min(starts)) if ends and starts else None
    answered = [r[END] - r[INTENDED] for r in rows if r[STATUS] is not None and r[END] is not None]
    metrics = {
        "total": total, "counts": counts, "duration_s": duration,
        "goodput_per_s": definitive / duration if duration else None,
        "registrations_per_s": counts.get("SUCCESS", 0) / duration if duration else None,
        "service_latency_s": stats(service_latencies_s(rows, timeout_s)),
        "all_answered_latency_s": stats(answered),       # includes instant refusals: shown for transparency, NOT a headline
        "rates": {
            "queue_full": counts.get("QUEUE_FULL", 0) / total if total else None,
            "admission_rejected": counts.get("ADMISSION_REJECTED", 0) / total if total else None,
            "refused_total": sum(counts.get(c, 0) for c in REFUSALS) / total if total else None,
            "error": sum(counts.get(c, 0) for c in ERRORS) / total if total else None,
            "timeout": counts.get("TIMEOUT", 0) / total if total else None,
            "connection_error": counts.get("CONNECTION_ERROR", 0) / total if total else None,
        },
        "utilization": utilization(polls, queue_capacity),
    }
    return metrics


def utilization(polls, queue_capacity):
    """Mean and maximum of queue, worker and semaphore utilisation over the server polls (instantaneous gauges)."""
    def series(fn):
        values = [v for v in (fn(p) for p in polls) if v is not None]
        return {"mean": sum(values) / len(values), "max": max(values), "n": len(values)} if values else None
    return {
        "queue": series(lambda p: p["depth"] / queue_capacity if queue_capacity else None),
        "workers": series(lambda p: p["active"] / p["alive"] if p.get("alive") else None),
        "semaphore": series(lambda p: p["in_cs"] / p["permits"] if p.get("permits") else None),
        "admission_limit": series(lambda p: p.get("adm_limit")),
    }


def recovery_time(rows, burst_start_s, burst_end_s, schedule_end_s, timeout_s, warmup_s=1.0):
    """Seconds from the end of a burst until latency is back to normal; None if it never recovered inside the schedule.

    Baseline = p95 of the service-latency set of requests that arrived before the burst (after `warmup_s`).
    Recovered = for RECOVERY_BINS consecutive one-second bins (by intended arrival), each with at least
    RECOVERY_MIN_SAMPLES samples, p95 <= max(RECOVERY_FACTOR x baseline, baseline + RECOVERY_FLOOR_S).
    Returns {"baseline_p95_s", "target_p95_s", "recovery_s" (None = not recovered), "censored_at_s", "bins"}.
    """
    before = [r for r in rows if warmup_s <= r[INTENDED] < burst_start_s]
    baseline_set = service_latencies_s(before, timeout_s)
    if len(baseline_set) < RECOVERY_MIN_SAMPLES:
        return {"baseline_p95_s": None, "target_p95_s": None, "recovery_s": None, "censored_at_s": None, "bins": [],
                "note": "too few pre-burst samples to set a baseline"}
    baseline = percentile(sorted(baseline_set), 95)
    target = max(RECOVERY_FACTOR * baseline, baseline + RECOVERY_FLOOR_S)
    first_bin, last_bin = math.ceil(burst_end_s), int(schedule_end_s)
    bins = []
    for b in range(first_bin, last_bin):
        samples = service_latencies_s([r for r in rows if b <= r[INTENDED] < b + 1], timeout_s)
        p95 = percentile(sorted(samples), 95) if len(samples) >= RECOVERY_MIN_SAMPLES else None
        bins.append({"t": b, "n": len(samples), "p95_s": p95, "ok": p95 is not None and p95 <= target})
    recovery = None
    for i in range(len(bins) - RECOVERY_BINS + 1):
        if all(x["ok"] for x in bins[i:i + RECOVERY_BINS]):
            recovery = max(0.0, bins[i]["t"] - burst_end_s)
            break
    return {"baseline_p95_s": baseline, "target_p95_s": target, "recovery_s": recovery,
            "censored_at_s": max(0.0, schedule_end_s - burst_end_s), "bins": bins}


def drain_time(polls, queue_capacity, burst_end_s):
    """Seconds after the burst ends until the queue stays at/below DRAIN_FRACTION of capacity for DRAIN_POLLS polls."""
    limit = DRAIN_FRACTION * queue_capacity
    after = [p for p in polls if p["t"] >= burst_end_s]
    for i in range(len(after) - DRAIN_POLLS + 1):
        if all(p["depth"] <= limit for p in after[i:i + DRAIN_POLLS]):
            return max(0.0, after[i]["t"] - burst_end_s)
    return None


def fraction_below_max(polls, capacity):
    """Share of polls during which the admission limit was below the queue capacity (IASL actually restricting)."""
    values = [p["adm_limit"] for p in polls if p.get("adm_limit") is not None]
    return sum(1 for v in values if v < capacity) / len(values) if values else None


# ----------------------------------------------------------------------------- comparing arms

def spread(values):
    values = [v for v in values if v is not None]
    return {"n": len(values), "mean": sum(values) / len(values), "min": min(values), "max": max(values),
            "median": sorted(values)[len(values) // 2]} if values else None


def paired(baseline_by_seed, other_by_seed, lower_is_better):
    """Seed-by-seed comparison of one metric. Only seeds present in both arms (and not None) are used.

    Returns the per-seed ratio other/baseline, how many seeds the other arm was better in, and the median ratio.
    A ratio below 1 is an improvement when lower is better and a deterioration when higher is better.
    """
    pairs = [(s, baseline_by_seed[s], other_by_seed[s]) for s in sorted(baseline_by_seed)
             if s in other_by_seed and baseline_by_seed[s] is not None and other_by_seed[s] is not None]
    ratios = {s: (o / b if b else None) for s, b, o in pairs}
    better = sum(1 for s, b, o in pairs if (o < b if lower_is_better else o > b))
    usable = sorted(r for r in ratios.values() if r is not None)
    return {"seeds": len(pairs), "better_in": better, "ratios": ratios,
            "median_ratio": usable[len(usable) // 2] if usable else None}
