# ConcurrentReg frontend

A landing page and an experiment dashboard for the ConcurrentReg research prototype (Vornics).
Vite + React 19 + TypeScript + Tailwind CSS 4. It is a separate app in `frontend/`; it does not change the Python backend.

## Run it

```bash
# terminal 1: the backend (from the repository root)
.venv/bin/python -m app.seed
QUEUE_CAPACITY=8 WORKER_COUNT=3 DB_SEMAPHORE_PERMITS=2 .venv/bin/uvicorn app.main:app --port 8000

# terminal 2: the frontend
cd frontend
npm install
npm run dev            # http://localhost:5173
```

| Command | What it does |
|---|---|
| `npm run dev` | dev server; `/api/*` is proxied to `BACKEND_URL` (default `http://127.0.0.1:8000`), so no CORS is needed |
| `npm run build` | type-check (`tsc -b`) then production build into `dist/` |
| `npm run typecheck` | type-check only |
| `npm test` | unit tests (vitest) |
| `npm run preview` | serve `dist/` on :4173 with the same `/api` proxy |

`VITE_API_BASE_URL` (see `.env.example`) overrides the API base. If you point it at another origin the backend must
allow CORS for the frontend's origin; the backend does not do that today.

## Routes

| Route | Content |
|---|---|
| `/` | Landing page |
| `/dashboard/demo` | **Live demo**: the guided, judge-ready flow against the real backend (needs the demo controls; see the root README) |
| `/dashboard` | Overview: live OS-layer counters, selected experiment, what is not available |
| `/dashboard/monitoring` | Live time series sampled by the browser |
| `/dashboard/iasl` | **IASL**: the adaptive admission controller live: state, the gate and its limit, signals against their thresholds, the decision log, and the settings in force. Read-only. Shows "switched off" unless the backend runs with `IASL_ENABLED=1` (or start the demo with `IASL=1 ./scripts/start_demo.sh`) |
| `/dashboard/experiments` | Import result files, history, baseline vs candidate |
| `/dashboard/workloads` | Workload configuration, validation, schedule preview, exact terminal command |
| `/dashboard/architecture` | Interactive request lifecycle with live counters per stage |
| `/dashboard/results/:id` | One experiment in detail, comparison, CSV/JSON export |

## Where every number comes from

Every panel carries a source badge. There are only five kinds.

| Badge | Meaning | Source |
|---|---|---|
| **Live API** | measured now | `GET /os-layer/status`, polled every 1, 2 or 5 s by the browser |
| **Result file** | measured in a past run | a JSON file written by `workload/workload_generator.py`, imported by the user |
| **Simulation** | NOT a measurement | the in-browser model in `src/lib/pipelineSim.ts` (hero and workload playground) |
| **Schematic** | NOT a measurement | an illustration or a preview computed from settings (schedule preview, command builder) |
| **Not exposed** | missing | the backend does not provide it; the UI says what it would need |

Backend endpoints used: `GET /os-layer/status` always; and, only when `GET /demo/info` says the demo controls are on: `/demo/state`, `/demo/registrations`, `/demo/reset`, `/demo/runs`, `/demo/os-layer`, `/demo/results`, `/demo/verify` (all in `app/demo_api.py`). `POST /registrations` is never called by the frontend: requests are sent by the real workload generator on the server.
If the API is down, the Overview, Monitoring and Architecture pages show an error with the start command. No sample data is ever substituted.

### Backend requirements (not implemented, documented only)

| Missing capability | What would be needed |
|---|---|
| Launching an experiment from the browser | **now provided** by `POST /demo/runs` when `CREG_DEMO_CONTROLS=1` (off by default) |
| Experiment history on the server | **now provided** by `GET /demo/results` in demo mode; otherwise users import files in the browser (IndexedDB) |
| Database lock-wait metrics | an endpoint reading `information_schema.innodb_trx` / `performance_schema` (needs the PROCESS privilege) |
| Live latency percentiles, live registration outcomes | server-side counters/histogram exposed over HTTP |
| Queue depth per run | the generator or server logging `/os-layer/status` during a run |
| Fixed vs adaptive comparison | the backend has optional IASL admission control (`GET /iasl/status|metrics|decisions|config`, off by default) and the IASL page shows it live; to compare fixed and adaptive runs use result files, and see `docs/iasl/IASL_EXPERIMENTS.md` |

## Verification of the logic that matters

* `src/lib/schedule.ts` ports the generator's arrival-schedule rules. `scripts/make_schedule_fixtures.py` runs the REAL generator
  (`.venv/bin/python frontend/scripts/make_schedule_fixtures.py`, from the repo root) and `schedule.test.ts` requires the TypeScript
  offsets to be bit-identical for steady, burst, ramp, phases and closed-loop configurations. A deliberately broken ramp formula makes it fail.
* `src/lib/command.ts` only emits flags the generator defines. The commands for every fixture were parsed back with the generator's own
  `parse_args` / `config_from_args` and compared to the original configuration (8 of 8 identical).
* `src/lib/landing-data.ts` holds the code excerpts shown on the landing page; `landing-data.test.ts` re-reads the repository files and fails if an excerpt
  is not an exact copy, and checks that every "Run an experiment" preset is a configuration the generator's validation accepts.
* `src/lib/pipelineSim.ts` is unit-tested for its invariants at every step: seats taken never exceed seats, semaphore holders never exceed
  permits, the queue never exceeds its capacity, and offered = finished + in flight.
* Percentiles use the generator's nearest-rank rule and are compared with its `latency_stats` output.

## Libraries (all installed from npm; no template was copied)

| Library | Used for | Licence | Repository |
|---|---|---|---|
| React, React DOM | UI | MIT | facebook/react |
| React Router | routing | MIT | remix-run/react-router |
| Vite, @vitejs/plugin-react | build and dev server | MIT | vitejs/vite |
| Tailwind CSS 4 | styling | MIT | tailwindlabs/tailwindcss |
| Motion (motion/react) | scroll reveals, entrance and section transitions | MIT | motiondivision/motion |
| Recharts | all charts | MIT | recharts/recharts |
| Radix UI (Dialog, Tabs, Tooltip, NavigationMenu) | accessible primitives, restyled | MIT | radix-ui/primitives |
| cmdk | command palette | MIT | dip/cmdk |
| Lucide | icons | ISC | lucide-icons/lucide |
| clsx, tailwind-merge | class names | MIT | |
| Geist Variable, Geist Mono Variable, Inter Variable, Instrument Serif (via @fontsource) | typefaces | SIL OFL 1.1 | |
| Vitest | tests | MIT | |

Evaluated and not used: GSAP (would overlap with Motion; no licence declared on the GitHub repository), Apache ECharts
(heavier than the chart types need), Spline (a 3D runtime is not worth the performance cost here), shadcn/ui (Radix primitives were
styled directly instead, so no generated component code is vendored).

## Landing page: how it relates to the reference site

The landing page follows the structure, rhythm and motion of a well-known developer-product homepage (Resend), as requested: left-aligned
serif hero with a 3D loop beside it, a stack row, a sequence of "tile + large heading + muted paragraph" sections, a tabbed dashboard window,
a testimonial-style marquee, a closing statement with a faded wordmark, and a column footer. It was produced with the `/clone` workflow's
analysis steps (computed styles, motion, per-viewport screenshots, asset inventory), re-expressed in this project's own code:

* Measured and re-created: heading sizes and tracking (96 px serif, 56 px at -2.8 px), the 104 deg translucent button gradient with a 16 px
  radius and a white-fill hover, 24 px cards with a 1 px translucent border and a top highlight line, the 1 s header / hero-text / visual
  entrance animations, the rotating gradient ring on the pill, and the 180 s marquee.
* Not copied: text, logos, photographs, product screenshots, videos, testimonials, customer names, or any source code. Every section's
  words, visuals and data are ConcurrentReg's own. The reference's headline typefaces are commercial, so Instrument Serif (headline) and Geist
  (section headings) stand in; body text is Inter.
* The `/clone` skill itself was not run as written: it targets a Next.js project in another user's directory and needs the Playwright MCP.
  Reference captures were kept outside the repository.

## Original media

Every image and clip on the landing page is generated by this repository, with no stock or third-party assets.

| File | What it is | Made by |
|---|---|---|
| `public/media/hero.webm`, `hero.mp4` (+ poster) | 10 s loop: a 3x3x3 lattice of dark glass cells that light up one after another, like seats being committed | `scripts/render-media` |
| `cli`, `schedule`, `seed`, `ring` (`.webm`, `.mp4`, poster) | 4 s loops, one per section: a terminal plate with a cursor, a burst of arrival bars, a die, a ring of permits | same |
| `floor.jpg`, `rays.jpg` | hero backdrop: a perspective floor grid and faint light streaks | same |

`scripts/render-media/scene.html` is a small software 3D renderer on Canvas 2D (geometry, lighting, grain, glow; every frame is a pure function of
time so each clip loops seamlessly). `render.mjs` steps it, grabs frames and encodes them with `ffmpeg`:

```bash
# needs Playwright (set PLAYWRIGHT_MODULE to its index.mjs if it is not installed here) and ffmpeg on PATH
node frontend/scripts/render-media/render.mjs all            # everything
node frontend/scripts/render-media/render.mjs all cli        # one clip
node frontend/scripts/render-media/render.mjs still hero 0.4 /tmp/hero.png   # one frame, for previewing
```

Clips play only while on screen, never with reduced motion (the poster is shown), carry no audio, and WebM is listed before MP4 so browsers
without H.264 still play them. They illustrate ideas; they show no measurements.

## Accessibility and motion

Reduced-motion preference: entrance animations are skipped, videos stay on their poster frame, the workload simulation starts paused, the claims
marquee becomes a static, hand-scrollable row, and CSS animations are reduced to near zero. The pipeline can be paused at any time. Canvas visuals have text alternatives; icon-only buttons have labels;
mobile navigation uses accessible dialogs; charts are accompanied by numbers.

## Known limitations

* Imported result files live in the browser (IndexedDB). A private window may refuse to save them; the page says so.
* Result files do not record the server settings (queue capacity, workers, permits), so the comparison cannot show them.
* `npm run build` produces a 418 kB (119 kB gzip) charts chunk. Routes are code-split, but the landing page also loads that chunk
  because the workload playground and measurement section use Recharts. Lazy-loading those two sections would be the next optimisation.
* The landing page and dashboard were checked in headless Chromium at 390, 768, 820, 1024 and 1440 px wide. They were not checked in Safari or Firefox.

## Navbar (landing page)

Researched on GitHub before building; licences and activity checked through the GitHub API (all MIT, all pushed within weeks).

| Source | What was taken from it |
|---|---|
| radix-ui/primitives `NavigationMenu` (used) | accessible foundation: hover intent (110 ms open delay, 450 ms skip delay), full keyboard model, `data-motion` directions, viewport size CSS variables |
| dip/cmdk (used) | the command palette engine (fuzzy search, keyboard navigation) |
| motiondivision/motion (already used) | `layoutId` sliding highlight, scroll progress spring (technique studied in ibelick/motion-primitives `AnimatedBackground`; code written here) |
| the reference site's own menu | one frosted popup that morphs width and re-centres under each trigger, 24 px radius, backdrop blur, 350 ms transitions |

What it does: Product / Research / Dashboard mega-menus with icon + description links and cards using the original 3D renders; a hover highlight that
glides between items; the header condenses into a floating pill on scroll with a scroll-progress hairline; scroll-spy marks the menu whose section you are
in; **Ctrl/Cmd+K** (or `/`) opens a palette that also works inside the dashboard and can open imported experiments or copy real generator commands (copied,
never run); a status dot reflecting the real backend; a full-screen mobile sheet. It honours reduced motion.
Verified with 24 browser checks (hover, keyboard Enter/Escape and focus return, morphing, scroll pill, scroll-spy, palette, mobile sheet, reduced motion)
and an automated accessibility audit (axe-core): closed navbar, command palette and mobile sheet have no violations. One finding remains while a menu is open:
`aria-hidden-focus` on a visually hidden focus guard that **Radix NavigationMenu renders itself** (`FocusProxy` in its source); it is by design in that library, so it is
documented here rather than patched.
