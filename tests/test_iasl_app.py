"""IASL in the real application: start-up, HTTP responses, the live settings swap, result files, and (MySQL only)
database correctness under admission pressure. Numbers are test-fixture values, not research parameters."""
import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from app import demo_api
from app.iasl.config import IASLConfig
from app.main import create_app
from app.os_layer import request_pipeline
from app.os_layer.layer_config import OSLayerConfig
from tests.conftest import add_students, count_registrations, get_section, requires_mysql, wait_until
from tests.test_os_request_pipeline import FakeRegistration
from workload import workload_generator as wg

ADMISSION_BODY = {"success": False, "message": "Request rejected by admission control"}


def quiet(**changes):
    """IASL on, but the loop ticks only every 10 s so it never moves the limit during a short test."""
    base = dict(enabled=True, sampling_interval_s=10.0, stale_metric_seconds=20.0, watchdog_seconds=60.0,
                cooldown_seconds=10.0, increase_cooldown_seconds=10.0, reversal_lockout_seconds=10.0)
    base.update(changes)
    return IASLConfig(**base)


@pytest.fixture
def gate():
    return threading.Event()


@pytest.fixture
def demo_on(monkeypatch, tmp_path):
    monkeypatch.setenv("CREG_DEMO_CONTROLS", "1")
    monkeypatch.setenv("CREG_RESULTS_DIR", str(tmp_path))
    return tmp_path


def iasl_of(start_server):
    return start_server.applications[-1].state.iasl


def post(url, student="STU001", section=1):
    return httpx.post(f"{url}/registrations", json={"student_id": student, "section_id": section}, timeout=10)


# ----------------------------------------------------------------------------- start-up

def test_iasl_is_off_by_default_nothing_is_installed_and_the_status_is_unchanged(start_server):
    url, layer = start_server(OSLayerConfig(16, 4, 2))
    assert iasl_of(start_server) is None and layer.admission is None and layer.observer is None
    status = httpx.get(f"{url}/os-layer/status").json()
    assert "admission" not in status
    assert post(url).status_code == 201


def test_when_enabled_the_runtime_runs_and_the_status_shows_the_admission_block(start_server):
    url, layer = start_server(OSLayerConfig(16, 4, 2), quiet())
    iasl = iasl_of(start_server)
    assert iasl.running and layer.admission is iasl.admission
    admission = httpx.get(f"{url}/os-layer/status").json()["admission"]
    assert admission == {"enabled": True, "rejected": 0, "limit": 16, "configured_limit": 16, "fallback": False,
                         "watchdog_tripped": False}
    assert post(url).status_code == 201                                  # a normal registration is unaffected


def test_a_bad_iasl_setting_stops_start_up_and_names_the_variable():
    application = create_app(OSLayerConfig(16, 4, 2), IASLConfig(enabled=True, admission_min=500))
    with pytest.raises(ValueError, match="IASL_ADMISSION_MIN"):
        with TestClient(application):
            pass


def test_iasl_is_switched_on_by_the_environment_and_a_bad_value_refuses_to_start(monkeypatch):
    monkeypatch.delenv("IASL_ENABLED", raising=False)
    with TestClient(create_app(OSLayerConfig(16, 4, 2))) as client:
        assert client.app.state.iasl is None
    monkeypatch.setenv("IASL_ENABLED", "1")
    with TestClient(create_app(OSLayerConfig(16, 4, 2))) as client:
        assert client.app.state.iasl is not None and client.app.state.iasl.running
        thread = client.app.state.iasl._thread
    assert not thread.is_alive()                                          # shutdown stopped the loop thread
    monkeypatch.setenv("IASL_SAMPLING_INTERVAL_S", "fast")
    with pytest.raises(ValueError, match="IASL_SAMPLING_INTERVAL_S"):
        with TestClient(create_app(OSLayerConfig(16, 4, 2))):
            pass


# ----------------------------------------------------------------------------- the HTTP contract

def test_an_admission_refusal_is_a_503_with_its_own_message_distinct_from_a_full_queue(start_server, monkeypatch, gate):
    fake = FakeRegistration(gate=gate)
    monkeypatch.setattr(request_pipeline, "register_student", fake)
    url, layer = start_server(OSLayerConfig(16, 2, 2), quiet())
    iasl = iasl_of(start_server)
    futures = [layer.submit(f"F{i}", 1) for i in range(2)]
    assert wait_until(lambda: layer.workers.active == 2)                  # both workers are busy (blocked on the gate)
    iasl.admission.set_limit(1)                                           # tighten only now, so no request races a worker
    futures.append(layer.submit("FQ", 1))                                 # queue depth 1 == limit

    refused = post(url, "STU001")
    assert refused.status_code == 503 and refused.json() == ADMISSION_BODY
    assert wg.classify_response(refused.status_code, refused.json()) == wg.ADMISSION_REJECTED

    iasl.admission.set_limit(16)                                          # now only the physical queue can refuse
    futures += [layer.submit(f"FF{i}", 1) for i in range(15)]             # depth 16: the queue is genuinely full
    full = post(url, "STU002")
    assert full.status_code == 503 and full.json() == {"success": False, "message": "Request queue is full"}
    assert wg.classify_response(full.status_code, full.json()) == wg.QUEUE_FULL
    snapshot = httpx.get(f"{url}/os-layer/status").json()
    assert snapshot["admission"]["rejected"] == 1 and snapshot["queue"]["rejected_queue_full"] == 1
    gate.set()
    for f in futures:
        f.result(timeout=10)


def test_the_generator_knows_the_new_response_and_still_never_calls_an_unknown_answer_a_success():
    assert wg.classify_response(503, ADMISSION_BODY) == wg.ADMISSION_REJECTED
    assert wg.classify_response(503, {"success": False, "message": "something else"}) == wg.SERVER_ERROR
    assert wg.classify_response(429, ADMISSION_BODY) == wg.CLIENT_ERROR   # only the agreed (status, message) pair counts
    assert wg.ADMISSION_REJECTED in wg.ALL_CATEGORIES and wg.ADMISSION_REJECTED != wg.QUEUE_FULL


# ----------------------------------------------------------------------------- demo API integration

def test_replacing_the_layer_from_the_dashboard_re_attaches_iasl_to_the_new_layer(start_server, demo_on):
    url, _ = start_server(OSLayerConfig(16, 2, 2), quiet())
    iasl = iasl_of(start_server)
    old_admission = iasl.admission
    reply = httpx.post(f"{url}/demo/os-layer", json={"queue_capacity": 30, "worker_count": 3, "db_semaphore_permits": 2})
    assert reply.status_code == 200
    application = start_server.applications[-1]
    assert application.state.os_layer.admission is iasl.admission is not old_admission
    admission = httpx.get(f"{url}/os-layer/status").json()["admission"]
    assert admission["limit"] == 30 and admission["rejected"] == 0       # fresh counters, bounds from the new size
    assert (iasl.controller.param.minimum, iasl.controller.param.maximum) == (3, 30)
    assert post(url).status_code == 201


def test_progress_counts_admission_refusals_as_answered_requests():
    class Layer:
        def __init__(self, snapshot):
            self._snapshot = snapshot

        def snapshot(self):
            return self._snapshot
    base = {"workers": {"jobs_finished": 10}, "queue": {"rejected_queue_full": 2}}
    assert demo_api.counters(Layer(base)) == {"finished": 10, "refused": 2}                       # no admission block
    with_admission = {**base, "admission": {"rejected": 5}}
    assert demo_api.counters(Layer(with_admission)) == {"finished": 10, "refused": 7}


def run_burst(url):
    start = httpx.post(f"{url}/demo/runs", json={"pattern": "burst", "request_count": 6, "contention": "hot", "seed": 42})
    assert start.status_code == 202
    job_id = start.json()["job_id"]
    wait_until(lambda: httpx.get(f"{url}/demo/runs/{job_id}").json()["status"] != "running", timeout_seconds=30, interval_seconds=0.05)
    return httpx.get(f"{url}/demo/runs/{job_id}").json()


def test_a_result_file_records_whether_iasl_was_on_and_how_it_was_configured(start_server, demo_on):
    url, _ = start_server(OSLayerConfig(32, 4, 2), quiet())
    job = run_burst(url)
    assert job["status"] == "done", job["error"]
    document = json.loads((demo_on / f"{job['experiment_id']}.json").read_text())
    recorded = document["server"]["iasl"]
    assert recorded["enabled"] is True and recorded["config"]["sampling_interval_s"] == 10.0
    assert recorded["admission"]["capacity"] == 32 and "decisions_logged" in recorded
    assert document["server"]["os_layer"] == {"queue_capacity": 32, "worker_count": 4, "db_semaphore_permits": 2}  # unchanged shape


def test_a_result_file_from_a_run_without_iasl_says_so(start_server, demo_on):
    url, _ = start_server(OSLayerConfig(32, 4, 2))
    job = run_burst(url)
    assert job["status"] == "done", job["error"]
    document = json.loads((demo_on / f"{job['experiment_id']}.json").read_text())
    assert document["server"]["iasl"] == {"enabled": False}


# ----------------------------------------------------------------------------- correctness on MySQL/InnoDB

@requires_mysql
def test_under_admission_pressure_and_semaphore_saturation_the_database_stays_correct(start_server, db):
    capacity = 10
    section = demo_api.models.CourseSection(course_code="IASLX", course_name="IASL test", capacity=capacity,
                                            available_seats=capacity)
    db.add(section)
    db.commit()
    section_id = section.id
    add_students(db, 11, 40)                                              # STU001..STU040 now exist
    url, layer = start_server(OSLayerConfig(queue_capacity=32, worker_count=4, db_semaphore_permits=1), quiet())
    iasl_of(start_server).admission.set_limit(4)                           # tight admission, one DB permit: heavy pressure

    config = wg.WorkloadConfig(base_url=url, request_count=120, concurrency=120, pattern="burst", contention="hot",
                               section_ids=[section_id], student_count=40, seed=5)
    wg.validate_config(config)
    results, elapsed = wg.run_workload(wg.generate_requests(config), config)
    counts = wg.summarize_results(results, elapsed)["category_counts"]

    assert sum(counts.values()) == 120                                    # every request got exactly one outcome
    assert counts[wg.ADMISSION_REJECTED] > 0                              # admission control really did refuse some
    assert counts[wg.UNKNOWN] == counts[wg.SERVER_ERROR] == counts[wg.CLIENT_ERROR] == 0
    assert counts[wg.TIMEOUT] == counts[wg.CONNECTION_ERROR] == 0
    snapshot = layer.snapshot()
    assert snapshot["admission"]["rejected"] == counts[wg.ADMISSION_REJECTED]       # server and clients agree
    assert snapshot["queue"]["rejected_queue_full"] == counts[wg.QUEUE_FULL]
    assert snapshot["db_semaphore"]["max_in_critical_section"] <= 1
    assert snapshot["queue"]["max_depth"] <= 4

    # The database is the authority: nothing oversold, nothing duplicated, rows equal what clients were told.
    assert counts[wg.SUCCESS] <= capacity
    assert count_registrations(db, section_id) == counts[wg.SUCCESS]
    assert get_section(db, "IASLX").available_seats == capacity - counts[wg.SUCCESS]
    state = demo_api.database_state()
    assert state["all_ok"], [i for i in state["invariants"] if not i["ok"]]
