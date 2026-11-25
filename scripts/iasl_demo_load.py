#!/usr/bin/env python
"""Drive a RUNNING ConcurrentReg server with an open-loop schedule, so the IASL dashboard page has something to show.

It only sends HTTP: it imports nothing from `app` and never touches a database. The target server must already have the
students STU001..STU<students> and the sections 1..<sections> in its database (the harness seed does this:
`scripts.iasl_experiment.seed_database`; the demo's own seed has only 10 students and 2 sections, so use
--students 10 --sections 2 against the demo, which then produces mostly DUPLICATE/COURSE_FULL answers: fine for watching load).

The schedule is the project generator's own (workload.workload_generator.generate_requests, pattern "phases", mixed
contention: 80% of requests on 2 hot sections), sent by scripts/iasl_loadgen.py (asyncio, several processes on one shared
clock, pre-opened keep-alive connections). Phases are RATE:SECONDS pairs, e.g. a calm start, an overload, a calm end:

    PYTHONPATH=. .venv/bin/python scripts/iasl_demo_load.py --url http://127.0.0.1:8010 --phases '100:6,320:22,100:12'

Rates beyond what the server can answer make it refuse requests (queue full, or admission control when IASL is on).
Keep --processes at 6 or fewer: more client processes do not help on macOS (connection storms overflow its accept queue).
"""
import argparse
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import iasl_loadgen as lg  # noqa: E402  (HTTP load driver; no database access)
from workload import workload_generator as wg  # noqa: E402  (the project's schedule and validation)

REFUSALS = (wg.QUEUE_FULL, wg.ADMISSION_REJECTED)


def build_requests(phases_text, students, sections, seed):
    """The generator's own request list for the given phases (validated by the generator's own rules)."""
    phases = wg.parse_phases(phases_text)
    # "mixed" contention needs at least one section that is not hot. With the full 20 sections there are 2 hot ones (the
    # experiments' setting); the demo's own seed has only 2 sections, so there one is hot and the other is not; with one
    # section everything is hot.
    if sections >= 3:
        contention, hot_sections = "mixed", 2
    elif sections == 2:
        contention, hot_sections = "mixed", 1
    else:
        contention, hot_sections = "hot", 1
    config = wg.WorkloadConfig(
        base_url="http://unused", concurrency=1000, arrival_model="open", pattern="phases", phases=phases,
        contention=contention, student_count=students, section_ids=list(range(1, sections + 1)),
        hot_section_count=hot_sections, hot_fraction=0.8, seed=seed)
    wg.validate_config(config)
    return wg.generate_requests(config), phases


def summarise(records, phases, elapsed):
    counts = Counter(r["category"] for r in records)
    total = len(records)
    refused = sum(counts.get(c, 0) for c in REFUSALS)
    lines = [f"sent {total} requests over {elapsed:.1f} s (schedule: {', '.join(f'{r:g}/s for {d:g}s' for r, d in phases)})"]
    lines += [f"  {category:<20}{n:>7}  {100 * n / total:5.1f}%" for category, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    lines.append(f"  refused (queue full + admission): {refused} = {100 * refused / total:.1f}%")
    late = lg.validity(records, 250)
    lines.append(f"  client keeping to the schedule: {'yes' if late['valid'] else 'NO: ' + '; '.join(late['reasons'])}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the running server")
    parser.add_argument("--phases", default="100:8,320:25,100:15", help="RATE:SECONDS,RATE:SECONDS,... (default: calm, overload, calm)")
    parser.add_argument("--students", type=int, default=5000, help="STU001..STU<n> must exist on the server (default 5000)")
    parser.add_argument("--sections", type=int, default=20, help="sections 1..n must exist on the server (default 20)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--processes", type=int, default=4, help="client processes, at most 6 (default 4)")
    parser.add_argument("--timeout", type=float, default=5.0, help="client timeout per request in seconds (default 5)")
    args = parser.parse_args(argv)
    if not 1 <= args.processes <= 6:
        parser.error("--processes must be between 1 and 6")
    try:
        requests, phases = build_requests(args.phases, args.students, args.sections, args.seed)
    except wg.ConfigError as error:
        parser.error(str(error))
    print(f"sending {len(requests)} requests to {args.url} ...", flush=True)
    records, _polls, elapsed = lg.run_open_loop(requests, args.url, timeout_s=args.timeout, poll_interval=None,
                                                processes=args.processes, warm_connections=60 * args.processes)
    print(summarise(records, phases, elapsed))


if __name__ == "__main__":   # required: the load driver starts client processes with "spawn", which re-imports this file
    main()
