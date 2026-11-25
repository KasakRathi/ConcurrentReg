#!/usr/bin/env python
"""IASL experiment harness. EXPERIMENT ONLY: it is not part of the product and the product never imports it.

SAFETY: it only ever touches the database `concurrentreg_exp` (it rewrites DATABASE_URL to that name before anything imports
the application, and refuses to continue if the connection does not report that name). The demo and test databases are never used.

Load is driven by scripts/iasl_loadgen.py (asyncio), which reuses the project generator's request schedule and response
classification; see that module for why the threaded generator could not be used.

Subcommands (run from the repo root, with .demo.env sourced so the MySQL credentials are in the environment):
  calibrate   measure the server's service capacity (closed loop) and check the driver stays valid at multiples of it
  run         execute a matrix of (workload x arm x seed) cells and write one JSON file per cell
  report      aggregate the cells of a run directory into tables

    set -a; source .demo.env; set +a
    PYTHONPATH=. .venv/bin/python scripts/iasl_experiment.py calibrate --permits 4
    PYTHONPATH=. .venv/bin/python scripts/iasl_experiment.py run --plan scripts/iasl_plan_evaluation.json --out results/iasl_experiments/evaluation
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

EXP_DB = "concurrentreg_exp"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8020
SCRATCH = os.path.join(ROOT, "results", "iasl_scratch")


def exp_url():
    base = os.environ.get("DATABASE_URL")
    if not base:
        raise SystemExit("DATABASE_URL is not set: run `set -a; source .demo.env; set +a` first.")
    url = base.rsplit("/", 1)[0] + "/" + EXP_DB
    os.environ["DATABASE_URL"] = url
    return url


def engine_for_experiments():
    """The SQLAlchemy engine, verified to point at the experiment database and nothing else."""
    exp_url()
    from app.database import engine
    if engine.url.database != EXP_DB:
        raise SystemExit(f"refusing to continue: connected to {engine.url.database!r}, not {EXP_DB!r}")
    return engine


# ----------------------------------------------------------------------------- the dataset

def seed_database(students, capacities):
    """Drop and recreate the tables in the experiment database and load a synthetic dataset (made-up names)."""
    from sqlalchemy import insert
    engine = engine_for_experiments()           # first: nothing below may run unless this is the experiment database
    from app import models
    from app.database import Base
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(models.Student), [{"student_id": f"STU{n:03d}", "name": f"Experiment Student {n}"}
                                                    for n in range(1, students + 1)])
        connection.execute(insert(models.CourseSection), [
            {"course_code": f"EXP{i:03d}", "course_name": f"Experiment course {i}", "capacity": cap, "available_seats": cap}
            for i, cap in enumerate(capacities, 1)])


def db_check(client_counts):
    """Correctness of the database after a run, from SQL. See docs/iasl/IASL_EXPERIMENTS.md section 4."""
    from sqlalchemy import text
    engine = engine_for_experiments()
    with engine.connect() as c:
        registrations = c.execute(text("SELECT COUNT(*) FROM registrations")).scalar()
        repeated = c.execute(text("SELECT COUNT(*) FROM (SELECT student_id, section_id FROM registrations "
                                  "GROUP BY student_id, section_id HAVING COUNT(*) > 1) t")).scalar()
        broken = c.execute(text(
            "SELECT COUNT(*) FROM course_sections s LEFT JOIN (SELECT section_id, COUNT(*) n FROM registrations GROUP BY section_id) r "
            "ON r.section_id = s.id WHERE s.available_seats <> s.capacity - COALESCE(r.n, 0) OR s.available_seats < 0 "
            "OR s.available_seats > s.capacity OR COALESCE(r.n, 0) > s.capacity")).scalar()
    successes = client_counts.get("SUCCESS", 0)
    # A client that timed out (or lost its connection) may still have been served afterwards, so the rows can exceed the
    # successes the client SAW, but never by more than the requests whose outcome it did not see.
    unseen = client_counts.get("TIMEOUT", 0) + client_counts.get("CONNECTION_ERROR", 0)
    consistent = successes <= registrations <= successes + unseen
    return {"registrations": registrations, "client_successes": successes, "client_unseen_outcomes": unseen,
            "repeated_pairs": repeated, "sections_inconsistent": broken, "rows_match_client": consistent,
            "ok": repeated == 0 and broken == 0 and consistent}


# ----------------------------------------------------------------------------- the server under test

class Server:
    def __init__(self, layer, iasl_env, logpath):
        self.layer, self.iasl_env, self.logpath, self.proc, self.url = layer, iasl_env, logpath, None, f"http://127.0.0.1:{PORT}"

    def start(self):
        import httpx
        queue, workers, permits = self.layer
        env = dict(os.environ, QUEUE_CAPACITY=str(queue), WORKER_COUNT=str(workers), DB_SEMAPHORE_PERMITS=str(permits),
                   IASL_ENABLED="1" if self.iasl_env is not None else "0")
        env.pop("CREG_DEMO_CONTROLS", None)
        for key, value in (self.iasl_env or {}).items():
            env[key] = str(value)
        os.makedirs(os.path.dirname(self.logpath), exist_ok=True)
        self.log = open(self.logpath, "wb")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning",
                                      "--timeout-keep-alive", "120"],   # keep the clients' warm connections open across idle phases
                                     cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early; see {self.logpath}")
            try:
                if httpx.get(f"{self.url}/os-layer/status", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError("server did not become ready")

    def stop(self):
        """Graceful: the layer drains accepted requests (so the database reaches its final state) before exiting."""
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()
        self.proc = None


# ----------------------------------------------------------------------------- one cell

def load_average():
    return round(os.getloadavg()[0], 2)


def workload_requests(spec, seed, students, section_ids):
    """The request list for one (workload, seed): the project generator's own schedule and targets."""
    from workload import workload_generator as wg
    instantaneous = "burst_count" in spec                 # all requests intended at t=0 (the generator's own "burst" pattern)
    config = wg.WorkloadConfig(
        base_url="http://unused", concurrency=1000, arrival_model="open", pattern="burst" if instantaneous else "phases",
        request_count=spec.get("burst_count", 20), phases=[] if instantaneous else [list(p) for p in spec["phases"]],
        contention=spec.get("contention", "mixed"), student_count=students, section_ids=section_ids,
        hot_section_count=spec.get("hot_sections", 2), hot_fraction=spec.get("hot_fraction", 0.8), seed=seed)
    wg.validate_config(config)
    return wg.generate_requests(config)


def offered_rate(records):
    times = sorted(r["intended_offset_s"] for r in records)
    return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else None


def run_cell(spec, arm_name, iasl_env, seed, requests, plan, outdir, attempt=1, previous=()):
    """Run one (workload, arm, seed) cell and return its record (also written to `outdir`)."""
    from scripts import iasl_analysis as ia
    from scripts import iasl_loadgen as lg
    setup = plan["setup"]
    capacities = spec.get("capacities", setup["capacities"])      # a workload may bring its own seat counts
    path = os.path.join(outdir, f"{spec['name']}__{arm_name}__seed{seed}.json")
    seed_database(setup["students"], capacities)
    server = Server(tuple(setup["layer"]), iasl_env, path.replace(".json", ".server.log"))
    record = {"workload": spec["name"], "arm": arm_name, "seed": seed, "iasl_env": iasl_env, "layer": setup["layer"],
              "attempt": attempt, "previous_invalid_attempts": list(previous),
              "capacities_summary": {"sections": len(capacities), "min": min(capacities), "max": max(capacities)},
              "started_at": datetime.now().isoformat(timespec="seconds"), "load_before": load_average()}
    import httpx
    server.start()
    try:
        records, polls, elapsed = lg.run_open_loop(requests, server.url, timeout_s=plan["timeout_s"],
                                                   processes=plan.get("client_processes", 6), warm_connections=plan.get("warm_connections", 480))
        record["server_end"] = httpx.get(f"{server.url}/os-layer/status", timeout=5).json()
        if iasl_env is not None:
            record["iasl_decisions"] = httpx.get(f"{server.url}/iasl/decisions", params={"limit": 200}, timeout=5).json()
            record["iasl_status"] = httpx.get(f"{server.url}/iasl/status", timeout=5).json()
    finally:
        server.stop()                                             # drains accepted work, so the database is final
    check = lg.validity(records, plan["lateness_tolerance_ms"])
    rows = ia.compact_rows(records)
    queue_capacity = setup["layer"][0]
    metrics = ia.run_metrics(rows, polls, queue_capacity, plan["timeout_s"])
    burst = spec.get("burst")
    if burst:
        metrics["recovery"] = ia.recovery_time(rows, burst[0], burst[1], spec["schedule_end_s"], plan["timeout_s"])
        metrics["drain_time_s"] = ia.drain_time(polls, queue_capacity, burst[1])
    if iasl_env is not None:
        metrics["fraction_time_restricted"] = ia.fraction_below_max(polls, queue_capacity)
    record.update({"valid_open_loop": check["valid"], "invalid_reasons": check["reasons"], "lateness_ms": check["lateness_ms"],
                   "offered_rate_per_s": offered_rate(records), "metrics": metrics, "db_check": db_check(metrics["counts"]),
                   "load_after": load_average(), "polls": polls, "rows": rows})
    with open(path, "w") as handle:
        json.dump(record, handle)
    return record


def one_line(record):
    m = record["metrics"]
    lat = m["service_latency_s"] or {}
    return (f"{record['workload']:<24}{record['arm']:<15}seed{record['seed']:<4} valid={str(record['valid_open_loop']):<5} "
            f"goodput={m['goodput_per_s'] or 0:7.1f}/s p95={1000 * (lat.get('p95') or 0):7.0f}ms "
            f"refused={100 * m['rates']['refused_total']:5.1f}% timeout={100 * m['rates']['timeout']:4.1f}% "
            f"err={100 * m['rates']['error']:3.1f}% db_ok={record['db_check']['ok']} load={record['load_before']}")


# ----------------------------------------------------------------------------- commands

def cmd_calibrate(args):
    from scripts import iasl_analysis as ia
    from scripts import iasl_loadgen as lg
    from workload import workload_generator as wg
    layer = [args.queue, args.workers, args.permits]
    capacities = [args.capacity] * args.sections
    section_ids = list(range(1, args.sections + 1))
    out = {"layer": layer, "students": args.students, "sections": args.sections, "closed_loop": [], "open_loop": []}
    print(f"[calibrate] server queue/workers/permits = {layer}; dataset {args.students} students x {args.sections} sections")
    for rep in range(args.repeats):                         # service capacity: closed loop keeps the server saturated
        seed_database(args.students, capacities)
        server = Server(tuple(layer), None, os.path.join(SCRATCH, "calibrate.server.log"))
        server.start()
        try:
            config = wg.WorkloadConfig(base_url=server.url, arrival_model="closed", virtual_users=args.users, request_count=args.requests,
                                       contention="mixed", student_count=args.students, section_ids=section_ids, hot_section_count=2,
                                       hot_fraction=0.8, seed=900 + rep, timeout_seconds=30, concurrency=args.users)
            wg.validate_config(config)
            records, elapsed = lg.run_closed_loop(wg.generate_requests(config), server.url, args.users, timeout_s=30, processes=4)
        finally:
            server.stop()
        counts = {}
        for r in records:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
        definitive = sum(counts.get(c, 0) for c in ia.DEFINITIVE)
        out["closed_loop"].append({"elapsed_s": elapsed, "definitive": definitive, "capacity_per_s": definitive / elapsed, "counts": counts})
        print(f"[calibrate] closed loop {args.users} users: {definitive} answers in {elapsed:.1f}s = {definitive / elapsed:.0f}/s  counts={counts}")
    capacity = sorted(c["capacity_per_s"] for c in out["closed_loop"])[len(out["closed_loop"]) // 2]
    out["capacity_per_s"] = capacity
    for fraction in args.fractions:                        # open loop at multiples of capacity: the driver must stay valid
        rate = round(capacity * fraction, 1)
        spec = {"name": f"probe{fraction}", "phases": [[rate, args.probe_seconds]]}
        requests = workload_requests(spec, 950, args.students, section_ids)
        seed_database(args.students, capacities)
        server = Server(tuple(layer), None, os.path.join(SCRATCH, "calibrate.server.log"))
        server.start()
        try:
            records, polls, elapsed = lg.run_open_loop(requests, server.url, timeout_s=5.0, processes=6, warm_connections=480)
        finally:
            server.stop()
        check = lg.validity(records, args.lateness_ms)
        m = ia.run_metrics(ia.compact_rows(records), polls, args.queue, 5.0)
        entry = {"fraction": fraction, "rate": rate, "valid_open_loop": check["valid"], "lateness_ms": check["lateness_ms"],
                 "p95_s": (m["service_latency_s"] or {}).get("p95"), "goodput": m["goodput_per_s"],
                 "refused": m["rates"]["refused_total"], "timeout": m["rates"]["timeout"]}
        out["open_loop"].append(entry)
        print(f"[calibrate] open loop at {fraction:.2f} x = {rate:.0f}/s: valid={check['valid']} "
              f"lateness_p99={(check['lateness_ms'] or {}).get('p99', 0):.0f}ms p95={1000 * (entry['p95_s'] or 0):.0f}ms "
              f"goodput={entry['goodput']:.0f}/s refused={100 * entry['refused']:.1f}% timeout={100 * entry['timeout']:.1f}%")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(out, handle, indent=1)
    print(f"[calibrate] capacity (median of closed-loop runs) = {capacity:.0f} answers/s; wrote {args.out}")


def cmd_run(args):
    plan = json.load(open(args.plan))
    os.makedirs(args.out, exist_ok=True)
    setup = plan["setup"]
    section_ids = list(range(1, len(setup["capacities"]) + 1))
    arms_all = [(name, cfg["env"], cfg.get("only")) for name, cfg in plan["arms"].items()]
    cells = []
    for seed_value in plan["seeds"]:
        for w_index, spec in enumerate(plan["workloads"]):
            arms = [(n, env) for n, env, only in arms_all if only is None or spec["name"] in only]
            if (seed_value + w_index) % 2 == 1:           # alternate the order of the arms so slow drift cannot favour one
                arms.reverse()
            cells.append((seed_value, spec, arms))
    total = sum(len(arms) for _, _, arms in cells)
    done = 0
    for seed_value, spec, arms in cells:
        requests = workload_requests(spec, seed_value, setup["students"], section_ids)   # ONCE, replayed identically per arm
        for arm_name, iasl_env in arms:
            path = os.path.join(args.out, f"{spec['name']}__{arm_name}__seed{seed_value}.json")
            done += 1
            if os.path.exists(path) and not args.force:
                print(f"[{done}/{total}] skip (exists) {os.path.basename(path)}")
                continue
            attempt, previous = 1, []
            while True:                                       # amendment 6: re-run only when the INSTRUMENT flagged the run invalid
                record = run_cell(spec, arm_name, iasl_env, seed_value, requests, plan, args.out, attempt, previous)
                print(f"[{done}/{total}] attempt {attempt}: {one_line(record)}", flush=True)
                if record["valid_open_loop"] or attempt >= 3:
                    break
                previous.append({"attempt": attempt, "reasons": record["invalid_reasons"], "lateness_ms": record["lateness_ms"],
                                 "load_before": record["load_before"]})
                os.replace(path, path.replace(".json", f".invalid_attempt{attempt}.json"))   # keep it, listed in the report
                attempt += 1
    print("[run] done")


def cmd_report(args):
    from scripts import iasl_report
    iasl_report.main(args.dir, args.out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--students", type=int, default=5000)
    c.add_argument("--sections", type=int, default=20)
    c.add_argument("--capacity", type=int, default=1_000_000)
    c.add_argument("--queue", type=int, default=200)
    c.add_argument("--workers", type=int, default=8)
    c.add_argument("--permits", type=int, default=4)
    c.add_argument("--users", type=int, default=64)
    c.add_argument("--requests", type=int, default=4000)
    c.add_argument("--repeats", type=int, default=3)
    c.add_argument("--fractions", type=float, nargs="*", default=[0.5, 0.9, 1.5, 2.0])
    c.add_argument("--probe-seconds", type=float, default=10)
    c.add_argument("--lateness-ms", type=float, default=250)
    c.add_argument("--out", default=os.path.join(ROOT, "results", "iasl_experiments", "calibration.json"))
    c.set_defaults(func=cmd_calibrate)
    r = sub.add_parser("run")
    r.add_argument("--plan", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_run)
    rp = sub.add_parser("report")
    rp.add_argument("dir")
    rp.add_argument("--out", default=None)
    rp.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    sys.path.insert(0, ROOT)
    if args.command in ("calibrate", "run"):
        exp_url()   # MUST happen before anything imports app.database (the engine is built at import time)
    args.func(args)


if __name__ == "__main__":
    main()
