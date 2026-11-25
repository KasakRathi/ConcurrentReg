"""Client-side workload generator for ConcurrentReg (an experimental instrument).

It sends HTTP requests to POST /registrations and records what happened.
It never touches the database and contains no registration, seat or admission logic.
The thread pool here only creates concurrent *client* traffic; it is not the
server-side worker pool.

Two arrival models:
  open    every request has an intended arrival time fixed in advance; responses never
          change that schedule. If the generator cannot keep to it, that is measured
          (lateness) and the run is flagged invalid for open-loop evaluation.
  closed  N virtual users; each thinks, sends, waits for the response, then repeats.

Run:  python -m workload.workload_generator --help
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import httpx

GENERATOR_VERSION = "2.0"   # 2.0: open/closed arrival models, lateness and validity reporting, phases

ARRIVAL_MODELS = ("open", "closed")
PATTERNS = ("steady", "burst", "ramp", "phases")
CONTENTIONS = ("hot", "independent", "mixed")
MAX_REQUESTS = 10_000        # safety cap against accidental huge runs
MAX_IN_FLIGHT = 1_000        # one thread and one connection per in-flight request
MAX_VIRTUAL_USERS = 1_000    # one thread per virtual user
MAX_PHASES = 50
MIN_SAMPLES_P95 = 20         # percentiles are only reported when the sample is big enough
MIN_SAMPLES_P99 = 100

# Result categories
SUCCESS = "SUCCESS"
DUPLICATE = "DUPLICATE"
COURSE_FULL = "COURSE_FULL"
QUEUE_FULL = "QUEUE_FULL"   # the server's bounded queue turned the request away (Day 3)
ADMISSION_REJECTED = "ADMISSION_REJECTED"   # IASL's admission control turned it away before the queue (distinct from QUEUE_FULL)
CLIENT_ERROR = "CLIENT_ERROR"
SERVER_ERROR = "SERVER_ERROR"
TIMEOUT = "TIMEOUT"
CONNECTION_ERROR = "CONNECTION_ERROR"
UNKNOWN = "UNKNOWN"
NOT_DISPATCHED = "NOT_DISPATCHED"   # the run was stopped before this request was ever sent
ALL_CATEGORIES = (SUCCESS, DUPLICATE, COURSE_FULL, QUEUE_FULL, ADMISSION_REJECTED, CLIENT_ERROR,
                  SERVER_ERROR, TIMEOUT, CONNECTION_ERROR, UNKNOWN, NOT_DISPATCHED)

# The Day 1 API contract: (HTTP status, message) -> category.
# Anything not listed here is NOT treated as a known outcome.
KNOWN_RESPONSES = {
    (201, "Registration successful"): SUCCESS,
    (409, "Student is already registered for this course section"): DUPLICATE,
    (409, "Course section is full"): COURSE_FULL,
    (503, "Request queue is full"): QUEUE_FULL,   # provisional status; see README "Unresolved decisions"
    (503, "Request rejected by admission control"): ADMISSION_REJECTED,   # only with IASL's admission control on
}


class ConfigError(Exception):
    pass


@dataclass
class WorkloadConfig:
    # All values below are demonstration defaults, not research parameters.
    base_url: str = "http://127.0.0.1:8000"
    endpoint: str = "/registrations"
    request_count: int = 20
    concurrency: int = 100            # open loop: max requests in flight (1 thread + 1 connection each)
    arrival_model: str = "open"       # "open" (scheduled arrivals) or "closed" (virtual users)
    pattern: str = "burst"            # open loop timing: steady, burst, ramp or phases
    contention: str = "hot"           # which sections are targeted
    student_count: int = 10           # students STU001..STUnnn must exist (Day 1 seed naming)
    section_ids: list = field(default_factory=lambda: [1, 2])
    hot_section_count: int = 1        # the first N of section_ids are "hot"
    hot_fraction: float = 0.5         # share of hot requests when contention="mixed"
    duplicate_fraction: float = 0.0   # share of requests that repeat an earlier (student, section)
    rate: float = 10.0                # requests/second for steady; final-stage rate for ramp
    ramp_stages: int = 3
    phases: list = field(default_factory=list)   # pattern="phases": [[rate_per_s, duration_s], ...]
    lateness_tolerance_ms: float = 50.0          # open loop: dispatch later than this makes a run invalid
    virtual_users: int = 10                      # closed loop: number of virtual users
    think_time_min_s: float = 0.0                # closed loop: think time before each request,
    think_time_max_s: float = 0.0                #   uniform in [min, max]; equal values = fixed
    seed: int = 42
    timeout_seconds: float = 5.0
    output_dir: str = "results"


@dataclass
class Request:
    request_id: str
    sequence: int
    student_id: str
    section_id: int
    planned_offset_s: float   # intended arrival, seconds after the experiment starts (None in closed loop)
    user: int = None                  # closed loop: which virtual user sends this request
    think_time_before_s: float = None  # closed loop: that user's think time before sending it


# ---------------------------------------------------------------- configuration

def validate_config(config):
    if not config.base_url.startswith(("http://", "https://")):
        raise ConfigError("base_url must start with http:// or https://")
    if not config.endpoint.startswith("/"):
        raise ConfigError("endpoint must start with /")
    if config.arrival_model not in ARRIVAL_MODELS:
        raise ConfigError(f"arrival_model must be one of {ARRIVAL_MODELS}")
    if config.pattern not in PATTERNS:
        raise ConfigError(f"pattern must be one of {PATTERNS}")
    if config.pattern == "phases":
        if config.arrival_model == "closed":
            raise ConfigError("phases describe scheduled arrivals, so they need arrival_model=open")
        validate_phases(config.phases)
        if not 1 <= planned_request_count(config) <= MAX_REQUESTS:
            raise ConfigError(f"the phases must produce between 1 and {MAX_REQUESTS} requests")
    elif not 1 <= config.request_count <= MAX_REQUESTS:
        raise ConfigError(f"request_count must be between 1 and {MAX_REQUESTS}")
    if not 1 <= config.concurrency <= MAX_IN_FLIGHT:
        raise ConfigError(f"concurrency (the in-flight cap) must be between 1 and {MAX_IN_FLIGHT}")
    if isinstance(config.seed, bool) or not isinstance(config.seed, int) or config.seed < 0:
        raise ConfigError("seed must be a non-negative whole number")
    if config.lateness_tolerance_ms < 0:
        raise ConfigError("lateness_tolerance_ms must not be negative")
    if config.arrival_model == "closed":
        if not 1 <= config.virtual_users <= MAX_VIRTUAL_USERS:
            raise ConfigError(f"virtual_users must be between 1 and {MAX_VIRTUAL_USERS}")
        if not 0 <= config.think_time_min_s <= config.think_time_max_s:
            raise ConfigError("think times must satisfy 0 <= think_time_min_s <= think_time_max_s")
    if config.contention not in CONTENTIONS:
        raise ConfigError(f"contention must be one of {CONTENTIONS}")
    if config.student_count < 1:
        raise ConfigError("student_count must be at least 1")
    if not config.section_ids or len(set(config.section_ids)) != len(config.section_ids):
        raise ConfigError("section_ids must be a non-empty list without repeats")
    if not 1 <= config.hot_section_count <= len(config.section_ids):
        raise ConfigError("hot_section_count must be between 1 and the number of sections")
    if config.contention == "mixed" and config.hot_section_count == len(config.section_ids):
        raise ConfigError("mixed contention needs at least one non-hot section")
    if not 0 <= config.hot_fraction <= 1 or not 0 <= config.duplicate_fraction <= 1:
        raise ConfigError("hot_fraction and duplicate_fraction must be between 0 and 1")
    if config.arrival_model == "open" and config.pattern in ("steady", "ramp") and config.rate <= 0:
        raise ConfigError("rate must be greater than 0 for steady and ramp patterns")
    if config.ramp_stages < 1:
        raise ConfigError("ramp_stages must be at least 1")
    if config.timeout_seconds <= 0:
        raise ConfigError("timeout_seconds must be greater than 0")


def validate_phases(phases):
    if not phases or len(phases) > MAX_PHASES:
        raise ConfigError(f"phases must hold between 1 and {MAX_PHASES} [rate, duration] pairs")
    for phase in phases:
        if not isinstance(phase, (list, tuple)) or len(phase) != 2:
            raise ConfigError("each phase must be a [rate_per_s, duration_s] pair")
        rate, duration = phase
        if isinstance(rate, bool) or isinstance(duration, bool) or not isinstance(rate, (int, float)) \
                or not isinstance(duration, (int, float)):
            raise ConfigError("phase rate and duration must be numbers")
        if not (math.isfinite(rate) and math.isfinite(duration)) or rate <= 0 or duration <= 0:
            raise ConfigError("phase rate and duration must be finite and greater than 0")


# ------------------------------------------------------------ request generation
# Everything in this section is deterministic for a given config (seed included).

def phase_plan(config):
    """Break a phases schedule into explicit phases.

    Phase i covers the half-open interval [start_s, end_s): its arrivals are at
    start_s + k/rate for k = 0 .. requests-1, so none falls on end_s, and the next
    phase starts exactly at end_s. requests = ceil(rate * duration).
    """
    plan = []
    start = 0.0
    for index, (rate, duration) in enumerate(config.phases):
        requests = math.ceil(rate * duration - 1e-9)
        plan.append({"index": index, "rate_per_s": rate, "duration_s": duration,
                     "start_s": start, "end_s": start + duration, "requests": requests})
        start += duration
    return plan


def planned_request_count(config):
    """How many requests the run will send (derived from the phases when pattern="phases")."""
    if config.pattern == "phases":
        return sum(phase["requests"] for phase in phase_plan(config))
    return config.request_count


def arrival_offsets(config):
    """Intended arrival time of each request, in seconds after the experiment starts."""
    count = config.request_count
    if config.pattern == "phases":
        return [phase["start_s"] + k / phase["rate_per_s"]
                for phase in phase_plan(config) for k in range(phase["requests"])]
    if config.pattern == "burst":
        return [0.0] * count
    if config.pattern == "steady":
        return [index / config.rate for index in range(count)]

    # ramp: the rate grows in equal steps; the last stage runs at config.rate.
    offsets = []
    time_so_far = 0.0
    for index in range(count):
        stage = index * config.ramp_stages // count          # 0 .. ramp_stages-1
        stage_rate = config.rate * (stage + 1) / config.ramp_stages
        offsets.append(time_so_far)
        time_so_far += 1 / stage_rate
    return offsets


def pick_section(rng, config):
    hot = config.section_ids[:config.hot_section_count]
    cold = config.section_ids[config.hot_section_count:]
    if config.contention == "hot":
        return rng.choice(hot)
    if config.contention == "independent":
        return rng.choice(config.section_ids)
    return rng.choice(hot) if rng.random() < config.hot_fraction else rng.choice(cold)


def pick_student(rng, students, section_id, used_pairs):
    # Prefer a student who has not yet asked for this section, so repeats only
    # happen on purpose (duplicate_fraction) or when every student already asked.
    unused = [s for s in students if (s, section_id) not in used_pairs]
    return rng.choice(unused if unused else students)


def plan_think_times(config, count):
    """One think time per request (closed loop), from their own seeded random stream.

    A separate stream means switching the think-time settings never changes which
    students and sections are requested for a given seed.
    """
    rng = random.Random(f"think-times-{config.seed}")
    return [rng.uniform(config.think_time_min_s, config.think_time_max_s) for _ in range(count)]


def generate_requests(config):
    rng = random.Random(config.seed)   # private generator: never touches global random state
    students = [f"STU{number:03d}" for number in range(1, config.student_count + 1)]
    count = planned_request_count(config)
    closed = config.arrival_model == "closed"
    offsets = [None] * count if closed else arrival_offsets(config)
    think_times = plan_think_times(config, count) if closed else [None] * count
    requests = []
    used_pairs = set()

    for index in range(count):
        if requests and rng.random() < config.duplicate_fraction:
            earlier = rng.choice(requests)
            student_id, section_id = earlier.student_id, earlier.section_id
        else:
            section_id = pick_section(rng, config)
            student_id = pick_student(rng, students, section_id, used_pairs)
        used_pairs.add((student_id, section_id))
        user = index % config.virtual_users if closed else None   # requests are dealt to users in turn
        requests.append(Request(f"req-{index:05d}", index, student_id, section_id, offsets[index],
                                user, think_times[index]))
    return requests


# ------------------------------------------------------------------ execution

def classify_response(status_code, body):
    """Map an HTTP response to a result category. Unrecognised answers are never SUCCESS."""
    message = body.get("message") if isinstance(body, dict) else None
    known = KNOWN_RESPONSES.get((status_code, message))
    if known:
        return known
    if status_code >= 500:
        return SERVER_ERROR
    if 400 <= status_code < 500 and status_code != 409:
        return CLIENT_ERROR
    return UNKNOWN


def send_request(client, endpoint, request, experiment_start):
    """Send one request and return its result record. Never raises.

    All durations come from time.perf_counter() (monotonic), so a change of the system clock
    cannot distort them. Wall-clock strings (intended_at, sent_at) are for reading only.
    """
    intended = request.planned_offset_s       # None in closed loop: there is no intended arrival
    if intended is not None:
        # Normally the dispatcher has already waited. This guarantees we never send EARLY.
        delay = experiment_start + intended - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

    sent_wall = datetime.now()
    start = time.perf_counter()                # the moment of sending
    status_code = None
    category = None
    detail = None
    try:
        response = client.post(endpoint, json={
            "student_id": request.student_id,
            "section_id": request.section_id,
        })
        status_code = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        category = classify_response(status_code, body)
        if category not in (SUCCESS, DUPLICATE, COURSE_FULL, QUEUE_FULL, ADMISSION_REJECTED):
            detail = response.text[:200]
    except httpx.TimeoutException as error:
        category, detail = TIMEOUT, type(error).__name__
    except httpx.TransportError as error:
        category, detail = CONNECTION_ERROR, type(error).__name__
    except Exception as error:  # a bug in the generator must not lose the record
        category, detail = UNKNOWN, f"{type(error).__name__}: {error}"
    end = time.perf_counter()

    sent_offset = start - experiment_start
    end_offset = end - experiment_start
    if intended is None:
        lateness_ms = intended_arrival_latency_ms = intended_at = None
    else:
        lateness_ms = (sent_offset - intended) * 1000
        # Time from the INTENDED arrival to the response: lateness + send-time latency.
        intended_arrival_latency_ms = (end_offset - intended) * 1000
        intended_at = (sent_wall - timedelta(seconds=sent_offset - intended)).isoformat(timespec="milliseconds")

    return {
        "request_id": request.request_id,
        "sequence": request.sequence,
        "student_id": request.student_id,
        "section_id": request.section_id,
        "planned_offset_s": intended,
        "started_at": sent_wall.isoformat(timespec="milliseconds"),
        "start_offset_s": sent_offset,
        "end_offset_s": end_offset,
        "latency_ms": (end - start) * 1000,
        "http_status": status_code,
        "category": category,
        "detail": detail,
        # --- added with the arrival-model work (all additive) ---
        "intended_offset_s": intended,
        "intended_at": intended_at,
        "sent_offset_s": sent_offset,
        "sent_at": sent_wall.isoformat(timespec="milliseconds"),
        "lateness_ms": lateness_ms,
        "send_time_latency_ms": (end - start) * 1000,
        "intended_arrival_latency_ms": intended_arrival_latency_ms,
    }


def undispatched_record(request):
    """The record for a request that was never sent because the run was stopped early."""
    return {
        "request_id": request.request_id, "sequence": request.sequence,
        "student_id": request.student_id, "section_id": request.section_id,
        "planned_offset_s": request.planned_offset_s, "started_at": None,
        "start_offset_s": None, "end_offset_s": None, "latency_ms": None,
        "http_status": None, "category": NOT_DISPATCHED,
        "detail": "the run was stopped before this request was sent",
        "intended_offset_s": request.planned_offset_s, "intended_at": None, "sent_offset_s": None,
        "sent_at": None, "lateness_ms": None, "send_time_latency_ms": None,
        "intended_arrival_latency_ms": None,
    }


def wait_until(moment, stop_event):
    """Sleep until `moment` (perf_counter time). Returns True if the run was asked to stop."""
    delay = moment - time.perf_counter()
    if delay > 0:
        return stop_event.wait(delay)
    return stop_event.is_set()


def dispatch_open_loop(requests, config, client, experiment_start, stop_event, records):
    """Send every request at its intended time, with at most config.concurrency in flight.

    The intended times are never changed. If the in-flight cap is full when a request is due,
    the dispatcher waits for a free slot, so the request goes out late: that shows up as
    lateness (and cap_was_full) in its record. Nothing piles up without limit, because at most
    `concurrency` requests are submitted and unfinished at any moment.
    """
    free_slots = threading.BoundedSemaphore(config.concurrency)

    def send_and_release(request, cap_was_full, slot_wait_s):
        try:
            record = send_request(client, config.endpoint, request, experiment_start)
            record["cap_was_full"] = cap_was_full
            record["slot_wait_ms"] = slot_wait_s * 1000
            records[request.sequence] = record
        finally:
            free_slots.release()

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        for request in requests:               # already in intended-time order
            if wait_until(experiment_start + request.planned_offset_s, stop_event):
                break
            due = time.perf_counter()
            got_slot = free_slots.acquire(blocking=False)
            cap_was_full = not got_slot
            while not got_slot:                # the cap is full: wait, but stay interruptible
                if stop_event.is_set():
                    break
                got_slot = free_slots.acquire(timeout=0.05)
            if not got_slot:
                break
            pool.submit(send_and_release, request, cap_was_full, time.perf_counter() - due)


def dispatch_closed_loop(requests, config, client, experiment_start, stop_event, records):
    """Virtual users: think, send, WAIT for the response, think again, ... until their requests are done."""
    by_user = {}
    for request in requests:
        by_user.setdefault(request.user, []).append(request)

    def run_user(user_requests):
        previous_end = None
        for request in user_requests:
            if stop_event.wait(request.think_time_before_s or 0):   # thinking (interruptible)
                return
            record = send_request(client, config.endpoint, request, experiment_start)  # returns after the response
            record["user"] = request.user
            record["think_time_before_s"] = request.think_time_before_s
            record["previous_end_offset_s"] = previous_end           # when this user's last response arrived
            records[request.sequence] = record
            previous_end = record["end_offset_s"]

    with ThreadPoolExecutor(max_workers=len(by_user)) as pool:
        list(pool.map(run_user, by_user.values()))


def run_workload(requests, config, client=None, stop_event=None):
    """Run the whole workload. Returns (results, elapsed_seconds), one result per request.

    `stop_event` lets a caller (or Ctrl-C) end the run early; requests not yet sent get a
    NOT_DISPATCHED record, so nothing silently disappears.
    """
    own_client = client is None
    if own_client:
        connections = config.virtual_users if config.arrival_model == "closed" else config.concurrency
        client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            limits=httpx.Limits(max_connections=connections, max_keepalive_connections=connections),
        )
    stop_event = stop_event or threading.Event()
    records = {}
    dispatch = dispatch_closed_loop if config.arrival_model == "closed" else dispatch_open_loop
    experiment_start = time.perf_counter()
    try:
        dispatch(requests, config, client, experiment_start, stop_event, records)
    except KeyboardInterrupt:
        stop_event.set()                       # in-flight requests have finished by now; report what happened
    finally:
        if own_client:
            client.close()
    elapsed = time.perf_counter() - experiment_start
    results = [records.get(request.sequence) or undispatched_record(request) for request in requests]
    return results, elapsed


# -------------------------------------------------------------------- results

def percentile(sorted_values, percent):
    """Nearest-rank percentile of an already sorted, non-empty list."""
    rank = math.ceil(percent / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


def latency_stats(values):
    """average/min/max/p50/p95/p99 of a list of milliseconds, or None if the list is empty."""
    values = sorted(values)
    if not values:
        return None
    return {
        "average": sum(values) / len(values),
        "min": values[0],
        "max": values[-1],
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def lateness_stats(values):
    """mean/median/max always; p95 and p99 only when the sample is large enough to mean something."""
    values = sorted(values)
    if not values:
        return None
    return {
        "mean": sum(values) / len(values),
        "median": percentile(values, 50),
        "p95": percentile(values, 95) if len(values) >= MIN_SAMPLES_P95 else None,
        "p99": percentile(values, 99) if len(values) >= MIN_SAMPLES_P99 else None,
        "max": values[-1],
        "samples": len(values),
    }


def rate_between(times):
    """Average event rate of a series of timestamps: (events - 1) / (last - first).

    The offered rate applies this to the INTENDED times and the achieved dispatch rate to the
    ACTUAL send times, so both use the same formula and the same kind of interval.
    Returns None when there are fewer than two events or they all happen at the same instant.
    """
    if len(times) < 2:
        return None
    span = max(times) - min(times)
    return (len(times) - 1) / span if span > 0 else None


OPEN_LOOP_RULE = ("valid_open_loop is true only if every intended request was dispatched AND no request "
                  "was sent more than lateness_tolerance_ms after its intended arrival time")


def summarize_open_loop(results, config):
    sent = [r for r in results if r["category"] != NOT_DISPATCHED]
    latenesses = [r["lateness_ms"] for r in sent if r.get("lateness_ms") is not None]
    tolerance = config.lateness_tolerance_ms
    over_tolerance = sum(1 for value in latenesses if value > tolerance)
    not_sent = len(results) - len(sent)
    counts = {c: sum(1 for r in results if r["category"] == c) for c in (TIMEOUT, CONNECTION_ERROR, SERVER_ERROR, CLIENT_ERROR, UNKNOWN)}

    reasons = []
    if not_sent:
        reasons.append(f"{not_sent} of {len(results)} intended requests were never dispatched")
    if over_tolerance:
        reasons.append(f"{over_tolerance} requests were sent more than {tolerance} ms after their intended arrival")
    capped = sum(1 for r in sent if r.get("cap_was_full"))

    offered = rate_between([r["intended_offset_s"] for r in results if r.get("intended_offset_s") is not None])
    achieved = rate_between([r["sent_offset_s"] for r in sent if r.get("sent_offset_s") is not None])
    return {
        "intended_requests": len(results),
        "dispatched_requests": len(sent),
        "undispatched_requests": not_sent,
        "offered_rate_per_s": offered,
        "achieved_dispatch_rate_per_s": achieved,
        "achieved_to_offered_ratio": achieved / offered if offered and achieved else None,
        "rate_definition": "(events - 1) / (last - first) over the intended times (offered) "
                           "or over the actual send times (achieved)",
        "lateness_ms": lateness_stats(latenesses),
        "lateness_tolerance_ms": tolerance,
        "requests_over_tolerance": over_tolerance,
        "in_flight_cap": config.concurrency,
        "requests_that_found_the_cap_full": capped,
        "errors": {"timeouts": counts[TIMEOUT], "connection_errors": counts[CONNECTION_ERROR],
                   "server_errors": counts[SERVER_ERROR], "client_errors": counts[CLIENT_ERROR],
                   "unclassified": counts[UNKNOWN]},
        "valid_open_loop": not_sent == 0 and over_tolerance == 0,
        "validity_rule": OPEN_LOOP_RULE,
        "invalid_reasons": reasons,   # always listed, so an invalid run explains itself
    }


def summarize_closed_loop(results, config):
    sent = [r for r in results if r["category"] != NOT_DISPATCHED]
    gaps = [r["sent_offset_s"] - r["previous_end_offset_s"] for r in sent
            if r.get("previous_end_offset_s") is not None]
    per_user = {}
    for r in sent:
        per_user[r.get("user")] = per_user.get(r.get("user"), 0) + 1
    return {
        "virtual_users": config.virtual_users,
        "think_time_min_s": config.think_time_min_s,
        "think_time_max_s": config.think_time_max_s,
        "intended_requests": len(results),
        "dispatched_requests": len(sent),
        "undispatched_requests": len(results) - len(sent),
        "requests_per_user": {"min": min(per_user.values()), "max": max(per_user.values())} if per_user else None,
        # Gap between a user's previous response and its next send. It can never be negative,
        # and is at least the user's think time: the user really waited for the response.
        "wait_after_previous_response_s": {"min": min(gaps), "mean": sum(gaps) / len(gaps)} if gaps else None,
        "waited_for_previous_response": all(gap >= 0 for gap in gaps),
        "arrivals_are_response_dependent": True,
    }


def summarize_results(results, elapsed_seconds, config=None):
    counts = {category: 0 for category in ALL_CATEGORIES}
    for result in results:
        counts[result["category"]] += 1

    total = len(results)
    completed = total - counts[NOT_DISPATCHED]   # requests that were really sent and got an outcome
    summary = {
        "total_requests": total,
        "successful_requests": counts[SUCCESS],
        # "failed" means: did not produce a registration (duplicates and full courses included)
        "failed_requests": total - counts[SUCCESS],
        "category_counts": counts,
        "elapsed_seconds": elapsed_seconds,
        # Completed requests/s of any outcome, over the whole run (start to last response).
        # NOT the same as successful throughput, and NOT the offered/achieved arrival rates.
        "completed_requests_per_second": completed / elapsed_seconds if elapsed_seconds > 0 else None,
        # Registrations actually created per second.
        "successful_registrations_per_second": counts[SUCCESS] / elapsed_seconds if elapsed_seconds > 0 else None,
    }

    # Latency covers requests that received an HTTP response. Timeouts and
    # connection errors have no real response time, so they are left out.
    answered = [r for r in results if r["http_status"] is not None]
    summary["latency_sample_count"] = len(answered)
    summary["latency_ms"] = latency_stats([r["latency_ms"] for r in answered])   # = send-time latency
    summary["send_time_latency_ms"] = summary["latency_ms"]                      # clearer name, same numbers
    summary["intended_arrival_latency_ms"] = latency_stats(
        [r["intended_arrival_latency_ms"] for r in answered if r.get("intended_arrival_latency_ms") is not None])

    summary["arrival_model"] = config.arrival_model if config else None
    summary["open_loop"] = summarize_open_loop(results, config) if config and config.arrival_model == "open" else None
    summary["closed_loop"] = summarize_closed_loop(results, config) if config and config.arrival_model == "closed" else None
    return summary


def make_experiment_id(config):
    now = datetime.now()
    # Milliseconds are included so two runs started in the same second get different files.
    stamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}"
    if config.arrival_model == "closed":
        return f"closed-{config.contention}-u{config.virtual_users}-seed{config.seed}-{stamp}"
    return f"{config.pattern}-{config.contention}-c{config.concurrency}-seed{config.seed}-{stamp}"


def generator_revision():
    """`git describe --always --dirty` of the generator's checkout, or None if git is unavailable."""
    try:
        done = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True, text=True,
                              timeout=2, cwd=os.path.dirname(os.path.abspath(__file__)))
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def build_run_info(config, requests, started_at, ended_at):
    """What is needed to repeat the run, and what cannot be repeated exactly."""
    closed = config.arrival_model == "closed"
    return {
        "generator_version": GENERATOR_VERSION,
        "generator_revision": generator_revision(),
        "arrival_model": config.arrival_model,
        "seed": config.seed,
        "run_started_at": started_at.isoformat(timespec="milliseconds"),
        "run_ended_at": ended_at.isoformat(timespec="milliseconds"),
        "in_flight_cap": None if closed else config.concurrency,
        "timeout_seconds": config.timeout_seconds,
        "lateness_tolerance_ms": None if closed else config.lateness_tolerance_ms,
        "target_rate_per_s": None if closed or config.pattern in ("burst", "phases") else config.rate,
        "schedule": None if closed else {
            "pattern": config.pattern,
            "phases": phase_plan(config) if config.pattern == "phases" else None,
            "intended_requests": len(requests),
            "last_intended_offset_s": max((r.planned_offset_s for r in requests), default=None),
        },
        "virtual_users": config.virtual_users if closed else None,
        "think_time": {"min_s": config.think_time_min_s, "max_s": config.think_time_max_s} if closed else None,
        "reproducible": "the planned schedule, think times and request targets (see generated_requests) "
                        "follow from the seed and the configuration",
        "not_reproducible": "operating-system thread scheduling, network timing and server response times, "
                            "so lateness, latency and which request wins a seat vary between runs",
    }


def save_results(path, experiment_id, config, requests, results, summary, run_info=None):
    document = {
        "experiment_id": experiment_id,
        "config": asdict(config),
        "generated_requests": [asdict(request) for request in requests],
        "summary": summary,
        "results": results,
    }
    if run_info is not None:
        document["run"] = run_info
    with open(path, "w") as output_file:
        json.dump(document, output_file, indent=2)


def check_saved_results(path, expected_requests):
    """Read the file back and confirm nothing went missing. Raises ValueError if not."""
    with open(path) as saved_file:
        saved = json.load(saved_file)
    results = saved["results"]
    if len(results) != expected_requests:
        raise ValueError(f"expected {expected_requests} results, file has {len(results)}")
    if len({r["request_id"] for r in results}) != expected_requests:
        raise ValueError("duplicate or missing request IDs in results")
    counts = saved["summary"]["category_counts"]
    if sum(counts.values()) != expected_requests:
        raise ValueError("category counts do not add up to the number of requests")
    open_loop = saved["summary"].get("open_loop")
    if open_loop and open_loop["dispatched_requests"] + open_loop["undispatched_requests"] != open_loop["intended_requests"]:
        raise ValueError("dispatched + undispatched does not equal the intended request count")
    return saved


# ------------------------------------------------------------------------ CLI

def parse_phases(text):
    """Turn "10:5,100:2,10:10" into [[10.0, 5.0], [100.0, 2.0], [10.0, 10.0]] (rate_per_s:duration_s)."""
    try:
        return [[float(rate), float(duration)] for rate, duration in (part.split(":") for part in text.split(","))]
    except ValueError:
        raise ConfigError("--phases must look like RATE:DURATION,RATE:DURATION, e.g. 10:5,100:2,10:10") from None


def parse_args(argv=None):
    defaults = WorkloadConfig()
    parser = argparse.ArgumentParser(
        description="Send a controlled, reproducible workload to POST /registrations. "
                    "The database must already be seeded (python -m app.seed). "
                    "Defaults are small demonstration values, not research parameters.")
    parser.add_argument("--base-url", default=defaults.base_url)
    parser.add_argument("--arrival-model", choices=ARRIVAL_MODELS, default=defaults.arrival_model,
                        help="open: arrivals follow a fixed schedule whatever the responses; "
                             "closed: --users virtual users, each waits for its response before the next request")
    parser.add_argument("--requests", type=int, default=defaults.request_count,
                        help="number of requests (derived from --phases when those are given)")
    parser.add_argument("--concurrency", type=int, default=defaults.concurrency,
                        help=f"open loop: cap on requests in flight (1..{MAX_IN_FLIGHT}); each uses a thread and a connection")
    parser.add_argument("--pattern", choices=PATTERNS, default=None,
                        help="open loop timing: steady (fixed rate), burst (all at once), ramp (rate grows in stages), "
                             "phases (use --phases). Default: burst, or phases if --phases is given")
    parser.add_argument("--phases", default=None,
                        help='open loop schedule as RATE:DURATION pairs, e.g. "10:5,100:2,10:10" = 10/s for 5 s, '
                             "100/s for 2 s, then 10/s for 10 s (an example, not a recommended value)")
    parser.add_argument("--lateness-tolerance-ms", type=float, default=defaults.lateness_tolerance_ms,
                        help="open loop: a request sent later than this after its intended time makes the run invalid")
    parser.add_argument("--users", type=int, default=defaults.virtual_users, help="closed loop: virtual users")
    parser.add_argument("--think-min", type=float, default=defaults.think_time_min_s,
                        help="closed loop: minimum think time in seconds before each request")
    parser.add_argument("--think-max", type=float, default=None,
                        help="closed loop: maximum think time (default: same as --think-min, i.e. fixed)")
    parser.add_argument("--contention", choices=CONTENTIONS, default=defaults.contention,
                        help="targets: hot (hot sections only), independent (all sections evenly), mixed")
    parser.add_argument("--sections", default=",".join(map(str, defaults.section_ids)),
                        help="comma-separated section ids to target")
    parser.add_argument("--hot-sections", type=int, default=defaults.hot_section_count,
                        help="how many of the first --sections are hot")
    parser.add_argument("--hot-fraction", type=float, default=defaults.hot_fraction,
                        help="share of hot requests for --contention mixed")
    parser.add_argument("--duplicate-fraction", type=float, default=defaults.duplicate_fraction,
                        help="share of requests that repeat an earlier student+section")
    parser.add_argument("--students", type=int, default=defaults.student_count,
                        help="students STU001..STUnnn (must exist in the database)")
    parser.add_argument("--rate", type=float, default=defaults.rate,
                        help="requests/second for steady; final-stage rate for ramp")
    parser.add_argument("--ramp-stages", type=int, default=defaults.ramp_stages)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--timeout", type=float, default=defaults.timeout_seconds, help="seconds per request")
    parser.add_argument("--output-dir", default=defaults.output_dir)
    return parser.parse_args(argv)


def config_from_args(args):
    defaults = WorkloadConfig()
    try:
        section_ids = [int(part) for part in args.sections.split(",")]
    except ValueError:
        raise ConfigError("--sections must be comma-separated integers, e.g. 1,2") from None
    phases = parse_phases(args.phases) if args.phases else []
    if phases and args.pattern not in (None, "phases"):
        raise ConfigError("--phases cannot be combined with --pattern " + args.pattern)
    if args.pattern == "phases" and not phases:
        raise ConfigError("--pattern phases needs --phases")
    pattern = "phases" if phases else (args.pattern or defaults.pattern)
    return WorkloadConfig(
        base_url=args.base_url, request_count=args.requests, concurrency=args.concurrency,
        arrival_model=args.arrival_model, pattern=pattern, phases=phases,
        lateness_tolerance_ms=args.lateness_tolerance_ms, virtual_users=args.users,
        think_time_min_s=args.think_min,
        think_time_max_s=args.think_min if args.think_max is None else args.think_max,
        contention=args.contention, student_count=args.students,
        section_ids=section_ids, hot_section_count=args.hot_sections,
        hot_fraction=args.hot_fraction, duplicate_fraction=args.duplicate_fraction,
        rate=args.rate, ramp_stages=args.ramp_stages, seed=args.seed,
        timeout_seconds=args.timeout, output_dir=args.output_dir,
    )


def main(argv=None):
    try:
        config = config_from_args(parse_args(argv))
        validate_config(config)
        os.makedirs(config.output_dir, exist_ok=True)
        if not os.access(config.output_dir, os.W_OK):
            raise ConfigError(f"cannot write to output directory {config.output_dir!r}")
    except (ConfigError, OSError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    experiment_id = make_experiment_id(config)
    path = os.path.join(config.output_dir, f"{experiment_id}.json")
    requests = generate_requests(config)
    closed = config.arrival_model == "closed"
    print(f"Experiment {experiment_id}")
    print(f"  target={config.base_url}{config.endpoint} arrival_model={config.arrival_model} "
          + (f"users={config.virtual_users} think={config.think_time_min_s}-{config.think_time_max_s}s "
             if closed else f"pattern={config.pattern} in_flight_cap={config.concurrency} ")
          + f"contention={config.contention} requests={len(requests)} seed={config.seed}")
    started_at = datetime.now()
    print(f"  started {started_at.isoformat(timespec='seconds')}")

    results, elapsed = run_workload(requests, config)
    ended_at = datetime.now()
    summary = summarize_results(results, elapsed, config)
    save_results(path, experiment_id, config, requests, results, summary,
                 build_run_info(config, requests, started_at, ended_at))

    try:
        check_saved_results(path, len(requests))
    except (ValueError, OSError, KeyError) as error:
        print(f"Result validation FAILED: {error}", file=sys.stderr)
        return 1

    print(json.dumps({key: summary[key] for key in (
        "total_requests", "successful_requests", "failed_requests", "category_counts",
        "elapsed_seconds", "completed_requests_per_second",
        "successful_registrations_per_second", "latency_ms", "intended_arrival_latency_ms",
        "open_loop", "closed_loop")}, indent=2))
    print(f"  results saved to {path}")

    open_loop = summary["open_loop"]
    if open_loop and not open_loop["valid_open_loop"]:
        print("WARNING: this run is NOT valid for open-loop evaluation: "
              + "; ".join(open_loop["invalid_reasons"]), file=sys.stderr)
    if summary["category_counts"][CONNECTION_ERROR] == len(results):
        print("Experiment FAILED: every request failed to connect. Is the API running?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
