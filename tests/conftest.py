import os

import pytest
from dotenv import load_dotenv

load_dotenv()

# The tests wipe every table, so only ever run them against a database whose
# name ends in "_test". This must happen before app.database is imported.
test_url = os.environ.get("TEST_DATABASE_URL", "")
if not test_url.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("Set TEST_DATABASE_URL to a database whose name ends with _test.")
os.environ["DATABASE_URL"] = test_url

import json  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import uvicorn  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.iasl.config import IASLConfig  # noqa: E402
from app.main import create_app  # noqa: E402
from app.os_layer.layer_config import OSLayerConfig  # noqa: E402
from app.seed import seed_dev_data  # noqa: E402

# Generous OS-layer limits for the Day 1/Day 2 tests, so the Day 3 layer never constrains them.
# These are test-fixture values, not research parameters.
GENEROUS_OS_CONFIG = OSLayerConfig(queue_capacity=64, worker_count=8, db_semaphore_permits=8)

# Which database the tests are really running on: "mysql", "sqlite", ...
DATABASE_DIALECT = engine.dialect.name

# Tests that depend on row-level locking (SELECT ... FOR UPDATE) only mean something on
# MySQL/InnoDB. SQLite has no row locks and ignores FOR UPDATE, so concurrent requests
# can overwrite each other's seat counts there. That is a SQLite limitation, not a
# ConcurrentReg defect, so these tests are skipped (with a visible reason) elsewhere.
requires_mysql = pytest.mark.skipif(
    DATABASE_DIALECT != "mysql",
    reason=f"needs MySQL/InnoDB row locks; the configured test database is {DATABASE_DIALECT}",
)


def pytest_report_header(config):
    return f"test database dialect: {DATABASE_DIALECT} (set TEST_DATABASE_URL to choose)"


@pytest.fixture(autouse=True)
def fresh_database():
    """Every test starts from the same freshly seeded database."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_dev_data(db)
    db.close()


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def get_section(db, course_code):
    db.rollback()  # end any old snapshot so we see the latest committed data
    return db.query(models.CourseSection).filter_by(course_code=course_code).one()


def count_registrations(db, section_id):
    db.rollback()
    return db.query(models.Registration).filter_by(section_id=section_id).count()


@pytest.fixture
def start_server():
    """Factory: start the real app with the given OS-layer settings on a free local port.

    Returns (url, os_layer). The server runs in a thread of this process, so a test can
    read os_layer.snapshot() directly. Every server started is stopped at the end of the test.
    """
    running = []

    def start(os_config, iasl_config=None):
        # IASL is explicitly OFF unless a test asks for it, so an IASL_ENABLED variable in the environment cannot leak in.
        application = create_app(os_config, iasl_config or IASLConfig())
        start.applications.append(application)   # lets a test reach application.state.iasl
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        running.append((server, thread))
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the test server did not start")
            time.sleep(0.01)
        return f"http://127.0.0.1:{port}", application.state.os_layer

    start.applications = []

    yield start
    for server, thread in running:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def server_url(start_server):
    url, _os_layer = start_server(GENEROUS_OS_CONFIG)
    return url


def wait_until(condition, timeout_seconds=10, interval_seconds=0.01):
    """Poll until condition() is true. Returns True, or False if the timeout passes first."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval_seconds)
    return condition()


def add_students(db, first_number, last_number):
    """Add students STU<first>..STU<last> (e.g. STU011), the naming the workload generator uses."""
    for number in range(first_number, last_number + 1):
        db.add(models.Student(student_id=f"STU{number:03d}", name=f"Test Student {number}"))
    db.commit()


def max_requests_in_flight(results):
    """Largest number of requests whose [start, end] intervals overlap at one moment."""
    events = []
    for result in results:
        events.append((result["start_offset_s"], 1))
        events.append((result["end_offset_s"], -1))
    in_flight = peak = 0
    for _, change in sorted(events):
        in_flight += change
        peak = max(peak, in_flight)
    return peak


def peak_overlap(intervals):
    """Largest number of (start, end) intervals that overlap at one moment."""
    events = [(start, 1) for start, _ in intervals] + [(end, -1) for _, end in intervals]
    open_now = peak = 0
    for _, change in sorted(events, key=lambda event: (event[0], event[1])):  # an end sorts before a start at the same instant
        open_now += change
        peak = max(peak, open_now)
    return peak


def log_events(caplog, logger_name, event_name):
    """The JSON log lines of one kind ("os_layer_request", "registration", ...) captured during a test."""
    found = []
    for record in caplog.records:
        if record.name == logger_name and record.getMessage().startswith("{"):
            data = json.loads(record.getMessage())
            if data.get("event") == event_name:
                found.append(data)
    return found


def count_innodb_lock_waits():
    """How many transactions InnoDB reports as waiting for a lock right now (needs the PROCESS privilege).

    Uses its own session. InnoDB serves a cached copy of this list when it is read more often than
    about every 0.1 s, so callers must poll slower than that.
    """
    observer = SessionLocal()
    try:
        return observer.execute(text(
            "SELECT COUNT(*) FROM information_schema.innodb_trx WHERE trx_state = 'LOCK WAIT'"
        )).scalar()
    finally:
        observer.close()
