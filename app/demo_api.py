"""Demo controls: let the dashboard drive the real system in front of an audience.

Nothing here is part of the registration path. It only ORCHESTRATES things that already exist:
  * the workload generator (workload/workload_generator.py) is run against this same server,
  * the database is re-seeded with app/seed.py,
  * the project's own pytest suite is run (app/verification.py).
It reads the database to check the correctness rules (seats never exceed capacity, no duplicate registrations).

Safety: everything except GET /demo/info is OFF unless the server is started with CREG_DEMO_CONTROLS=1,
because resetting the database and running a test suite must never be reachable on a normal deployment.
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app import models, verification
from app.database import SessionLocal, engine
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import OSConcurrencyLayer
from app.seed import reset_and_seed
from workload import workload_generator as generator

MAX_DEMO_REQUESTS = 5000
RESULT_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")   # an experiment id is a file name: no slashes, no dots-only


def controls_enabled():
    return os.environ.get("CREG_DEMO_CONTROLS") == "1"


def require_controls():
    if not controls_enabled():
        raise HTTPException(404, "Demo controls are disabled. Start the server with CREG_DEMO_CONTROLS=1.")


def results_dir():
    return os.environ.get("CREG_RESULTS_DIR", "results")


info_router = APIRouter(prefix="/demo")                                   # always available, read-only
router = APIRouter(prefix="/demo", dependencies=[Depends(require_controls)])


# ----------------------------------------------------------------------------- database facts

def database_facts():
    dialect = engine.dialect.name
    version = None
    try:
        with engine.connect() as connection:
            query = "SELECT VERSION()" if dialect == "mysql" else "SELECT sqlite_version()" if dialect == "sqlite" else None
            version = connection.execute(text(query)).scalar() if query else None
    except Exception:
        pass
    return {"dialect": dialect, "version": version, "name": engine.url.database and os.path.basename(str(engine.url.database)),
            "row_locks": dialect == "mysql"}


def database_state():
    """What is in the database right now, and whether the correctness rules hold. All of it comes from SQL."""
    db = SessionLocal()
    try:
        db.rollback()   # start a fresh snapshot: every query below sees the same moment
        sections = db.execute(select(models.CourseSection).order_by(models.CourseSection.id)).scalars().all()
        registered = dict(db.execute(select(models.Registration.section_id, func.count()).group_by(models.Registration.section_id)).all())
        repeated = db.execute(
            select(func.count()).select_from(
                select(models.Registration.student_id, models.Registration.section_id)
                .group_by(models.Registration.student_id, models.Registration.section_id)
                .having(func.count() > 1).subquery()
            )
        ).scalar()
        students = db.execute(select(func.count()).select_from(models.Student)).scalar()
        rows = [{
            "id": s.id, "course_code": s.course_code, "course_name": s.course_name, "capacity": s.capacity,
            "available_seats": s.available_seats, "registered": registered.get(s.id, 0),
        } for s in sections]
    finally:
        db.close()

    over = [r["course_code"] for r in rows if r["registered"] > r["capacity"]]
    drift = [r["course_code"] for r in rows if r["available_seats"] != r["capacity"] - r["registered"]]
    out_of_range = [r["course_code"] for r in rows if not 0 <= r["available_seats"] <= r["capacity"]]
    invariants = [
        {"id": "capacity", "label": "Registrations never exceed a section's capacity", "ok": not over,
         "detail": "every section is within capacity" if not over else f"over capacity: {', '.join(over)}"},
        {"id": "seats", "label": "Seats left = capacity - registrations", "ok": not drift,
         "detail": "the seat counter matches the stored registrations" if not drift else f"counter drift in: {', '.join(drift)}"},
        {"id": "range", "label": "0 <= seats left <= capacity", "ok": not out_of_range,
         "detail": "every counter is in range" if not out_of_range else f"out of range: {', '.join(out_of_range)}"},
        {"id": "unique", "label": "No student holds a section twice", "ok": repeated == 0,
         "detail": "no repeated (student, section) pair" if repeated == 0 else f"{repeated} repeated pair(s)"},
    ]
    return {
        "taken_at": datetime.now().isoformat(timespec="milliseconds"), "database": database_facts(),
        "sections": rows, "totals": {"students": students, "registrations": sum(r["registered"] for r in rows)},
        "invariants": invariants, "all_ok": all(i["ok"] for i in invariants),
    }


# ----------------------------------------------------------------------------- runs

class RunRequest(BaseModel):
    """The generator options the dashboard may set. Everything else keeps the generator's own default."""
    arrival_model: Literal["open", "closed"] = "open"
    pattern: Literal["steady", "burst", "ramp", "phases"] = "burst"
    request_count: int = 20
    rate: float = 10
    ramp_stages: int = 3
    phases: list[list[float]] = []
    concurrency: int = 100
    contention: Literal["hot", "independent", "mixed"] = "hot"
    section_ids: list[int] | None = None
    hot_section_count: int = 1
    hot_fraction: float = 0.5
    duplicate_fraction: float = 0.0
    student_count: int = 10
    virtual_users: int = 10
    think_time_min_s: float = 0.0
    think_time_max_s: float = 0.0
    seed: int = 42
    timeout_seconds: float = 5.0
    lateness_tolerance_ms: float = 50.0
    reset_first: bool = True


class RunJob:
    def __init__(self, job_id, config, reset_first, os_layer, iasl=None):
        self.job_id = job_id
        self.config = config
        self.reset_first = reset_first
        self.os_layer = os_layer
        self.iasl = iasl                   # the IASL runtime if it is enabled, else None
        self.status = "running"            # running | done | failed
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.started = time.monotonic()
        self.ended = None
        self.planned = generator.planned_request_count(config)
        self.baseline = counters(os_layer)
        self.experiment_id = None
        self.summary = None
        self.db_check = None
        self.error = None

    def as_dict(self):
        now = counters(self.os_layer)
        seen = (now["finished"] - self.baseline["finished"]) + (now["refused"] - self.baseline["refused"])
        done = self.status == "done"
        elapsed = (self.ended or time.monotonic()) - self.started
        return {
            "job_id": self.job_id, "status": self.status, "started_at": self.started_at, "reset_first": self.reset_first,
            "config": {k: getattr(self.config, k) for k in ("arrival_model", "pattern", "request_count", "rate", "contention", "seed", "concurrency", "virtual_users", "section_ids", "phases")},
            "progress": {
                "planned_requests": self.planned, "responses_seen": min(seen, self.planned) if not done else self.planned,
                "fraction": 1.0 if done else min(1.0, seen / self.planned) if self.planned else 0.0, "elapsed_s": round(elapsed, 2),
                "note": "Estimated from the server's own counters (finished + refused requests since the run began).",
            },
            "experiment_id": self.experiment_id, "summary": self.summary, "db_check": self.db_check, "error": self.error,
        }


def counters(os_layer):
    snap = os_layer.snapshot()
    # A request turned away by admission control is answered too, so it counts as progress (the block exists only with IASL on).
    refused = snap["queue"]["rejected_queue_full"] + snap.get("admission", {}).get("rejected", 0)
    return {"finished": snap["workers"]["jobs_finished"], "refused": refused}


_jobs = {}
_run_lock = threading.Lock()     # held for the whole life of a run: only one at a time
_current = {"run": None, "verify": None}
_verifications = {}


def _execute(job):
    """Runs in a background thread. Always releases the run lock."""
    try:
        config = job.config
        requests = generator.generate_requests(config)
        started_at = datetime.now()
        results, elapsed = generator.run_workload(requests, config)
        ended_at = datetime.now()
        summary = generator.summarize_results(results, elapsed, config)
        experiment_id = generator.make_experiment_id(config)
        os.makedirs(config.output_dir, exist_ok=True)
        path = os.path.join(config.output_dir, f"{experiment_id}.json")
        generator.save_results(path, experiment_id, config, requests, results, summary,
                               generator.build_run_info(config, requests, started_at, ended_at))
        generator.check_saved_results(path, len(requests))

        # Cross-check: did the database store exactly as many registrations as the client was told succeeded?
        state = database_state()
        db_check = {
            "registrations_in_db": state["totals"]["registrations"], "successes_reported_by_client": summary["successful_requests"],
            "match": state["totals"]["registrations"] == summary["successful_requests"] if job.reset_first else None,
            "invariants_ok": state["all_ok"],
            "note": None if job.reset_first else "The database was not reset first, so earlier registrations are included and the counts need not match.",
        }
        _add_context(path, job, db_check)
        job.summary = {k: summary[k] for k in ("total_requests", "successful_requests", "category_counts", "elapsed_seconds", "completed_requests_per_second", "latency_ms")}
        job.summary["valid_open_loop"] = (summary.get("open_loop") or {}).get("valid_open_loop")
        job.db_check = db_check
        job.experiment_id = experiment_id
        job.status = "done"
    except Exception as error:   # show the reason in the UI instead of hanging
        job.error = f"{type(error).__name__}: {error}"
        job.status = "failed"
    finally:
        job.ended = time.monotonic()
        _run_lock.release()


def _add_context(path, job, db_check):
    """Record, inside the result file, which server settings and database produced it (the generator cannot know)."""
    with open(path) as handle:
        document = json.load(handle)
    document["server"] = {
        "os_layer": job.os_layer.snapshot()["config"], "database": database_facts(),
        "iasl": job.iasl.describe() if job.iasl is not None else {"enabled": False},
        "started_via": "demo-api", "reset_first": job.reset_first, "db_check": db_check,
    }
    with open(path, "w") as handle:
        json.dump(document, handle, indent=2)


@router.post("/runs", status_code=202)
def start_run(body: RunRequest, request: Request):
    if verification_running():
        raise HTTPException(409, "The test suite is running; start an experiment when it finishes.")
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "An experiment is already running.")
    started = False
    try:
        if body.request_count > MAX_DEMO_REQUESTS:
            raise HTTPException(422, f"The demo caps a run at {MAX_DEMO_REQUESTS} requests.")
        if body.reset_first:
            reset_and_seed()
        db = SessionLocal()
        try:
            section_ids = body.section_ids or [s for (s,) in db.execute(select(models.CourseSection.id).order_by(models.CourseSection.id)).all()]
            students = db.execute(select(func.count()).select_from(models.Student)).scalar()
        finally:
            db.close()
        if body.student_count > students:
            raise HTTPException(422, f"student_count {body.student_count} is more than the {students} students in the database.")
        host, port = request.scope.get("server") or ("127.0.0.1", 8000)
        config = generator.WorkloadConfig(
            base_url=os.environ.get("CREG_SELF_URL") or f"http://127.0.0.1:{port}", request_count=body.request_count,
            concurrency=body.concurrency, arrival_model=body.arrival_model, pattern=body.pattern, phases=[list(p) for p in body.phases],
            lateness_tolerance_ms=body.lateness_tolerance_ms, virtual_users=body.virtual_users,
            think_time_min_s=body.think_time_min_s, think_time_max_s=body.think_time_max_s, contention=body.contention,
            student_count=body.student_count, section_ids=section_ids, hot_section_count=body.hot_section_count,
            hot_fraction=body.hot_fraction, duplicate_fraction=body.duplicate_fraction, rate=body.rate,
            ramp_stages=body.ramp_stages, seed=body.seed, timeout_seconds=body.timeout_seconds, output_dir=results_dir(),
        )
        try:
            generator.validate_config(config)
        except generator.ConfigError as error:
            raise HTTPException(422, str(error)) from None
        job = RunJob(uuid.uuid4().hex[:10], config, body.reset_first, request.app.state.os_layer,
                     getattr(request.app.state, "iasl", None))
        _jobs[job.job_id] = job
        _current["run"] = job.job_id
        threading.Thread(target=_execute, args=(job,), daemon=True, name=f"demo-run-{job.job_id}").start()
        started = True
        return job.as_dict()
    finally:
        if not started:
            _run_lock.release()


@router.get("/runs/current")
def current_run():
    job = _jobs.get(_current["run"])
    return job.as_dict() if job else {"status": "none"}


@router.get("/runs/{job_id}")
def get_run(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such run.")
    return job.as_dict()


# ----------------------------------------------------------------------------- state, reset, server settings

@info_router.get("/info")
def info(request: Request):
    try:
        verification.check_can_run()
        tests = {"available": True, "reason": None, "dialect": verification.database_dialect(os.environ.get("TEST_DATABASE_URL"))}
    except verification.VerificationRefused as refusal:
        tests = {"available": False, "reason": str(refusal), "dialect": None}
    return {
        "controls_enabled": controls_enabled(), "database": database_facts(), "os_layer": request.app.state.os_layer.snapshot()["config"],
        "generator_version": generator.GENERATOR_VERSION, "generator_revision": generator.generator_revision(), "tests": tests,
        "results_dir": results_dir() if controls_enabled() else None,
    }


@router.get("/state")
def state():
    return database_state()


@router.get("/registrations")
def registrations(limit: int = 200):
    """The stored registrations themselves (newest last), joined with the student and course codes. Read-only."""
    db = SessionLocal()
    try:
        db.rollback()
        query = (
            select(models.Registration.id, models.Student.student_id, models.CourseSection.course_code,
                   models.Registration.registered_at, models.Registration.status)
            .join(models.Student, models.Student.id == models.Registration.student_id)
            .join(models.CourseSection, models.CourseSection.id == models.Registration.section_id)
            .order_by(models.Registration.id).limit(max(1, min(limit, 500)))
        )
        rows = db.execute(query).all()
    finally:
        db.close()
    return {"items": [{"id": r[0], "student": r[1], "course": r[2], "registered_at": r[3].isoformat(timespec="milliseconds"), "status": r[4]} for r in rows]}


@router.post("/reset")
def reset():
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "An experiment is running; reset when it finishes.")
    try:
        reset_and_seed()
    finally:
        _run_lock.release()
    return database_state()


class OsLayerRequest(BaseModel):
    queue_capacity: int
    worker_count: int
    db_semaphore_permits: int


@router.post("/os-layer")
def reconfigure_os_layer(body: OsLayerRequest, request: Request):
    """Replace the queue/worker/semaphore layer with a new one. The settings are otherwise fixed at start-up,
    so this is what lets a baseline-versus-candidate comparison run without restarting the server."""
    if not 1 <= body.queue_capacity <= 1000 or not 1 <= body.worker_count <= 64 or not 1 <= body.db_semaphore_permits <= 64:
        raise HTTPException(422, "queue_capacity 1..1000, worker_count 1..64, db_semaphore_permits 1..64.")
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "An experiment is running; change the settings when it finishes.")
    try:
        new_layer = OSConcurrencyLayer(OSLayerConfig(body.queue_capacity, body.worker_count, body.db_semaphore_permits))
        iasl = getattr(request.app.state, "iasl", None)
        if iasl is not None:
            iasl.attach(new_layer, strict=False)   # new bounds from the new size; clamps, because the server is running
        new_layer.start()
        old_layer = request.app.state.os_layer
        request.app.state.os_layer = new_layer      # new requests use the new layer from here on
        old_layer.stop()                            # let anything already accepted finish
    finally:
        _run_lock.release()
    return new_layer.snapshot()["config"]


# ----------------------------------------------------------------------------- result files

@router.get("/results")
def list_results():
    folder = results_dir()
    items = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder), key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True):
            if not name.endswith(".json"):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path) as handle:
                    doc = json.load(handle)
                items.append({
                    "experiment_id": doc["experiment_id"], "modified_at": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds"),
                    "size_bytes": os.path.getsize(path), "arrival_model": doc["config"].get("arrival_model"), "pattern": doc["config"].get("pattern"),
                    "contention": doc["config"].get("contention"), "total_requests": doc["summary"]["total_requests"],
                    "successful_requests": doc["summary"]["successful_requests"], "has_server_context": "server" in doc,
                })
            except (OSError, ValueError, KeyError):
                continue   # not a result file we recognise: leave it out rather than guess
            if len(items) >= 50:
                break
    return {"folder": folder, "items": items}


@router.get("/results/{experiment_id}")
def get_result(experiment_id: str):
    if not RESULT_ID.match(experiment_id) or experiment_id.startswith("."):
        raise HTTPException(404, "No such result.")
    folder = os.path.realpath(results_dir())
    path = os.path.realpath(os.path.join(folder, f"{experiment_id}.json"))
    if os.path.dirname(path) != folder or not os.path.isfile(path):
        raise HTTPException(404, "No such result.")
    with open(path) as handle:
        return json.load(handle)


# ----------------------------------------------------------------------------- tests

def verification_running():
    job = _verifications.get(_current["verify"])
    return bool(job and job.status == "running")


@router.post("/verify", status_code=202)
def start_verify():
    if _run_lock.locked():
        raise HTTPException(409, "An experiment is running; run the tests when it finishes.")
    if verification_running():
        raise HTTPException(409, "The test suite is already running.")
    try:
        job = verification.start_verification(uuid.uuid4().hex[:10])
    except verification.VerificationRefused as refusal:
        raise HTTPException(409, str(refusal)) from None
    _verifications[job.job_id] = job
    _current["verify"] = job.job_id
    return job.snapshot()


@router.get("/verify/current")
def current_verify():
    job = _verifications.get(_current["verify"])
    return job.snapshot() if job else {"status": "none"}
