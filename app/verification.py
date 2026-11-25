"""Run the project's own pytest suite on request and report what happened, test by test.

Used only by the demo controls (app/demo_api.py), never by the registration path.
The command is fixed (no user input reaches it) and it runs against TEST_DATABASE_URL, never the app database:
the tests wipe every table, so we refuse to run if both URLs are the same.
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_SECONDS = 900          # a run that takes longer than this is stopped
LIVE_LINES_KEPT = 400      # most recent finished tests kept for the live view

# One line of `pytest -v` output, e.g.
#   tests/test_api.py::test_post_unknown_student_is_404 PASSED                [  4%]
#   tests/test_concurrency.py::test_x SKIPPED (needs MySQL/InnoDB row locks; ...) [ 10%]
LINE = re.compile(
    r"^(?P<file>\S+?)::(?P<name>\S+)\s+(?P<status>PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)"
    r"(?P<rest>.*?)\s*(?:\[\s*(?P<percent>\d+)%\])?\s*$"
)


class VerificationRefused(Exception):
    """The suite must not run (for example: the test database is the app database)."""


def parse_live_line(line):
    """Turn one `pytest -v` result line into a dict, or None if the line is not a test result."""
    match = LINE.match(line.rstrip())
    if not match:
        return None
    reason = match.group("rest").strip()
    if reason.startswith("(") and reason.endswith(")"):
        reason = reason[1:-1]
    else:
        reason = ""
    return {
        "file": match.group("file"), "name": match.group("name"), "status": match.group("status"),
        "reason": reason, "percent": int(match.group("percent")) if match.group("percent") else None,
    }


def parse_junit(xml_text):
    """Read pytest's JUnit XML into counts and one record per test."""
    root = ET.fromstring(xml_text)
    tests = []
    for case in root.iter("testcase"):
        status, reason = "PASSED", ""
        for child in case:
            if child.tag == "skipped":
                status, reason = "SKIPPED", child.get("message", "")
            elif child.tag == "failure":
                status, reason = "FAILED", (child.get("message") or "")[:300]
            elif child.tag == "error":
                status, reason = "ERROR", (child.get("message") or "")[:300]
        file = (case.get("classname") or "").replace(".", "/") + ".py"
        tests.append({"file": file, "name": case.get("name"), "status": status, "reason": reason, "time_s": float(case.get("time") or 0)})
    counts = {"total": len(tests)}
    for label in ("PASSED", "FAILED", "SKIPPED", "ERROR"):
        counts[label.lower()] = sum(1 for t in tests if t["status"] == label)
    return {"counts": counts, "tests": tests}


def database_dialect(url):
    """'mysql', 'sqlite', ... from a SQLAlchemy URL (no connection is opened)."""
    return (url or "").split(":", 1)[0].split("+", 1)[0] or "unknown"


@dataclass
class VerificationJob:
    job_id: str
    status: str = "running"                      # running | done | failed
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    started_monotonic: float = field(default_factory=time.monotonic)
    finished_monotonic: float = None
    dialect: str = "unknown"
    live: list = field(default_factory=list)     # finished tests so far, newest last
    percent: int = 0
    report: dict = None                          # parse_junit() output once finished
    error: str = None
    output_tail: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self):
        with self.lock:
            live_counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
            for item in self.live:
                key = item["status"].lower()
                key = "passed" if key in ("xpass",) else "skipped" if key == "xfail" else key
                live_counts[key] = live_counts.get(key, 0) + 1
            end = self.finished_monotonic or time.monotonic()
            return {
                "job_id": self.job_id, "status": self.status, "started_at": self.started_at,
                "elapsed_s": round(end - self.started_monotonic, 2), "dialect": self.dialect,
                "percent": 100 if self.status == "done" else self.percent,
                "live_counts": live_counts, "recent": self.live[-60:], "report": self.report,
                "error": self.error, "output_tail": self.output_tail[-12:],
            }


def check_can_run(environ=None):
    """Return the test database URL, or raise VerificationRefused with the reason."""
    environ = os.environ if environ is None else environ
    test_url = environ.get("TEST_DATABASE_URL", "")
    if not test_url:
        raise VerificationRefused("TEST_DATABASE_URL is not set on the server, so there is no safe database to test on.")
    if not test_url.rsplit("/", 1)[-1].endswith("_test"):
        raise VerificationRefused("TEST_DATABASE_URL must name a database that ends in _test (the tests wipe every table).")
    if test_url == environ.get("DATABASE_URL"):
        raise VerificationRefused("TEST_DATABASE_URL is the same database as the running app; refusing to wipe it.")
    return test_url


def start_verification(job_id, environ=None):
    """Start the suite in a background thread and return its job. Raises VerificationRefused first if unsafe."""
    test_url = check_can_run(environ)
    job = VerificationJob(job_id=job_id, dialect=database_dialect(test_url))
    threading.Thread(target=_run, args=(job,), daemon=True, name=f"verify-{job_id}").start()
    return job


def _run(job):
    xml_path = os.path.join(tempfile.gettempdir(), f"creg-verify-{job.job_id}.xml")
    command = [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", f"--junitxml={xml_path}"]
    try:
        process = subprocess.Popen(
            command, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        timer = threading.Timer(MAX_SECONDS, process.kill)
        timer.start()
        try:
            for line in process.stdout:
                item = parse_live_line(line)
                with job.lock:
                    if item:
                        job.live.append(item)
                        if len(job.live) > LIVE_LINES_KEPT:
                            job.live = job.live[-LIVE_LINES_KEPT:]
                        if item["percent"] is not None:
                            job.percent = item["percent"]
                    elif line.strip():
                        job.output_tail.append(line.rstrip()[:240])
                        job.output_tail = job.output_tail[-40:]
            code = process.wait()
        finally:
            timer.cancel()
        with open(xml_path) as handle:
            report = parse_junit(handle.read())
        with job.lock:
            job.report = report
            job.status = "done"
            job.error = None if code == 0 else f"pytest exited with code {code} (see failures)"
    except Exception as error:  # report the problem instead of hanging the UI
        with job.lock:
            job.status = "failed"
            job.error = f"{type(error).__name__}: {error}"
    finally:
        job.finished_monotonic = time.monotonic()
        try:
            os.remove(xml_path)
        except OSError:
            pass
