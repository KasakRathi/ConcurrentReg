"""MySQL/InnoDB-only verification. Skipped, with a reason, on any other database.

The capacity and request numbers here are small test-fixture values, not research parameters.
"""
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import models
from app.database import SessionLocal
from tests.conftest import count_registrations, max_requests_in_flight, requires_mysql
from workload import workload_generator as wg

pytestmark = requires_mysql


def test_all_tables_use_innodb(db):
    rows = db.execute(text(
        "SELECT table_name, engine FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name IN "
        "('students', 'course_sections', 'registrations')"
    )).all()
    engines = {name.lower(): engine for name, engine in rows}
    print(f"\nstorage engines: {engines}")
    assert engines == {"students": "InnoDB", "course_sections": "InnoDB", "registrations": "InnoDB"}


def count_transactions_waiting_for_a_lock():
    # A separate session, so looking never touches the session that holds the lock.
    observer = SessionLocal()
    try:
        return observer.execute(text(
            "SELECT COUNT(*) FROM information_schema.innodb_trx WHERE trx_state = 'LOCK WAIT'"
        )).scalar()
    finally:
        observer.close()


def test_capacity_one_with_more_requests_than_seats_through_the_api(server_url, db):
    section = models.CourseSection(
        course_code="ONESEAT", course_name="One seat (test)", capacity=1, available_seats=1,
    )
    db.add(section)
    db.commit()
    try:
        count_transactions_waiting_for_a_lock()   # probe the privilege before taking any lock
    except OperationalError:
        pytest.skip("needs the MySQL PROCESS privilege to read information_schema.innodb_trx")
    request_count = 4   # more simultaneous requests than seats (test-fixture value)
    config = wg.WorkloadConfig(
        base_url=server_url, request_count=request_count, concurrency=request_count, pattern="burst",
        contention="hot", section_ids=[section.id], student_count=request_count, seed=1,
    )
    wg.validate_config(config)
    requests = wg.generate_requests(config)
    outcome = {}

    # Hold the section's row lock from a separate connection (backend untouched) so that
    # all requests are inside the server at once, then watch MySQL itself report them waiting.
    db.query(models.CourseSection).filter_by(id=section.id).with_for_update().one()
    runner = threading.Thread(target=lambda: outcome.update(zip(("results", "elapsed"), wg.run_workload(requests, config))))
    runner.start()
    waiting = 0
    deadline = time.monotonic() + 5
    while waiting < request_count and time.monotonic() < deadline:
        time.sleep(0.25)   # InnoDB serves a cached trx list if read more often than every ~0.1 s
        waiting = count_transactions_waiting_for_a_lock()
    db.rollback()   # release the lock; the waiting transactions now run one after another
    runner.join()

    results = outcome["results"]
    categories = sorted(result["category"] for result in results)
    print(f"\nserver-side transactions in LOCK WAIT while lock was held: {waiting}")
    print(f"client-side peak requests in flight: {max_requests_in_flight(results)}")
    print(f"categories: {categories}")

    assert waiting == request_count                      # InnoDB itself saw all of them blocked on the row lock
    assert max_requests_in_flight(results) == request_count
    assert categories == [wg.COURSE_FULL] * 3 + [wg.SUCCESS]
    # Persisted state, not just HTTP answers:
    db.rollback()
    section_row = db.get(models.CourseSection, section.id)
    db.refresh(section_row)
    assert section_row.available_seats == 0
    assert count_registrations(db, section.id) == 1       # successful registrations <= capacity
    registered = db.query(models.Registration.student_id).filter_by(section_id=section.id).all()
    assert len({student_pk for (student_pk,) in registered}) == len(registered)   # no duplicate rows
