# frontend/ (landing page and dashboard)

**Purpose.** A browser UI for the research prototype: a public landing page and an experiment dashboard. It is a separate app
(Vite, React, TypeScript, Tailwind). It reads one backend endpoint, `GET /os-layer/status`, and reads workload-generator result files that
the user imports. It does not change the database, the API or the generator. See `frontend/README.md` for commands, the data-source
table and the licences.

**Rule it follows.** Every number on screen is either measured (live API or a result file), or is labelled *Simulation*, *Schematic* or
*Not exposed*. If the API fails, an error is shown; no sample data is substituted.

## Files

| File | What it does | Data source | What it does NOT do |
|---|---|---|---|
| `src/lib/types.ts` | TypeScript shapes of the status response and of a result file, copied from `request_pipeline.snapshot()` and `workload_generator.py` | none | validate anything (see api.ts, results.ts) |
| `src/lib/api.ts` | `fetchOsLayerStatus`: GET with a 4 s timeout, shape check, error kinds (unreachable / http / invalid) | `GET /os-layer/status` | call any other endpoint; retry; cache |
| `src/lib/results.ts` | parse and validate a result file; nearest-rank percentiles; per-second rate bins; histogram; error groups; comparison rows; CSV | imported file | repair or invent missing fields: they show as n/a |
| `src/lib/schedule.ts` | port of `phase_plan`, `arrival_offsets`, `planned_request_count`, `validate_config` | none (computed from settings) | generate the random request targets (Python's RNG is not ported) |
| `src/lib/command.ts` | builds the terminal command for a configuration, leaving out flags equal to the default | none | start a run |
| `src/lib/pipelineSim.ts` | seeded simulation of queue, workers, semaphore, one row lock per section, finite seats | none | measure anything; it is only an explanation |
| `src/lib/architecture.ts` | the stages, parameters and exposed metrics, written from the code; the admission controller is shown as an optional stage (IASL, off by default) | none | claim any feature that does not exist |
| `src/lib/idb.ts` | IndexedDB key-value wrapper; failures return "not saved" instead of throwing | browser storage | sync anywhere |
| `src/hooks/monitor.tsx` | one poller shared by the dashboard; keeps up to 1800 samples; computes rates between polls; marks a restart when counters go down | `GET /os-layer/status` | store history on the server; compute a rate across an outage |
| `src/hooks/results-store.tsx` | imported experiments, selection, persistence | user files | upload files |
| `src/components/visuals/PipelineCanvas.tsx` | draws a `PipelineSim` on a canvas; vertical layout on narrow screens; pauses when off screen | the simulation | change the rules of the simulation |
| `src/components/charts/*` | Recharts charts for result files and live samples | file / live | |
| `src/components/dashboard/*` | shell (sidebar, breadcrumb, status, selectors), tiles, comparison table | live / file | |
| `src/components/landing/Header.tsx`, `Hero.tsx` | fixed header with hover dropdowns and a mobile dialog; hero with the looping 3D clip and the stack row | none | claim any customer or usage |
| `src/components/landing/RunSection.tsx` | 12 presets + 3 server variants build the real terminal command with `buildCommand` | computed | start a run |
| `src/components/landing/ExperienceSection.tsx` | simulated responses using the README's real API messages; a labelled sample event timeline | simulation / sample | send any request |
| `src/components/landing/WorkloadsSection.tsx` | the Workloads page's schedule preview and validation, for one fixed configuration | computed (same code as the dashboard) | |
| `src/components/landing/ResultsSection.tsx` | your latest imported run, or a labelled example layout | result file / example | invent numbers without the label |
| `src/components/landing/ReproduceSection.tsx` | four real code excerpts with a plain-English note each | repository files (tested) | |
| `src/components/landing/GuaranteesSection.tsx`, `QuoteSection.tsx`, `FactsSection.tsx` | what the code enforces; the design principle; claims and limits with their source files | README / code | claim more than the tests establish |
| `src/components/landing/ControlSection.tsx` (+ `ArchitecturePanel`, `PlaygroundPanel`, `AnalyticsPanel`) | tabbed dashboard window: architecture explorer, workload simulation, result charts | architecture data / simulation / result file | |
| `src/components/landing/FooterSection.tsx` | closing statement, faded wordmark, link columns, one real backend check every 20 s | `GET /os-layer/status` | |
| `src/components/landing/VideoTile.tsx`, `CodeWindow.tsx`, `SectionHead.tsx` | looping video (plays only on screen, not with reduced motion), small syntax highlighter, shared section heading | none | |
| `scripts/render-media/` | renders the five clips, their posters and two backdrop images (software 3D on Canvas 2D, encoded with ffmpeg) | none | pull in any outside asset |
| `src/lib/landing-data.ts` | code excerpts, experiment presets, server variants | repository files | |
| `src/components/ui/*` | button, source badge, tooltip, states, code block, reveal, error boundary | none | |
| `src/pages/*` | one file per route | see README | |

## Behaviour worth knowing

* **Source badges** (`ui/SourceBadge.tsx`): Live API, Result file, Simulation, Schematic, Not exposed.
* **Latency percentiles** shown for a result file come from its own summary. When fewer than 20 (p95) or 100 (p99) answered requests
  exist, the tile says the value is close to the maximum.
* **Open-loop validity** is shown exactly as the file states it, with the file's invalid reasons.
* **Comparison** warns when seeds, arrival models, patterns, request counts or contention differ, or when either run is not valid open loop.
* **Reduced motion**: animations are skipped and the pipeline starts paused.

## Tests (`npm test`, 59 tests)

* `schedule.test.ts`: TypeScript offsets equal the real generator's offsets for 8 configurations (fixtures regenerated with
  `frontend/scripts/make_schedule_fixtures.py`). Mutation check: breaking the ramp formula made 2 tests fail; restored.
* `results.test.ts`: percentile rule equals the generator's, rate bins conserve counts, undispatched requests are not counted as sent,
  histogram accounts for every sample, CSV escaping, comparison rows.
* `command.test.ts`: only defined flags; commands re-parsed by the generator's own argument parser gave identical configurations (8 of 8).
* `pipelineSim.test.ts`: invariants hold at every step for several seeds and resource limits.
* `landing-data.test.ts`: every code excerpt on the landing page is an exact copy of the repository file it names; every preset validates.

## Not covered by automated tests

The React components, the canvas drawing and the routes were checked by screenshots in headless Chromium, not by component tests.
