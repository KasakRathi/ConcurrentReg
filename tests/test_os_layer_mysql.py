"""The Day 3 OS layer with the REAL Day 1 registration transaction on MySQL/InnoDB.

Skipped, with a visible reason, on any other database: these tests rely on InnoDB row locks.
The Day 2 workload generator plays the clients. The layer's own counters (layer.snapshot())
show what the SERVER did, which is not the same thing as what the clients did.
The numbers below are test-fixture values, not research parameters.
"""
import logging
import threading
from collections import Counter

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import models
from app import registration_service
from app.database import SessionLocal, engine
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import INTERNAL_ERROR_MESSAGE, OSConcurrencyLayer
from app.registration_service import DUPLICATE, ERROR, FULL, SUCCESS
from tests.conftest import (add_students, count_innodb_lock_waits, count_registrations, get_section, log_events,
                            max_requests_in_flight, peak_overlap, requires_mysql, wait_until)
from workload import workload_generator as wg

pytestmark = requires_mysql


def add_section(db, course_code, capacity):
    section = models.CourseSection(course_code=course_code, course_name=f"{course_code} (test)",
                                   capacity=capacity, available_seats=capacity)
    db.add(section)
    db.commit()
    return section.id


def run_through_layer(os_config, requests):
    """Submit (student_code, section_id) pairs all at once through a started layer."""
    layer = OSConcurrencyLayer(os_config)
    layer.start()
    try:
        futures = [layer.submit(student_code, section_id) for student_code, section_id in requests]
        results = [future.result(timeout=60) for future in futures]
    finally:
        layer.stop()
    return results, layer.snapshot()


# --------------------------------------------------- correctness through the layer

def test_concurrent_registrations_through_the_layer_never_oversell(db):
    section_id = add_section(db, "OS10", capacity=10)
    students = [f"OSA{number:02d}" for number in range(30)]
    for code in students:
        db.add(models.Student(student_id=code, name=code))
    db.commit()

    results, snapshot = run_through_layer(
        OSLayerConfig(queue_capacity=64, worker_count=6, db_semaphore_permits=3),
        [(code, section_id) for code in students])

    assert Counter(result.code for result in results) == {SUCCESS: 10, FULL: 20}
    assert count_registrations(db, section_id) == 10
    assert get_section(db, "OS10").available_seats == 0
    assert snapshot["workers"]["jobs_finished"] == 30
    assert snapshot["workers"]["max_active"] <= 6
    assert snapshot["db_semaphore"]["max_in_critical_section"] <= 3
    assert snapshot["queue"]["max_depth"] <= 64


def test_same_student_twice_at_once_through_the_layer_registers_once(db):
    section_id = get_section(db, "CSE301").id          # capacity 5, so seats never run out

    results, _snapshot = run_through_layer(
        OSLayerConfig(queue_capacity=8, worker_count=4, db_semaphore_permits=4),
        [("STU001", section_id), ("STU001", section_id)])

    assert sorted(result.code for result in results) == [DUPLICATE, SUCCESS]
    assert count_registrations(db, section_id) == 1
    assert get_section(db, "CSE301").available_seats == 4


def test_last_seat_over_http_with_day2_clients_does_not_oversell(start_server, db):
    section_id = add_section(db, "LAST1", capacity=1)
    url, layer = start_server(OSLayerConfig(queue_capacity=16, worker_count=4, db_semaphore_permits=2))
    config = wg.WorkloadConfig(base_url=url, request_count=8, concurrency=8, pattern="burst",
                               contention="hot", section_ids=[section_id], student_count=8, seed=3)
    wg.validate_config(config)

    results, elapsed = wg.run_workload(wg.generate_requests(config), config)
    counts = wg.summarize_results(results, elapsed)["category_counts"]

    assert counts[wg.SUCCESS] == 1 and counts[wg.COURSE_FULL] == 7
    assert count_registrations(db, section_id) == 1
    assert get_section(db, "LAST1").available_seats == 0


# ----------------------------------- server-side limits exercised by Day 2 clients

def test_day2_clients_saturate_the_server_side_limits(start_server, db):
    add_students(db, 11, 20)            # STU001..STU020 exist, so 12 requests can all use different students
    queue_capacity, worker_count, permits, request_count = 4, 3, 2, 12
    url, layer = start_server(OSLayerConfig(queue_capacity, worker_count, permits))
    config = wg.WorkloadConfig(base_url=url, request_count=request_count, concurrency=request_count,
                               pattern="burst", contention="hot", section_ids=[1], student_count=20, seed=1)
    wg.validate_config(config)
    requests = wg.generate_requests(config)
    outcome = {}

    # Hold CSE301's row lock from the test (the backend is not touched). Workers that reach the
    # database block there, so the server-side limits show up in the layer's counters.
    db.query(models.CourseSection).filter_by(id=1).with_for_update().one()
    runner = threading.Thread(target=lambda: outcome.update(zip(("results", "elapsed"), wg.run_workload(requests, config))))
    runner.start()

    def saturated():
        snap = layer.snapshot()
        return (snap["workers"]["active"] == worker_count
                and snap["db_semaphore"]["in_critical_section"] == permits
                and snap["db_semaphore"]["waiting"] == worker_count - permits
                and snap["queue"]["accepted"] + snap["queue"]["rejected_queue_full"] == request_count)

    try:
        reached = wait_until(saturated, timeout_seconds=15)
        while_blocked = layer.snapshot()
    finally:
        db.rollback()                   # release the lock so the accepted requests can finish
        runner.join(timeout=30)

    assert reached, f"the layer never reached the expected saturated state: {while_blocked}"
    # While the lock was held: 3 workers busy, 2 inside the DB section, 1 waiting for a permit.
    assert while_blocked["workers"]["active"] == 3
    assert while_blocked["db_semaphore"]["in_critical_section"] == 2
    assert while_blocked["db_semaphore"]["waiting"] == 1
    assert while_blocked["queue"]["depth"] <= queue_capacity

    results = outcome["results"]
    categories = Counter(result["category"] for result in results)
    final = layer.snapshot()
    accepted, rejected = final["queue"]["accepted"], final["queue"]["rejected_queue_full"]

    # Nothing is lost: every request was either accepted or refused by the full queue.
    assert accepted + rejected == request_count
    assert accepted <= worker_count + queue_capacity       # the system never held more than workers + queue
    assert rejected >= request_count - (worker_count + queue_capacity)
    assert categories[wg.QUEUE_FULL] == rejected
    assert categories[wg.SUCCESS] + categories[wg.COURSE_FULL] == accepted
    assert categories[wg.SUCCESS] == min(accepted, 5)       # CSE301 has 5 seats
    for unexpected in (wg.SERVER_ERROR, wg.CLIENT_ERROR, wg.UNKNOWN, wg.TIMEOUT, wg.CONNECTION_ERROR):
        assert categories[unexpected] == 0
    # The database stayed correct.
    assert count_registrations(db, 1) == categories[wg.SUCCESS]
    assert get_section(db, "CSE301").available_seats == 5 - categories[wg.SUCCESS]
    # Server-side limits were reached and never exceeded during the whole run.
    assert final["workers"]["max_active"] == 3
    assert final["db_semaphore"]["max_in_critical_section"] == 2
    assert final["queue"]["max_depth"] <= queue_capacity
    # Client concurrency is not server concurrency: more client requests were in flight than the server had workers.
    assert max_requests_in_flight(results) > final["workers"]["max_active"]


def test_day2_burst_without_any_artificial_hold_respects_the_limits(start_server, db):
    add_students(db, 11, 40)
    url, layer = start_server(OSLayerConfig(queue_capacity=64, worker_count=4, db_semaphore_permits=2))
    config = wg.WorkloadConfig(base_url=url, request_count=40, concurrency=20, pattern="burst",
                               contention="hot", section_ids=[1], student_count=40, seed=7)
    wg.validate_config(config)

    results, elapsed = wg.run_workload(wg.generate_requests(config), config)
    counts = wg.summarize_results(results, elapsed)["category_counts"]
    assert wait_until(lambda: layer.snapshot()["workers"]["jobs_finished"] == 40)
    status = httpx.get(url + "/os-layer/status").json()

    assert counts[wg.SUCCESS] == 5 and counts[wg.COURSE_FULL] == 35 and counts[wg.QUEUE_FULL] == 0
    assert count_registrations(db, 1) == 5
    assert get_section(db, "CSE301").available_seats == 0
    assert status["config"] == {"queue_capacity": 64, "worker_count": 4, "db_semaphore_permits": 2}
    assert status["queue_wait"]["jobs_dequeued"] == 40
    # 20 clients ran at once, but the server never used more than its own limits.
    assert status["workers"]["max_active"] <= 4
    assert status["db_semaphore"]["max_in_critical_section"] <= 2
    assert status["queue"]["max_depth"] <= 64


# ======================================================================================
# End-to-end evidence: a section with exactly ONE seat, real HTTP, every Day 3 layer,
# real MySQL/InnoDB. The Day 2 generator is the client side; the layer's own counters,
# InnoDB's own view and the log lines are the server side.
# The numbers (8 clients, 4 workers, ...) are test-fixture values, not research parameters.
# ======================================================================================

def run_capacity_one_scenario(start_server, db, os_config, request_count=8, watch_innodb=False):
    """Send `request_count` simultaneous Day 2 clients at a section with exactly one seat.

    The test holds that section's row lock (the backend is not touched), so the accepted requests
    are genuinely in flight together and the server's limits show up in its counters. Then the
    lock is released and the requests finish. Returns everything that was observed.
    """
    section_id = add_section(db, "ONESEAT", capacity=1)
    url, layer = start_server(os_config)
    config = wg.WorkloadConfig(base_url=url, request_count=request_count, concurrency=request_count,
                               pattern="burst", contention="hot", section_ids=[section_id],
                               student_count=request_count, seed=11, timeout_seconds=30)
    wg.validate_config(config)
    requests = wg.generate_requests(config)
    outcome = {}
    evidence = {"section_id": section_id, "layer": layer, "request_count": request_count, "lock_waits": []}

    def saturated():
        # Every request has been answered or is waiting inside the server, and the server is as busy as its
        # limits allow: busy workers, permits all taken, the rest of the busy workers waiting for a permit.
        snap = layer.snapshot()
        accepted, refused = snap["queue"]["accepted"], snap["queue"]["rejected_queue_full"]
        active = snap["workers"]["active"]
        inside = snap["db_semaphore"]["in_critical_section"]
        return (accepted + refused == request_count
                and active == min(os_config.worker_count, accepted)
                and inside == min(os_config.db_semaphore_permits, active)
                and snap["db_semaphore"]["waiting"] == active - inside)

    db.query(models.CourseSection).filter_by(id=section_id).with_for_update().one()   # the test holds the row lock
    runner = threading.Thread(target=lambda: outcome.update(zip(("results", "elapsed"), wg.run_workload(requests, config))))
    runner.start()
    try:
        evidence["reached_saturation"] = wait_until(saturated, timeout_seconds=15)
        evidence["while_blocked"] = layer.snapshot()
        if watch_innodb:
            expected = evidence["while_blocked"]["db_semaphore"]["in_critical_section"]
            wait_until(lambda: evidence["lock_waits"].append(count_innodb_lock_waits()) or evidence["lock_waits"][-1] == expected,
                       timeout_seconds=15, interval_seconds=0.25)
    finally:
        db.rollback()                 # release the lock: the accepted requests can now finish
        runner.join(timeout=60)

    assert not runner.is_alive(), "the workload did not finish after the lock was released"
    accepted = layer.snapshot()["queue"]["accepted"]
    assert wait_until(lambda: layer.snapshot()["workers"]["jobs_finished"] == accepted
                      and layer.snapshot()["workers"]["active"] == 0)
    evidence["results"] = outcome["results"]
    evidence["final"] = layer.snapshot()

    # What is really stored in MySQL afterwards:
    db.rollback()
    evidence["seats_left"] = db.get(models.CourseSection, section_id).available_seats
    evidence["registered_students"] = [code for (code,) in db.query(models.Student.student_id)
                                       .join(models.Registration, models.Registration.student_id == models.Student.id)
                                       .filter(models.Registration.section_id == section_id)]
    evidence["duplicate_rows"] = db.execute(text(
        "SELECT COUNT(*) FROM (SELECT student_id FROM registrations WHERE section_id = :s "
        "GROUP BY student_id HAVING COUNT(*) > 1) d"), {"s": section_id}).scalar()
    return evidence


CAPACITY_ONE_CONFIGS = [
    # The queue is big enough for every request: 4 workers busy, 2 inside the DB section, 2 waiting, 4 queued.
    pytest.param(OSLayerConfig(queue_capacity=8, worker_count=4, db_semaphore_permits=2), id="every-request-fits"),
    # A tiny queue: the queue itself must turn some requests away (the refusal is the bounded-queue behaviour).
    pytest.param(OSLayerConfig(queue_capacity=2, worker_count=2, db_semaphore_permits=1), id="queue-overflows"),
]


@pytest.mark.parametrize("os_config", CAPACITY_ONE_CONFIGS)
def test_capacity_one_end_to_end_through_every_day3_layer(start_server, db, caplog, os_config):
    caplog.set_level(logging.INFO)
    workers, permits, capacity = os_config.worker_count, os_config.db_semaphore_permits, os_config.queue_capacity

    # --- the environment really is MySQL/InnoDB, in an isolated test database
    assert engine.dialect.name == "mysql"
    assert db.execute(text("SELECT DATABASE()")).scalar().endswith("_test")
    engines = dict(db.execute(text("SELECT table_name, engine FROM information_schema.tables WHERE table_schema = DATABASE()")).all())
    assert {engines[name] for name in ("students", "course_sections", "registrations")} == {"InnoDB"}
    print(f"\nenvironment: MySQL {db.execute(text('SELECT VERSION()')).scalar()}, InnoDB tables, database {db.execute(text('SELECT DATABASE()')).scalar()}")

    e = run_capacity_one_scenario(start_server, db, os_config)
    results, final, while_blocked = e["results"], e["final"], e["while_blocked"]
    accepted, refused = final["queue"]["accepted"], final["queue"]["rejected_queue_full"]
    categories = Counter(result["category"] for result in results)
    print(f"accepted={accepted} refused={refused} categories={dict(categories)}")
    print(f"while blocked: workers active={while_blocked['workers']['active']}, inside DB section={while_blocked['db_semaphore']['in_critical_section']}, "
          f"waiting for a permit={while_blocked['db_semaphore']['waiting']}, queue depth={while_blocked['queue']['depth']}")

    # --- correctness: one seat, many simultaneous clients
    assert e["reached_saturation"], f"the server never reached the expected saturated state: {while_blocked}"
    assert accepted + refused == e["request_count"]
    assert categories[wg.SUCCESS] == 1                                   # exactly one client got the seat
    assert categories[wg.COURSE_FULL] == accepted - 1                    # every other accepted request was told "full"
    assert categories[wg.QUEUE_FULL] == refused                          # the rest were turned away by the full queue
    for unexpected in (wg.SERVER_ERROR, wg.CLIENT_ERROR, wg.UNKNOWN, wg.TIMEOUT, wg.CONNECTION_ERROR, wg.DUPLICATE):
        assert categories[unexpected] == 0
    assert e["seats_left"] == 0
    assert count_registrations(db, e["section_id"]) == 1                 # exactly one registration record ...
    assert e["duplicate_rows"] == 0                                      # ... and no duplicates: no overselling
    winner = next(result["student_id"] for result in results if result["category"] == wg.SUCCESS)
    assert e["registered_students"] == [winner]                          # the stored row belongs to the client told SUCCESS

    # --- overlap: the clients were really in flight together, and more of them than the server had workers
    peak_clients = max_requests_in_flight(results)
    assert peak_clients >= accepted
    if accepted > workers:
        assert peak_clients > final["workers"]["max_active"]             # client concurrency is not server concurrency

    # --- bounded queue
    assert refused >= e["request_count"] - (workers + capacity)          # nothing beyond workers + capacity was ever held
    assert accepted <= workers + capacity
    if capacity >= e["request_count"] - workers:
        assert refused == 0                                              # it fitted, so nothing was refused
    else:
        assert refused >= 1                                              # queue-full really happened and was observable
    assert while_blocked["queue"]["depth"] <= capacity
    assert final["queue"]["max_depth"] <= capacity
    assert final["queue"]["max_depth"] >= while_blocked["queue"]["depth"]
    assert final["queue"]["depth"] == 0

    # --- worker pool
    assert while_blocked["workers"]["active"] == min(workers, accepted)
    assert final["workers"]["max_active"] == workers                     # the bound was reached ...
    assert final["workers"]["max_active"] <= workers                     # ... and never exceeded
    assert final["workers"]["jobs_started"] == final["workers"]["jobs_finished"] == accepted
    assert final["workers"]["unexpected_errors"] == 0 and final["workers"]["alive"] == workers

    # --- DB semaphore
    assert while_blocked["db_semaphore"]["in_critical_section"] == min(permits, accepted)
    assert final["db_semaphore"]["max_in_critical_section"] == permits   # reached, never exceeded
    assert final["db_semaphore"]["acquisitions"] == accepted             # every accepted request passed through it
    assert final["db_semaphore"]["in_critical_section"] == 0 and final["db_semaphore"]["waiting"] == 0   # all permits returned
    assert final["db_semaphore"]["wait_max_s"] > 0                       # some workers really waited for a permit

    # --- log lines: the same requests, seen from the OS layer and from the Day 1 registration service
    layer_lines = log_events(caplog, "os_layer", "os_layer_request")
    refusal_lines = log_events(caplog, "os_layer", "os_layer_rejected")
    day1_lines = log_events(caplog, "registration", "registration")
    assert len(layer_lines) == accepted and len(refusal_lines) == refused
    assert {line["request_id"] for line in layer_lines} == {line["request_id"] for line in day1_lines}   # Day 1 code ran for exactly these
    assert Counter(line["result"] for line in layer_lines) == {SUCCESS: 1, FULL: accepted - 1}
    assert {line["worker"] for line in layer_lines} <= {f"worker-{n}" for n in range(1, workers + 1)}
    assert {(l["queue_capacity"], l["worker_count"], l["db_semaphore_permits"]) for l in layer_lines + refusal_lines} == {(capacity, workers, permits)}
    busy = peak_overlap([(line["worker_started_at_s"], line["worker_finished_at_s"]) for line in layer_lines])
    inside = peak_overlap([(line["semaphore_acquired_at_s"], line["worker_finished_at_s"]) for line in layer_lines])
    print(f"from the log lines alone: peak workers busy={busy}, peak inside the DB section={inside}; "
          f"client-side peak in flight={peak_clients}; semaphore acquisitions={final['db_semaphore']['acquisitions']}, "
          f"largest permit wait={final['db_semaphore']['wait_max_s'] * 1000:.1f} ms, largest queue wait={final['queue_wait']['max_s'] * 1000:.1f} ms")
    assert busy == min(workers, accepted) and inside == permits          # the log alone shows the same limits
    assert max(line["queue_wait_ms"] for line in layer_lines) > 0 and max(line["semaphore_wait_ms"] for line in layer_lines) > 0


def test_innodb_never_sees_more_blocked_transactions_than_the_semaphore_allows(start_server, db):
    try:
        count_innodb_lock_waits()
    except OperationalError:
        pytest.skip("needs the MySQL PROCESS privilege to read information_schema.innodb_trx")
    os_config = OSLayerConfig(queue_capacity=8, worker_count=4, db_semaphore_permits=2)

    e = run_capacity_one_scenario(start_server, db, os_config, watch_innodb=True)

    readings = e["lock_waits"]
    print(f"\nInnoDB transactions in LOCK WAIT, successive readings: {readings} (workers active: {e['while_blocked']['workers']['active']})")
    assert e["while_blocked"]["workers"]["active"] == 4                  # four workers are busy ...
    assert readings and readings[-1] == 2                                # ... but InnoDB sees only 2 transactions waiting on the row lock
    assert max(readings) <= 2                                            # never more than the permits
    assert Counter(r["category"] for r in e["results"])[wg.SUCCESS] == 1
    assert count_registrations(db, e["section_id"]) == 1 and e["seats_left"] == 0


# ======================================================================================
# A REAL MySQL failure inside the protected section (not a simulated one)
# ======================================================================================

def test_a_real_mysql_error_inside_the_db_section_leaks_neither_permit_nor_worker(db):
    layer = OSConcurrencyLayer(OSLayerConfig(queue_capacity=4, worker_count=2, db_semaphore_permits=1))
    layer.start()
    admin = SessionLocal()
    holder_connection = db.execute(text("SELECT CONNECTION_ID()")).scalar()
    db.query(models.CourseSection).filter_by(id=1).with_for_update().one()     # the test holds CSE301's row lock

    def worker_connections_blocked_on_the_lock():
        rows = admin.execute(text("SHOW FULL PROCESSLIST")).all()
        admin.rollback()
        return [row[0] for row in rows if row[0] != holder_connection and row[4] == "Query" and row[7] and "FOR UPDATE" in row[7]]

    try:
        first = layer.submit("STU001", 1)     # takes the only permit and blocks on the row lock inside MySQL
        second = layer.submit("STU002", 1)    # waits for the permit
        assert wait_until(lambda: len(worker_connections_blocked_on_the_lock()) == 1)
        snap = layer.snapshot()["db_semaphore"]
        assert (snap["in_critical_section"], snap["waiting"]) == (1, 1)

        victim = worker_connections_blocked_on_the_lock()[0]
        admin.execute(text(f"KILL {victim}"))                                   # MySQL drops the worker's connection mid-transaction
        admin.commit()

        failed = first.result(timeout=15)
        assert failed.code == ERROR                                             # reported as an error, not lost or hung
        assert wait_until(lambda: layer.snapshot()["db_semaphore"]["acquisitions"] == 2)   # the permit was handed on to the waiting request
    finally:
        db.rollback()                                                           # release the row lock
    try:
        assert second.result(timeout=15).code == SUCCESS                        # the waiting request completes normally
        assert wait_until(lambda: layer.snapshot()["workers"]["active"] == 0)
        final = layer.snapshot()
    finally:
        layer.stop(timeout_seconds=5)   # short, so a failing test cannot stall
        admin.close()

    assert final["db_semaphore"]["in_critical_section"] == 0 and final["db_semaphore"]["waiting"] == 0
    assert final["workers"]["alive"] == 2 and final["workers"]["unexpected_errors"] == 0
    assert count_registrations(db, 1) == 1                                      # only the second request registered ...
    assert get_section(db, "CSE301").available_seats == 4                       # ... the killed transaction left nothing behind


def test_unexpected_error_while_holding_a_real_row_lock_releases_lock_permit_and_worker(db, monkeypatch):
    # Here the exception is NOT a database error that Day 1 handles: it is a bug-like Python error that
    # travels up through the semaphore block while the worker's MySQL transaction holds the section's
    # row lock. If the lock, the permit or the worker leaked, the next request could never finish.
    layer = OSConcurrencyLayer(OSLayerConfig(queue_capacity=4, worker_count=1, db_semaphore_permits=1))
    layer.start()

    def explode_after_the_row_lock_is_taken(db_session, student_pk, section_id):
        raise RuntimeError("simulated bug after the row lock was taken")

    try:
        monkeypatch.setattr(registration_service, "is_already_registered", explode_after_the_row_lock_is_taken)
        failed = layer.submit("STU001", 1).result(timeout=15)
        monkeypatch.undo()                                            # the real duplicate check is back

        assert failed.code == ERROR and failed.message == INTERNAL_ERROR_MESSAGE
        # With one worker and one permit, this request needs the same worker, the same permit and the
        # same row lock. It would hang until MySQL's lock-wait timeout (50 s) if any of them had leaked.
        after = layer.submit("STU002", 1).result(timeout=15)
        assert after.code == SUCCESS
        assert wait_until(lambda: layer.snapshot()["workers"]["active"] == 0)
        final = layer.snapshot()
    finally:
        layer.stop(timeout_seconds=5)

    assert final["db_semaphore"]["in_critical_section"] == 0 and final["db_semaphore"]["acquisitions"] == 2
    assert final["workers"]["alive"] == 1 and final["workers"]["unexpected_errors"] == 0
    assert count_registrations(db, 1) == 1                           # only STU002; the failed transaction was rolled back
    assert get_section(db, "CSE301").available_seats == 4
