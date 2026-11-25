"""Run the workload generator against the real Day 1 backend (in-process server, test database)."""
import json
import threading
import time

from app import models
from tests.conftest import count_registrations, get_section, max_requests_in_flight, requires_mysql
from workload import workload_generator as wg


@requires_mysql
def test_hot_workload_against_real_backend_keeps_day1_invariants(server_url, db):
    # Section 2 is CSE302 (capacity 2). Six students all ask for it at once.
    config = wg.WorkloadConfig(base_url=server_url, request_count=6, concurrency=3, pattern="burst",
                               contention="hot", section_ids=[2], seed=1)
    wg.validate_config(config)

    results, elapsed = wg.run_workload(wg.generate_requests(config), config)
    summary = wg.summarize_results(results, elapsed)

    assert summary["total_requests"] == 6
    assert summary["category_counts"][wg.SUCCESS] == 2
    assert summary["category_counts"][wg.COURSE_FULL] == 4
    assert summary["category_counts"][wg.UNKNOWN] == 0
    assert summary["category_counts"][wg.SERVER_ERROR] == 0
    # The generator only reports. The database confirms the backend kept its invariants.
    assert count_registrations(db, 2) == 2
    assert get_section(db, "CSE302").available_seats == 0


@requires_mysql
def test_requests_really_overlap_when_the_section_is_locked(server_url, db):
    config = wg.WorkloadConfig(base_url=server_url, request_count=5, concurrency=5, pattern="burst",
                               contention="hot", section_ids=[1], seed=1)   # CSE301 has 5 seats
    requests = wg.generate_requests(config)
    outcome = {}

    # Hold the section's row lock so that every registration request has to wait for it
    # on the server. They are then all in flight together, which we can see from timestamps.
    db.query(models.CourseSection).filter_by(id=1).with_for_update().one()
    runner = threading.Thread(target=lambda: outcome.update(zip(("results", "elapsed"), wg.run_workload(requests, config))))
    runner.start()
    time.sleep(0.5)
    db.rollback()   # release the lock
    runner.join()

    results = outcome["results"]
    print(f"\nmax requests in flight: {max_requests_in_flight(results)}")
    assert max_requests_in_flight(results) == 5
    assert all(result["latency_ms"] >= 400 for result in results)   # all waited for the lock
    assert [r["category"] for r in results] == [wg.SUCCESS] * 5
    assert count_registrations(db, 1) == 5


def test_cli_run_saves_a_readable_result_file_and_is_reproducible(server_url, tmp_path):
    arguments = ["--base-url", server_url, "--requests", "4", "--concurrency", "2",
                 "--pattern", "steady", "--rate", "50", "--contention", "independent",
                 "--seed", "9", "--output-dir", str(tmp_path)]

    assert wg.main(arguments) == 0
    assert wg.main(arguments) == 0

    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 2
    first, second = (json.loads(path.read_text()) for path in files)
    assert len(first["results"]) == 4
    assert first["config"]["seed"] == 9
    assert first["summary"]["total_requests"] == 4
    # Same seed + same config => same logical request sequence (timing of results will differ).
    assert first["generated_requests"] == second["generated_requests"]


def test_unreachable_api_is_an_experiment_level_failure(tmp_path):
    arguments = ["--base-url", "http://127.0.0.1:1", "--requests", "3", "--concurrency", "2",
                 "--timeout", "1", "--output-dir", str(tmp_path)]
    assert wg.main(arguments) == 1
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["summary"]["category_counts"][wg.CONNECTION_ERROR] == 3   # recorded, not lost


def test_invalid_cli_configuration_exits_before_sending_anything(tmp_path):
    assert wg.main(["--requests", "-1", "--output-dir", str(tmp_path)]) == 2
    assert list(tmp_path.glob("*.json")) == []
