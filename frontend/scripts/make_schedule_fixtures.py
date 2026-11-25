"""Regenerate src/lib/__fixtures__/schedule.fixtures.json from the REAL workload generator.

Run from the repository root:  .venv/bin/python frontend/scripts/make_schedule_fixtures.py
The vitest suite compares the TypeScript schedule preview against these numbers, so a drift between the
browser preview and workload/workload_generator.py shows up as a failing test.
"""
import json
import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from workload import workload_generator as g  # noqa: E402

CASES = {
    "burst": ["--pattern", "burst", "--requests", "20"],
    "steady": ["--pattern", "steady", "--rate", "7", "--requests", "25"],
    "ramp": ["--pattern", "ramp", "--rate", "30", "--requests", "40", "--ramp-stages", "4"],
    "ramp_uneven": ["--pattern", "ramp", "--rate", "9", "--requests", "17", "--ramp-stages", "3"],
    "phases": ["--phases", "10:5,100:2,10:10"],
    "phases_fractional": ["--phases", "2.5:3,0.5:4,7:1.5"],
    "closed": ["--arrival-model", "closed", "--users", "6", "--think-min", "0.1", "--think-max", "0.4", "--requests", "30"],
    "mixed_dup": ["--contention", "mixed", "--sections", "1,2,3", "--hot-sections", "1", "--hot-fraction", "0.7",
                  "--duplicate-fraction", "0.2", "--students", "50", "--requests", "200", "--pattern", "steady", "--rate", "50"],
}

out = {}
for name, argv in CASES.items():
    config = g.config_from_args(g.parse_args(argv))
    g.validate_config(config)
    closed = config.arrival_model == "closed"
    out[name] = {
        "argv": argv,
        "config": asdict(config),
        "planned_request_count": g.planned_request_count(config),
        "offsets": None if closed else g.arrival_offsets(config),
        "phase_plan": g.phase_plan(config) if config.pattern == "phases" else None,
    }

import random  # noqa: E402

rng = random.Random(7)
sample = [round(rng.lognormvariate(3, 0.8), 3) for _ in range(137)]
out["_latency_sample"] = {"values": sample, "stats": g.latency_stats(sample)}

target = os.path.join(ROOT, "frontend", "src", "lib", "__fixtures__", "schedule.fixtures.json")
with open(target, "w") as handle:
    json.dump(out, handle, indent=1)
print(f"wrote {target} ({len(out)} cases)")
