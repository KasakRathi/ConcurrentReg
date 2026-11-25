"""The read-only IASL endpoints: shape, honesty about being off, no write route, strict JSON, no interference."""
import json
import threading
import time

import httpx
import pytest

from app.iasl import serialize
from app.iasl.config import IASLConfig
from app.iasl.types import (
    Assessment, Gauges, IntervalRates, MetricQuality, MetricsSample, Signal, StateTransition, SystemState, WindowStats,
)
from app.main import app as module_app
from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from tests.conftest import wait_until
from tests.test_os_request_pipeline import FakeRegistration

PATHS = ("/iasl/status", "/iasl/metrics", "/iasl/decisions", "/iasl/config")
DECISION_FIELDS = {"id", "event", "at_wall", "at_monotonic", "previous_state", "current_state", "metrics_used", "action",
                   "parameter", "previous_value", "new_value", "rule", "reason", "guardrail", "blocked_by",
                   "suppressed_since_last"}


def enabled(**changes):
    """IASL on, ticks driven by the test (the loop thread only fires every 10 s), fast escalation."""
    base = dict(enabled=True, sampling_interval_s=10.0, stale_metric_seconds=20.0, watchdog_seconds=60.0,
                cooldown_seconds=10.0, increase_cooldown_seconds=10.0, reversal_lockout_seconds=10.0,
                smoothing_samples=1, escalate_samples=2, queue_wait_p95_pressure_s=100.0, queue_wait_p95_overload_s=200.0)
    base.update(changes)
    return IASLConfig(**base)


@pytest.fixture
def gate():
    return threading.Event()


def strict_json(response):
    """Parse JSON refusing NaN/Infinity, which are not valid JSON."""
    def refuse(token):
        raise ValueError(f"non-standard JSON constant {token}")
    return json.loads(response.text, parse_constant=refuse)


def get(url, path, **params):
    return httpx.get(f"{url}{path}", params=params, timeout=5)


def overloaded(start_server, monkeypatch, gate, capacity=40):
    """A server whose queue is full and whose IASL has seen it long enough to restrict admission."""
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration(gate=gate))
    url, layer = start_server(OSLayerConfig(capacity, 2, 2), enabled())
    iasl = start_server.applications[-1].state.iasl
    futures = [layer.submit(f"W{i}", 1) for i in range(2)]
    assert wait_until(lambda: layer.workers.active == 2)
    futures += [layer.submit(f"Q{i}", 1) for i in range(capacity)]
    for _ in range(3):
        iasl.tick()
    return url, layer, iasl, futures


# ----------------------------------------------------------------------------- read-only by construction

def test_there_are_exactly_four_iasl_routes_and_all_of_them_are_get():
    paths = {p: sorted(methods) for p, methods in module_app.openapi()["paths"].items() if p.startswith("/iasl")}
    assert paths == {p: ["get"] for p in PATHS}


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_every_attempt_to_change_iasl_over_http_is_refused(start_server, method):
    url, _ = start_server(OSLayerConfig(16, 2, 2), enabled())
    for path in PATHS:
        reply = httpx.request(method, f"{url}{path}", json={"admission_min": 1}, timeout=5)
        assert reply.status_code == 405, (method, path)


# ----------------------------------------------------------------------------- IASL switched off

def test_when_iasl_is_off_the_endpoints_say_so_instead_of_failing(start_server):
    url, _ = start_server(OSLayerConfig(16, 2, 2))
    for path in ("/iasl/status", "/iasl/metrics"):
        body = strict_json(get(url, path))
        assert body["enabled"] is False and "switched off" in body["message"]
    decisions = strict_json(get(url, "/iasl/decisions"))
    assert decisions["enabled"] is False and decisions["decisions"] == []
    config = strict_json(get(url, "/iasl/config"))
    assert config["enabled"] is False and config["active"] is False and config["read_only"] is True
    assert config["settings"]["enabled"] is False and "resolved" not in config
    assert config["environment_variables"]["enabled"] == "IASL_ENABLED"


# ----------------------------------------------------------------------------- IASL on, before any analysis

def test_before_the_first_tick_nothing_is_invented(start_server):
    url, layer = start_server(OSLayerConfig(40, 2, 2), enabled())
    status = strict_json(get(url, "/iasl/status"))
    assert status["enabled"] is True and status["attached"] is True
    assert status["state"] is None and status["current_metrics"] is None
    assert status["last_decision"] is None and status["last_control_action"] is None and status["last_decision_reason"] is None
    assert status["admission"]["limit_in_force"] == 40 and status["admission"]["capacity"] == 40
    assert status["fallback"]["active"] is False and status["loop"]["ticks"] == 0
    metrics = strict_json(get(url, "/iasl/metrics"))
    assert metrics["sample"] is None and metrics["analysis"] is None
    assert strict_json(get(url, "/iasl/decisions"))["decisions"] == []


# ----------------------------------------------------------------------------- IASL on, under load

def test_status_answers_every_question_an_operator_has(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    status = strict_json(get(url, "/iasl/status"))
    assert status["enabled"] is True and status["running"] is True
    assert status["state"] == "OVERLOADED" and "OVERLOADED" in status["state_reason"]
    assert status["metrics_quality"] in ("OK", "DEGRADED") and status["assessment_quality"] == "OK"
    metrics = status["current_metrics"]
    assert metrics["queue_depth"] == 40 and metrics["queue_utilization"] == 1.0 and metrics["sample_age_s"] >= 0
    admission = status["admission"]
    assert admission["limit_in_force"] == admission["configured_limit"] == 32          # 40 - 2 x step 4
    assert (admission["minimum"], admission["maximum"], admission["initial"], admission["step"]) == (2, 40, 40, 4)
    action = status["last_control_action"]
    assert action["action"] == "DECREASE" and (action["previous_value"], action["new_value"]) == (40, 32)
    assert status["last_decision_reason"] == status["last_decision"]["reason"] and status["last_decision_reason"]
    assert status["fallback"]["active"] is False and status["fallback"]["mode"] == "baseline"
    assert status["loop"]["ticks"] == 3 and status["loop"]["changes"] == 1 and status["loop"]["failed_ticks"] == 0
    assert "PROVISIONAL" in status["calibration"]
    assert admission["what_it_limits"]
    gate.set()


def test_the_last_control_action_is_a_real_change_not_an_idle_hold(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    iasl.tick()                                                           # inside the cooldown: blocked, recorded as a HOLD
    status = strict_json(get(url, "/iasl/status"))
    assert status["last_decision"]["action"] == "HOLD" and status["last_decision"]["blocked_by"] == "cooldown"
    assert status["last_control_action"]["action"] == "DECREASE"          # the real change is still reported as the action
    gate.set()


def test_metrics_separate_instantaneous_interval_and_window_values_and_list_what_is_unavailable(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    body = strict_json(get(url, "/iasl/metrics"))
    sample = body["sample"]
    assert set(sample) >= {"gauges", "interval", "window", "kinds", "unavailable", "quality", "issues", "age_s", "wall_time"}
    assert sample["gauges"]["queue_depth"] == 40 and sample["gauges"]["queue_capacity"] == 40
    assert set(sample["interval"]) >= {"arrivals_per_s", "queue_full_rejection_rate", "error_rate", "admission_rejections_per_s"}
    assert set(sample["window"]) >= {"covered_s", "samples", "queue_wait_p95_s", "server_latency_p99_s"}
    assert set(sample["kinds"]) == {"gauges", "interval", "window"}
    assert set(sample["unavailable"]) >= {"timed_out_requests", "db_timeouts", "db_lock_wait", "timeout_rate"}
    analysis = body["analysis"]
    assert analysis["state"] == "OVERLOADED" and len(analysis["signals"]) == 6
    assert {s["class"] for s in analysis["signals"]} == {"primary", "corroborating"}
    assert analysis["transition"] is None or analysis["transition"]["to"]
    gate.set()


def test_metrics_history_is_optional_bounded_and_oldest_first(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    assert "history" not in strict_json(get(url, "/iasl/metrics"))
    rows = strict_json(get(url, "/iasl/metrics", history=2))["history"]
    assert len(rows) == 2 and set(rows[0]) >= {"wall_time", "queue_utilization", "admission_limit", "queue_wait_p95_s"}
    all_rows = strict_json(get(url, "/iasl/metrics", history=120))["history"]
    assert len(all_rows) == 3 and all_rows[-2:] == rows
    assert get(url, "/iasl/metrics", history=121).status_code == 422
    assert get(url, "/iasl/metrics", history=-1).status_code == 422
    gate.set()


def test_decisions_list_complete_records_newest_last_with_a_limit(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    body = strict_json(get(url, "/iasl/decisions"))
    assert body["enabled"] is True and body["returned"] == body["kept"] >= 1 and "suppressed_since_last" in body["note"]
    for record in body["decisions"]:
        assert DECISION_FIELDS <= set(record)
    ids = [d["id"] for d in body["decisions"]]
    assert ids == sorted(ids)
    change = next(d for d in body["decisions"] if d["action"] == "DECREASE")
    assert (change["previous_value"], change["new_value"], change["rule"]) == (40, 32, "R2")
    assert change["previous_state"] in ("HEALTHY", "UNDER_PRESSURE", "OVERLOADED") and change["current_state"] == "OVERLOADED"
    assert "signals" in change["metrics_used"]
    one = strict_json(get(url, "/iasl/decisions", limit=1))
    assert one["returned"] == 1 and one["decisions"][0]["id"] == ids[-1]
    for bad in (0, 201, -5):
        assert get(url, "/iasl/decisions", limit=bad).status_code == 422
    gate.set()


def test_config_shows_what_is_in_force_and_how_to_change_it(start_server):
    url, layer = start_server(OSLayerConfig(40, 2, 2), enabled(admission_min=5, fallback_mode="conservative"))
    body = strict_json(get(url, "/iasl/config"))
    assert body["enabled"] is True and body["active"] is True and body["read_only"] is True
    assert body["settings"]["admission_min"] == 5 and body["settings"]["fallback_mode"] == "conservative"
    assert body["settings"]["queue_util_overload"] == 0.85                # a provisional default, shown as such
    assert "PROVISIONAL" in body["calibration"] and "environment variables" in body["how_to_change"]
    resolved = body["resolved"]
    assert (resolved["minimum"], resolved["maximum"], resolved["initial"], resolved["step"]) == (5, 40, 40, 4)
    assert resolved["largest_single_move"] == 8 and resolved["fallback_limit"] == 20 and resolved["parameter"] == "admission_depth_limit"
    assert set(body["environment_variables"]) == set(body["settings"])    # every setting says which variable controls it


def test_fallback_mode_is_visible_in_the_status(start_server):
    url, layer = start_server(OSLayerConfig(40, 2, 2), enabled(fallback_after_failures=3, fallback_mode="conservative"))
    iasl = start_server.applications[-1].state.iasl
    def broken():
        raise RuntimeError("boom")
    iasl.collector.sample = broken                                        # real ticks that fail, as in production
    for _ in range(3):
        iasl.tick()
    status = strict_json(get(url, "/iasl/status"))
    assert status["fallback"]["active"] is True and status["fallback"]["fallback_limit"] == 20
    assert status["admission"]["limit_in_force"] == 20
    assert status["last_control_action"]["action"] == "FALLBACK_ENTER" and "boom" in status["last_decision_reason"]


def test_every_response_is_strict_json_even_when_values_are_missing(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    for path in PATHS:
        strict_json(get(url, path))                                       # raises on NaN / Infinity
    strict_json(get(url, "/iasl/metrics", history=120))
    gate.set()


# ----------------------------------------------------------------------------- monitoring cannot interfere

def test_the_endpoints_never_touch_the_os_layer_so_they_cannot_slow_registrations(start_server, monkeypatch, gate):
    url, layer, iasl, futures = overloaded(start_server, monkeypatch, gate)
    calls = []
    real = layer.snapshot
    monkeypatch.setattr(layer, "snapshot", lambda: calls.append(1) or real())
    for path in PATHS:
        for _ in range(20):
            assert get(url, path).status_code == 200
    assert calls == []                                                    # they read IASL's published snapshot only
    gate.set()


def test_the_endpoints_still_answer_while_the_runtime_lock_is_held_by_a_tick(start_server):
    url, layer = start_server(OSLayerConfig(40, 2, 2), enabled())
    iasl = start_server.applications[-1].state.iasl
    iasl.tick()
    with iasl._lock:                                                      # as if a slow tick were in progress
        started = time.perf_counter()
        for path in PATHS:
            assert get(url, path).status_code == 200
        assert get(url, "/iasl/metrics", history=5).status_code == 200
        assert time.perf_counter() - started < 3


def test_registrations_run_normally_while_monitoring_is_hammered(start_server, monkeypatch):
    monkeypatch.setattr(request_pipeline, "register_student", FakeRegistration())
    url, layer = start_server(OSLayerConfig(256, 8, 4), enabled())
    stop, failures, statuses = threading.Event(), [], []

    def monitor():
        while not stop.is_set():
            for path in PATHS:
                try:
                    reply = httpx.get(f"{url}{path}", timeout=5)
                    if reply.status_code != 200:
                        failures.append((path, reply.status_code))
                except Exception as error:
                    failures.append((path, repr(error)))

    def register(first):
        for i in range(40):
            statuses.append(httpx.post(f"{url}/registrations", json={"student_id": f"S{first}-{i}", "section_id": 1}, timeout=10).status_code)

    monitors = [threading.Thread(target=monitor) for _ in range(3)]
    clients = [threading.Thread(target=register, args=(n,)) for n in range(5)]
    for t in monitors + clients:
        t.start()
    for t in clients:
        t.join()
    stop.set()
    for t in monitors:
        t.join()
    assert not failures
    assert statuses == [201] * 200                                        # every registration answered normally


# ----------------------------------------------------------------------------- serializers

def make_sample(**changes):
    base = dict(taken_at=100.0, wall_time="2026-11-25T10:00:00.000", interval_s=0.5, quality=MetricQuality.OK, restart=False,
                gauges=Gauges(queue_depth=3, queue_capacity=10, queue_utilization=0.3),
                interval=IntervalRates(arrivals_per_s=5.0), window=WindowStats(samples=0))
    base.update(changes)
    return MetricsSample(**base)


def test_an_invalid_sample_with_missing_fields_serialises_with_nulls_not_inventions():
    sample = make_sample(quality=MetricQuality.INVALID, issues=("snapshot_failed:RuntimeError",), gauges=Gauges(), interval=None,
                         interval_s=None)
    body = serialize.sample_to_dict(sample, now=102.5)
    assert body["quality"] == "INVALID" and body["issues"] == ["snapshot_failed:RuntimeError"]
    assert body["interval"] is None and body["age_s"] == 2.5 and body["gauges"]["queue_depth"] is None
    json.dumps(body, allow_nan=False)
    assert serialize.sample_to_dict(None) is None


def test_the_history_row_copes_with_a_sample_that_has_no_interval_values():
    row = serialize.history_row(make_sample(interval=None))
    assert row["arrivals_per_s"] is None and row["queue_utilization"] == 0.3
    json.dumps(row, allow_nan=False)


def test_an_assessment_serialises_its_signals_streaks_and_transition():
    signals = (Signal("queue_utilization", "primary", 0.9, 2, 0.5, 0.85), Signal("error_rate", "primary", None, None, 0.02, 0.1))
    transition = StateTransition(SystemState.HEALTHY, SystemState.OVERLOADED, "t", "HEALTHY -> OVERLOADED: test", signals)
    a = Assessment(state=SystemState.OVERLOADED, previous_state=SystemState.HEALTHY, quality=MetricQuality.OK, held=False,
                   candidate=SystemState.OVERLOADED, signals=signals, transition=transition, reason="r", worse_streak=2)
    body = serialize.assessment_to_dict(a)
    assert body["state"] == "OVERLOADED" and body["this_sample_looks"] == "OVERLOADED" and body["streaks"] == {"worse": 2, "better": 0}
    assert body["signals"][1]["value"] is None and body["signals"][1]["level"] is None
    assert body["transition"] == {"from": "HEALTHY", "to": "OVERLOADED", "at": "t", "reason": "HEALTHY -> OVERLOADED: test"}
    json.dumps(body, allow_nan=False)
    held = Assessment(state=SystemState.HEALTHY, previous_state=SystemState.HEALTHY, quality=MetricQuality.STALE, held=True, candidate=None)
    assert serialize.assessment_to_dict(held)["this_sample_looks"] is None
    assert serialize.assessment_to_dict(None) is None
