"""Tests for the demo controls (app/demo_api.py) and the test-suite runner (app/verification.py)."""
import json
import os

import httpx
import pytest

from app import models, verification
from app.database import engine
from tests.conftest import count_registrations, get_section, requires_mysql, wait_until

BURST = {"pattern": "burst", "request_count": 6, "contention": "hot", "seed": 42}


@pytest.fixture
def demo_on(monkeypatch, tmp_path):
    """Turn the demo controls on and send result files to a temporary folder."""
    monkeypatch.setenv("CREG_DEMO_CONTROLS", "1")
    monkeypatch.setenv("CREG_RESULTS_DIR", str(tmp_path))
    return tmp_path


def finished(url, job_id, timeout=30):
    """Wait for a run to stop running and return its final description."""
    wait_until(lambda: httpx.get(f"{url}/demo/runs/{job_id}").json()["status"] != "running", timeout_seconds=timeout, interval_seconds=0.05)
    return httpx.get(f"{url}/demo/runs/{job_id}").json()


# ------------------------------------------------------------------ gating

def test_info_is_public_and_reports_the_database(server_url, monkeypatch):
    monkeypatch.delenv("CREG_DEMO_CONTROLS", raising=False)
    body = httpx.get(f"{server_url}/demo/info").json()
    assert body["controls_enabled"] is False
    assert body["database"]["dialect"] == engine.dialect.name
    assert body["database"]["row_locks"] == (engine.dialect.name == "mysql")
    assert body["results_dir"] is None            # nothing about the server's folders is revealed while controls are off


def test_every_other_demo_endpoint_is_off_by_default(server_url, monkeypatch):
    monkeypatch.delenv("CREG_DEMO_CONTROLS", raising=False)
    for method, path in [("GET", "/demo/state"), ("POST", "/demo/reset"), ("POST", "/demo/runs"), ("GET", "/demo/runs/current"),
                         ("GET", "/demo/results"), ("GET", "/demo/registrations"), ("POST", "/demo/verify"), ("POST", "/demo/os-layer")]:
        response = httpx.request(method, f"{server_url}{path}", json={} if method == "POST" else None)
        assert response.status_code == 404, f"{method} {path} should be hidden when CREG_DEMO_CONTROLS is not 1"


# ------------------------------------------------------------------ state and invariants

def test_state_of_the_seeded_database(server_url, demo_on):
    state = httpx.get(f"{server_url}/demo/state").json()
    assert [(s["course_code"], s["capacity"], s["registered"]) for s in state["sections"]] == [("CSE301", 5, 0), ("CSE302", 2, 0)]
    assert state["totals"] == {"students": 10, "registrations": 0}
    assert state["all_ok"] is True
    assert [i["id"] for i in state["invariants"]] == ["capacity", "seats", "range", "unique"]


def test_invariants_can_fail_when_the_data_is_wrong(server_url, demo_on, db):
    # Bypass the application rules on purpose: three registrations in a 2-seat section, and a wrong seat counter elsewhere.
    section = get_section(db, "CSE302")
    other = get_section(db, "CSE301")      # fetch both first: get_section() rolls back anything not yet committed
    for number in (1, 2, 3):
        student = db.query(models.Student).filter_by(student_id=f"STU00{number}").one()
        db.add(models.Registration(student_id=student.id, section_id=section.id))
    other.available_seats = 4            # no registration stored, so the counter should still be 5
    db.commit()
    state = httpx.get(f"{server_url}/demo/state").json()
    broken = {i["id"]: i["ok"] for i in state["invariants"]}
    assert broken["capacity"] is False and broken["seats"] is False
    assert state["all_ok"] is False
    assert "CSE302" in next(i for i in state["invariants"] if i["id"] == "capacity")["detail"]


def test_registrations_lists_the_stored_rows(server_url, demo_on, db):
    section = get_section(db, "CSE301")
    for student in ("STU001", "STU002"):
        assert httpx.post(f"{server_url}/registrations", json={"student_id": student, "section_id": section.id}).status_code == 201
    db.rollback()
    items = httpx.get(f"{server_url}/demo/registrations").json()["items"]
    assert [(i["student"], i["course"], i["status"]) for i in items] == [("STU001", "CSE301", "REGISTERED"), ("STU002", "CSE301", "REGISTERED")]
    assert httpx.get(f"{server_url}/demo/registrations?limit=1").json()["items"][0]["student"] == "STU001"


def test_reset_restores_the_seeded_state(server_url, demo_on, db):
    section = get_section(db, "CSE301")
    assert httpx.post(f"{server_url}/registrations", json={"student_id": "STU001", "section_id": section.id}).status_code == 201
    assert count_registrations(db, section.id) == 1
    db.rollback()    # end this test's own snapshot: an open transaction would hold a MySQL metadata lock and block the table drop
    state = httpx.post(f"{server_url}/demo/reset").json()
    assert state["totals"]["registrations"] == 0
    assert [s["available_seats"] for s in state["sections"]] == [5, 2]


# ------------------------------------------------------------------ runs

def test_a_run_writes_a_result_file_and_the_database_agrees(server_url, demo_on):
    start = httpx.post(f"{server_url}/demo/runs", json=BURST)
    assert start.status_code == 202
    job = finished(server_url, start.json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert job["progress"]["fraction"] == 1.0

    # the file exists, is the generator's own format, and carries the server context the generator cannot know
    path = demo_on / f"{job['experiment_id']}.json"
    document = json.loads(path.read_text())
    assert document["summary"]["total_requests"] == 6
    assert document["server"]["os_layer"]["worker_count"] == 8          # the test server's settings
    assert document["server"]["database"]["dialect"] == engine.dialect.name

    # the client's count of successes equals the rows in the database
    assert job["db_check"]["registrations_in_db"] == job["db_check"]["successes_reported_by_client"] == job["summary"]["successful_requests"]
    assert job["db_check"]["match"] is True

    listed = httpx.get(f"{server_url}/demo/results").json()["items"]
    assert [i["experiment_id"] for i in listed] == [job["experiment_id"]]
    assert httpx.get(f"{server_url}/demo/results/{job['experiment_id']}").json()["experiment_id"] == job["experiment_id"]


def test_result_names_cannot_escape_the_results_folder(server_url, demo_on):
    (demo_on.parent / "secret.json").write_text("{}")
    for name in ("..%2Fsecret", "%2e%2e%2fsecret", ".hidden", "a%2Fb"):
        assert httpx.get(f"{server_url}/demo/results/{name}").status_code == 404, name


def test_the_result_guard_itself_refuses_escapes(demo_on):
    """Call the function directly: over HTTP the router already rejects slashes, so that path never reaches the guard."""
    from fastapi import HTTPException

    from app import demo_api
    (demo_on.parent / "secret.json").write_text('{"experiment_id": "stolen"}')
    (demo_on / "real.json").write_text('{"experiment_id": "real"}')
    assert demo_api.get_result("real")["experiment_id"] == "real"                      # a genuine file is served
    for bad in ("../secret", "..", ".hidden", "a/b", "x" * 300):
        with pytest.raises(HTTPException) as refusal:
            demo_api.get_result(bad)
        assert refusal.value.status_code == 404, bad
    # a symlink INSIDE the folder that points OUTSIDE it must not be followed
    os.symlink(demo_on.parent / "secret.json", demo_on / "link.json")
    with pytest.raises(HTTPException) as refusal:
        demo_api.get_result("link")
    assert refusal.value.status_code == 404


def test_only_one_run_at_a_time(server_url, demo_on):
    slow = httpx.post(f"{server_url}/demo/runs", json={"pattern": "steady", "rate": 20, "request_count": 24, "contention": "independent"})
    assert slow.status_code == 202
    assert httpx.post(f"{server_url}/demo/runs", json=BURST).status_code == 409
    assert httpx.post(f"{server_url}/demo/reset").status_code == 409
    assert finished(server_url, slow.json()["job_id"])["status"] == "done"
    assert httpx.post(f"{server_url}/demo/runs", json=BURST).status_code == 202        # free again
    finished(server_url, httpx.get(f"{server_url}/demo/runs/current").json()["job_id"])


def test_bad_settings_are_rejected_with_the_generators_own_message(server_url, demo_on):
    zero = httpx.post(f"{server_url}/demo/runs", json={**BURST, "request_count": 0})
    assert zero.status_code == 422 and "request_count" in zero.json()["detail"]
    too_many_students = httpx.post(f"{server_url}/demo/runs", json={**BURST, "student_count": 99})
    assert too_many_students.status_code == 422 and "99" in too_many_students.json()["detail"]
    huge = httpx.post(f"{server_url}/demo/runs", json={**BURST, "request_count": 5001})
    assert huge.status_code == 422
    # a refused start must release the lock, or the demo would be stuck
    assert httpx.post(f"{server_url}/demo/runs", json=BURST).status_code == 202
    finished(server_url, httpx.get(f"{server_url}/demo/runs/current").json()["job_id"])


@requires_mysql
def test_seat_race_through_the_demo_api_never_oversells(start_server, demo_on):
    """30 simultaneous requests for the 2-seat section: exactly 2 rows in InnoDB, and the client was told 2."""
    from app.os_layer.layer_config import OSLayerConfig
    url, _layer = start_server(OSLayerConfig(queue_capacity=64, worker_count=8, db_semaphore_permits=8))
    job = httpx.post(f"{url}/demo/runs", json={"pattern": "burst", "request_count": 30, "contention": "hot", "section_ids": [2, 1], "hot_section_count": 1}).json()
    final = finished(url, job["job_id"])
    assert final["status"] == "done", final["error"]
    assert final["db_check"]["registrations_in_db"] == 2 and final["db_check"]["successes_reported_by_client"] == 2
    assert final["db_check"]["invariants_ok"] is True


# ------------------------------------------------------------------ server settings

def test_server_settings_can_be_changed_between_runs(server_url, demo_on):
    changed = httpx.post(f"{server_url}/demo/os-layer", json={"queue_capacity": 3, "worker_count": 2, "db_semaphore_permits": 1})
    assert changed.json() == {"queue_capacity": 3, "worker_count": 2, "db_semaphore_permits": 1}
    status = httpx.get(f"{server_url}/os-layer/status").json()
    assert status["config"] == changed.json() and status["queue"]["capacity"] == 3
    # the new layer really serves requests
    section = httpx.get(f"{server_url}/demo/state").json()["sections"][0]["id"]
    assert httpx.post(f"{server_url}/registrations", json={"student_id": "STU001", "section_id": section}).status_code == 201
    for bad in ({"queue_capacity": 0, "worker_count": 2, "db_semaphore_permits": 1}, {"queue_capacity": 3, "worker_count": 65, "db_semaphore_permits": 1}):
        assert httpx.post(f"{server_url}/demo/os-layer", json=bad).status_code == 422
    # the settings are recorded in the result file of the next run
    job = finished(server_url, httpx.post(f"{server_url}/demo/runs", json=BURST).json()["job_id"])
    document = json.loads((demo_on / f"{job['experiment_id']}.json").read_text())
    assert document["server"]["os_layer"] == {"queue_capacity": 3, "worker_count": 2, "db_semaphore_permits": 1}


# ------------------------------------------------------------------ the test-suite runner

SAMPLE_XML = """<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="4">
<testcase classname="tests.test_api" name="test_a" time="0.010"/>
<testcase classname="tests.test_api" name="test_b" time="0.020"><failure message="assert 1 == 2">trace</failure></testcase>
<testcase classname="tests.test_concurrency" name="test_c[x]" time="0.000"><skipped message="needs MySQL/InnoDB row locks; the configured test database is sqlite"/></testcase>
<testcase classname="tests.test_registration" name="test_d" time="1.500"><error message="boom"/></testcase>
</testsuite></testsuites>"""


def test_junit_report_is_read_correctly():
    report = verification.parse_junit(SAMPLE_XML)
    assert report["counts"] == {"total": 4, "passed": 1, "failed": 1, "skipped": 1, "error": 1}
    by_name = {t["name"]: t for t in report["tests"]}
    assert by_name["test_c[x]"]["status"] == "SKIPPED" and "row locks" in by_name["test_c[x]"]["reason"]
    assert by_name["test_b"]["reason"] == "assert 1 == 2"
    assert by_name["test_a"]["file"] == "tests/test_api.py"


def test_live_lines_are_parsed():
    ok = verification.parse_live_line("tests/test_api.py::test_post_unknown_student_is_404 PASSED                         [  4%]")
    assert ok == {"file": "tests/test_api.py", "name": "test_post_unknown_student_is_404", "status": "PASSED", "reason": "", "percent": 4}
    skipped = verification.parse_live_line("tests/test_concurrency.py::test_x SKIPPED (needs MySQL/InnoDB row locks; sqlite) [ 10%]")
    assert skipped["status"] == "SKIPPED" and skipped["reason"] == "needs MySQL/InnoDB row locks; sqlite" and skipped["percent"] == 10
    assert verification.parse_live_line("collected 171 items") is None
    assert verification.parse_live_line("") is None


def test_the_suite_refuses_to_run_on_an_unsafe_database():
    check = verification.check_can_run
    with pytest.raises(verification.VerificationRefused, match="not set"):
        check({})
    with pytest.raises(verification.VerificationRefused, match="_test"):
        check({"TEST_DATABASE_URL": "mysql+pymysql://u:p@h/concurrentreg"})
    with pytest.raises(verification.VerificationRefused, match="same database"):
        check({"TEST_DATABASE_URL": "mysql+pymysql://u:p@h/x_test", "DATABASE_URL": "mysql+pymysql://u:p@h/x_test"})
    assert check({"TEST_DATABASE_URL": "mysql+pymysql://u:p@h/x_test", "DATABASE_URL": "mysql+pymysql://u:p@h/x"}).endswith("x_test")


def test_the_endpoint_refuses_when_the_test_database_is_the_app_database(server_url, demo_on):
    # conftest points DATABASE_URL at the test database, so here the two are the same: the endpoint must say no.
    assert os.environ["TEST_DATABASE_URL"] == os.environ["DATABASE_URL"]
    refused = httpx.post(f"{server_url}/demo/verify")
    assert refused.status_code == 409 and "same database" in refused.json()["detail"]
    assert httpx.get(f"{server_url}/demo/info").json()["tests"]["available"] is False
