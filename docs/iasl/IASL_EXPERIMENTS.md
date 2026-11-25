# IASL Experimental Evaluation (Stage 8)

**Status of this document:** sections 1 to 8 were written **before any evaluation run** and are the pre-registration: the setup,
workloads, metric definitions, hypotheses and decision rules below were fixed first and were not changed after seeing results.
Results are in section 9 onward and were added afterwards. The plan was **revised once, after the pilot and calibration but before any evaluation run**,
because the pilot exposed problems in the load-generating instrument; every revision is listed in section 8.

**What this evaluation can and cannot show.** It compares the existing fixed pipeline with the pipeline plus IASL v1 (a deterministic
rule-based controller that moves one admission limit) on one machine, one synthetic dataset and five synthetic workload shapes. It says
nothing about real university traffic, other hardware, PostgreSQL, or settings other than those tested, and with five seeds per cell it can only
detect large effects (section 5).

---

## 1. Question

Does IASL v1 improve how the system behaves under load without hurting correctness, and at what cost?

The design predicted (`IASL_ARCHITECTURE.md` §1) that IASL **cannot raise throughput** (the database/semaphore bounds it) and **can** trade
refusals for lower queueing delay and faster recovery. The hypotheses (section 5) test exactly that, including the ways it could fail.

---

## 2. Set-up

| Item | Value |
|---|---|
| Host | one macOS machine, 10 cores, also running the load generator, the server and the Docker VM that hosts MySQL |
| Database | MySQL 8.4.11 / InnoDB in Docker (`creg-demo-mysql`), database `concurrentreg_exp` (separate from the demo and test databases) |
| Server | one `uvicorn app.main:app` process per run, fresh process and freshly seeded database for every run |
| Dataset | 5,000 synthetic students, 20 synthetic sections, 1,000,000 seats each (so seats never run out and goodput is meaningful); the correctness workload W6 uses 100 seats per section. The server runs with `--timeout-keep-alive 120` so the clients' warm connections survive idle phases |
| Contention | `mixed`: 80% of requests target 2 "hot" sections, 20% the other 18 (a registration rush on a few popular courses) |
| Requests | generated **once** per (workload, seed) and replayed identically against every arm |
| Client | an asyncio load driver (`scripts/iasl_loadgen.py`) running in **6 client processes** on one shared clock, driven by the project generator's own request schedule and response classification; open loop, 480 pre-opened keep-alive connections, client timeout 5 s, lateness tolerance 250 ms (see section 8 for why the project's threaded generator was not used) |
| Server settings | queue capacity 200, worker threads 8, DB semaphore permits 4 (the settings proposed before the work started) |
| Arms | `baseline` (IASL off) and `iasl_default` (IASL on, **all unmodified default settings**). `iasl_sensitive` is an *exploratory* extra arm (section 5) |
| Interleaving | for each (workload, seed) both arms run back to back; the order alternates with `seed + workload index` so slow drift cannot favour one arm |
| Server observation | `GET /os-layer/status` polled every 0.25 s for **both** arms (same endpoint, same cost) |
| Containers | the 20 unrelated Docker containers on the host were stopped for the experiments (list saved) and restored afterwards; `creg-demo-mysql` stayed up |

IASL settings are the repository defaults: sampling 0.5 s, admission minimum = worker count (8), maximum = queue capacity (200), step 10% of the
span (19), queue-utilisation thresholds 0.50/0.85, queue-wait p95 thresholds 0.10/0.50 s, queue-full-rejection thresholds 1%/5%, error-rate thresholds
2%/10%, escalate after 2 and de-escalate after 5 consecutive samples, cooldown 2 s (decrease) / 4 s (increase), reversal lockout 8 s, fallback
`baseline`. These were never calibrated; **they are not tuned to these workloads**, and they were not changed after the pilot or any result.
`iasl_sensitive` is one predetermined alternative (thresholds roughly halved: queue utilisation 0.25/0.45, queue-wait p95 0.05/0.25 s,
queue-full-rejection 0.5%/2.5%), run only on the three overload workloads, to see how sensitive the outcome is to the thresholds. It is labelled
exploratory and carries no hypothesis.

### 2.1 Calibration (measured before the evaluation plan was fixed)

Calibration ran in two rounds, because the first exposed a defect in the instrument (section 8).

| Round | Instrument | Result |
|---|---|---|
| 1 | project's threaded generator, permits 4 | closed-loop capacity 316, 359, 429 answers/s; open loop at 1.5x / 2x / 3x of that **invalid** (lateness p99 4 to 23 s), goodput stuck near 210 to 240/s, queue never full |
| 1 | same, permits 1 | capacity about 200/s (stable); valid up to 1.8x |
| 2 | asyncio driver, one process | invalid above about 400/s: the server received nothing for 7 s (log), the client process was at 75 to 100% CPU |
| 2 | asyncio driver, **6 processes, warmed connections**, permits 4 | closed-loop capacity **376, 340, 357 answers/s** (about 5% spread); open loop at 0.5x / 0.9x / 1.5x / 2.0x = 178 / 321 / 535 / 714 req/s: **all valid** (lateness p99 at most 9 ms); p95 15 / 406 / 734 / 1126 ms; refused 0% / 0% / 37% / 63%; goodput 178 / 306 / 316 / 244 /s |

So C is about **357 answers/s** (rounded to 360 below). The instrument stays valid at 2 C, the baseline already shows genuine overload, and goodput
*falls* when load exceeds capacity (316/s at 1.5 C, 244/s at 2 C): refusing a request still costs the single server process real work.

---

## 3. Workloads

Rates are in requests/s; C = 360/s is the measured service capacity (section 2.1).

| Id | Shape | Schedule | Requests | Purpose |
|---|---|---|---|---|
| W1 normal | steady | 180/s (0.5 C) for 20 s | 3,600 | does IASL stay out of the way when nothing is wrong |
| W2 gradual | staircase | 180, 270, 360, 450, 540 /s (0.5 to 1.5 C), 5 s each | 9,000 | gradually increasing load, through and beyond capacity |
| W3 burst | instantaneous | 500 requests all intended at t = 0 | 500 | sudden burst shorter than the control loop's reaction time |
| W4 overload | steady | 540/s (1.5 C) for 16 s | 8,640 | sustained overload |
| W5 burst + recovery | phases | 144/s (0.4 C) for 8 s, **648/s (1.8 C) for 4 s**, 144/s for 20 s | 6,624 | burst, then how fast things return to normal |
| W6 overload, scarce seats | steady | as W4 but **100 seats per section** (2,000 seats for 8,640 requests) | 8,640 | correctness under pressure with real seat contention |

Seeds 1 to 5 for every workload (pilot seed 101, harness check only).

---

## 4. Metrics (definitions fixed in advance; implemented and unit-tested in `scripts/iasl_analysis.py`)

| Metric | Definition |
|---|---|
| **Definitive answer** | a request whose category is `SUCCESS`, `DUPLICATE` or `COURSE_FULL`: the database decided it |
| **Goodput** | definitive answers per second over the whole run (first intended arrival to last response) |
| **Registrations/s** | `SUCCESS` per second over the same span |
| **Service-latency set** | definitive answers **plus client timeouts counted at the timeout value (5 s)**. A timeout is a lower bound on a latency too slow to observe; leaving timeouts out would let a slower system look faster. Requests refused up front (queue full or admission) are **not** in this set: they appear as rejection rates, so refusing work can never masquerade as speed |
| **Latency** | `end - INTENDED arrival` (what a user would feel, including any generator lateness); p50, p95, p99 of the service-latency set |
| **All-answered latency** | the same including instant refusals; reported only for transparency, never as a headline |
| **Rates** | queue-full refusals, admission refusals, total refusals, errors (`SERVER_ERROR`, `CLIENT_ERROR`, `UNKNOWN`), timeouts, connection errors; each as a share of all requests |
| **Utilisation** | mean and maximum of polled queue depth / capacity, active / alive workers, semaphore in use / permits (instantaneous gauges); IASL arms also the admission limit and the share of polls with the limit below capacity |
| **Recovery time (W5)** | baseline = p95 of the service-latency set for requests intended in [1 s, burst start). Target = max(1.5 x baseline, baseline + 25 ms). Recovered when 3 consecutive 1-second bins (by intended arrival, after the burst ends), each with at least 5 samples, have p95 <= target. Recovery time = start of the first such bin minus burst end. If it never happens inside the schedule it is reported as **not recovered** (censored), never as a number |
| **Queue drain time (W5)** | seconds after the burst ends until polled queue depth stays at or below 5% of capacity for 3 consecutive polls |
| **Correctness** | after the run and a graceful server stop (which drains accepted work): no `(student, section)` registered twice; for every section `available_seats = capacity - registered`, `0 <= available_seats <= capacity`, `registered <= capacity`; and `client successes <= rows in DB <= client successes + client timeouts + connection errors` (a client that gave up may still have been served afterwards) |
| **Validity** | a run is valid only if every request was dispatched and none was sent more than 250 ms after its intended time (the generator's open-loop rule) |

---

## 5. Hypotheses and decision rules (fixed in advance)

Comparisons are **paired by seed** (same requests in both arms). With five seeds the rules are sign-count rules, not significance tests; the calibration
runs varied about 15% from run to run, so effects smaller than roughly 20% cannot be distinguished from noise and are reported as "no clear difference".
Ratios are `iasl_default / baseline`.

| Id | Hypothesis | Counts as **supported** only if |
|---|---|---|
| **H1** | under sustained overload IASL lowers the latency of the requests it serves | W4: service-latency p95 is lower in at least 4 of 5 seeds **and** the median ratio is at most 0.90 |
| **H2** | it does so without a material loss of goodput | W2, W4, W5: median goodput ratio at least 0.90 (a "material fall" is below 0.90) |
| **H3** | it never compromises correctness | **every** run in every workload and arm passes the correctness check, and no run has errors beyond refusals (a hard requirement, not a performance hypothesis) |
| **H4** | at normal load it changes nothing material | W1: admission refusals below 1% in every seed, median p95 ratio within 0.80 to 1.25, median goodput ratio at least 0.95, and the limit below capacity for under 5% of polls |
| **H5** | an instantaneous burst is over before the loop can react, so it makes no material difference | W3: median p95 ratio within 0.80 to 1.25 and median goodput ratio at least 0.90 (a clear improvement would be a surprise and would be reported as such) |
| **H6** | it does not slow recovery after a burst | W5: median recovery ratio at most 1.25 (runs where either arm did not recover are counted and shown, not hidden) |

Any rule not met is reported as **not supported**. Refusal rates are always reported next to latency; an improvement in latency that is paid for with a
large rise in refusals is stated as a trade, not as a win. `iasl_sensitive` is exploratory: reported descriptively, no decision rule.

---

## 6. Exclusions

* A seed enters a paired comparison only if **both** arms' runs are valid (section 4). Invalid runs are excluded from performance comparisons, counted, and
  listed with the generator's own reason. They are **never** excluded from the correctness check (H3).
* No run is re-run because of its result. A run is repeated only if the harness itself failed (a crash before the result file was written), and every
  such repeat is listed.
* The pilot (seed 101) checks the harness only and contributes nothing to any conclusion.

---

## 7. Known confounds (disclosed up front)

* **Shared machine.** The generator, server and Docker VM share 10 cores; macOS background services (iCloud sync) were using several cores during
  setup. The 1-minute load average is recorded before and after every run. Interleaving the arms protects against slow drift, not against bursts of noise.
* **Single-process, Python.** Server and generator are single-process Python programs; absolute numbers are specific to this machine.
* **Synthetic workloads and data.** Made-up students and sections; request mix chosen by me; not real university traffic.
* **Logging cost.** The server writes one JSON log line per request in both arms (existing behaviour); IASL adds only its own few decision lines.
* **Few seeds.** Five per cell (section 5).
* **Same host for the database.** MySQL runs in a local Docker VM, so database latency is unrealistically small.

---

## 8. Revisions and deviations (all made before any evaluation run; reported before results)

1. **The project's threaded workload generator was not used; an asyncio, multi-process driver was.** Pilot and calibration runs showed the threaded
   generator stalls once a few hundred requests are in flight: dispatch fell from 600 to 18-90 requests per 2 s while the server's queue sat empty,
   the run was flagged invalid, and goodput stuck near 220/s regardless of offered load. Cause (diagnosed, not guessed): the HTTP client library's
   connection pool does work proportional to the number of open connections, so a single client process spends its time managing the pool and stops
   sending (the server log showed 7 seconds with no requests, the client at 75 to 100% CPU). A single asyncio process had the same limit; spreading
   the load over 6 processes with small pools removed it. The new driver reuses the generator's request schedule and its response classification
   unchanged and is checked against the project generator on identical requests (`tests/test_iasl_experiment_loadgen.py`).
2. **Connections are pre-opened and reused.** With several processes, hundreds of simultaneous *new* connections overflow the operating system's accept
   queue (128 on this macOS) and the surplus are refused (201 of 600 in a probe). Warming 480 keep-alive connections before the clock starts avoids
   measuring that. It also removes connection-setup noise from every run, equally for both arms.
3. **An earlier draft of this plan used one DB permit** (I had concluded the server could not otherwise be overloaded). That conclusion came from deviation 1's
   defect and was withdrawn; the plan uses the proposed **4 permits**, measured capacity 357/s. Nothing in the results should be read as being about 1 permit.
4. **Dataset:** 5,000 students and 20 sections (proposed about 2,000 and 20), so no request needs a repeated student and `DUPLICATE` answers do not blur
   throughput.
5. **Instantaneous burst size** W3 = 500 requests (lateness of a truly simultaneous burst is bounded by one event loop's start-up cost).
6. **Re-running invalid runs (amendment to section 6).** The machine is noisy over time (macOS background services; one probe at 0.9 C was invalid and
   the identical probe minutes later was perfect). A run flagged invalid by the **instrument's** rule (a request dispatched more than 250 ms late, or not
   dispatched) is re-run, up to 2 further attempts, with the same seed and requests. All attempts are kept and listed. Validity is judged only from
   dispatch lateness, never from any outcome metric, and an arm is never re-run for a result it produced. If a cell is still invalid after 3 attempts it
   is excluded and reported.
7. **IASL settings were not changed** at any point; the defaults in section 2 are what the pilot and the evaluation ran.

---

## 9. Results

All 75 planned cells ran; **every one was valid on its first attempt** (no dispatch-lateness failure, no re-run) and **every one passed the correctness check**.
Run: 2026-11-25, 30 minutes (02:34 to 03:05) on the machine described in section 2, with the 20 unrelated containers stopped. The 1-minute load average
before the runs ranged from 4.3 to 11.2 (macOS background services; see section 10). Raw per-run files (per-request rows, server polls, IASL decisions,
server logs) are in `results/iasl_experiments/evaluation/` (git-ignored).

### 9.1 Verdicts on the pre-registered hypotheses (mechanical application of section 5)

| id | hypothesis | verdict | evidence |
|---|---|---|---|
| H1 | under sustained overload IASL lowers the latency of the requests it serves (W4) | **SUPPORTED** | lower in 4 of 5 seeds, median ratio 0.77 (needs >= 4 seeds and <= 0.90) |
| H2 | without a material loss of goodput (W2, W4, W5) | **NOT SUPPORTED** | w2_gradual median ratio 0.98; w4_overload median ratio 0.86 (below 0.90); w5_burst_recovery median ratio 0.96 |
| H3 | it never compromises correctness (all runs) | **SUPPORTED** | 75 runs checked; none failed |
| H4 | at normal load it changes nothing material (W1) | **SUPPORTED** | max admission refusals 0.00%; median p95 ratio 1.15; median goodput ratio 1.00; limit below capacity in up to 0.0% of polls |
| H5 | an instantaneous burst makes no material difference (W3) | **SUPPORTED** | median p95 ratio 0.88, median goodput ratio 1.23 |
| H6 | it does not slow recovery after a burst (W5) | **SUPPORTED** | recovered in both: 5 seeds (median ratio 1.0); only IASL recovered: 0; only baseline recovered: 0; neither: 0 |


**Reading the verdicts.** Five of six pre-registered hypotheses are supported by their rules, **H2 (no material goodput loss) is not**. H3, the hard
requirement, holds across all 75 runs including W6, where seats really run out under overload. The table is a mechanical application of rules written
before the data existed; sections 9.3 and 10 say how much weight each verdict can bear.

### 9.3 What the data show, seed by seed

Ratios are `iasl_default / baseline` (same requests in both arms). Goodput in answers/s, p95 of the service-latency set in ms, refusals as a share of all requests.

**W4 sustained overload (1.5 C)**

| seed | baseline goodput / p95 / refused | IASL goodput / p95 / refused | goodput ratio | p95 ratio |
|---|---|---|---|---|
| 1 | 230 / 1081 / 55.5% | 250 / 898 / 53.6% | 1.08 | 0.83 |
| 2 | 232 / 1091 / 55.6% | 218 / 756 / 59.5% | 0.94 | 0.69 |
| 3 | 300 / 853 / 42.7% | 213 / **6051** / 49.3% | 0.71 | **7.09** |
| 4 | 234 / 1127 / 55.1% | 201 / 865 / 62.7% | 0.86 | 0.77 |
| 5 | 260 / 974 / 49.9% | 218 / 738 / 59.4% | 0.84 | 0.76 |

**W2 gradual**: p95 ratios 0.63, 0.71, 1.40, 0.54, 0.70; goodput ratios 1.02, 0.98, 0.93, 1.04, 0.96 (median 0.98).
**W5 burst + recovery**: p95 ratios 0.68, 0.91, 0.97, 1.15, 1.32 (no clear effect); goodput ratios 1.01, 0.98, 0.96, 0.93, 0.95 (median 0.96).
**W6 scarce seats**: p95 ratios 1.08, 1.04, 0.61, 1.14, 0.84; goodput ratios 0.84, 0.69, 1.11, 0.66, 0.93.

How IASL behaved in W4: in all 5 seeds it made 6 limit changes, took the admission limit **down to its floor (8)** and kept it below capacity for 90 to 94% of the run;
no failed ticks, no fallback.

**What can be said, and what cannot:**

* **Under sustained overload IASL v1 did what its design predicted**: it shortened the wait of the requests it served (W4 median service latency 881 ms to 482 ms, p95 ratio 0.77;
  W2 p95 ratio median 0.70), by turning queue-full refusals into admission refusals (W4 queue-full 55% to 0.9%) and refusing about 4 percentage points more in total
  (W4 55.1% to 59.4%). **Latency of served requests fell and total refusals rose: it is a trade, not a free improvement.**
* **It did not raise throughput, as predicted, and a goodput cost cannot be ruled out.** W4 median goodput ratio 0.86 (fails the 0.90 rule); W2 0.98 and W5 0.96 pass.
  But the baseline's own goodput varies enormously between seeds (W4: 230 to 300; W6: 336 to 441, bimodal), and its high values go with low refusal rates, which looks like
  machine-speed variation (section 10), so a 14% median difference is not clearly distinguishable from noise. The pre-registered rule is applied as written: **not supported**.
  Why goodput might be lower was not established; two untested candidates are (a) refusals are not free in a single-process Python server (every refusal still costs HTTP
  handling and a log line on the event loop that the workers share), and (b) a floor of 8 leaves the queue nearly empty so workers occasionally starve.
* **The latency benefit is not demonstrated for bursts or for scarce-seat overload.** W5 and W6 p95 ratios straddle 1: in W5 IASL was lower in 3 of 5 seeds (median ratio 0.97, range 0.68 to 1.32), in W6 lower in only 2 of 5 (median 1.04, range 0.61 to 1.14). W3 (instantaneous burst) shows no significant latency difference, as H5 predicted.
* **H1's 4 of 5 includes one seed (3) where IASL was far worse** (p95 6.0 s); see section 10. Excluding nothing, as pre-registered.
* **H4 held:** at 0.5 C IASL refused nothing, left the limit at capacity throughout, and p95 was 15 ms vs 14 ms.
* **H5's goodput ratio of 1.23 was unexpected** (a lower refusal rate, 14% vs 18%). With baseline goodput spanning 210 to 235 and IASL 222 to 288 over five seeds this is most likely noise and is reported, not explained.
* **H6 is weakly informative:** recovery time hit the metric's 1-second resolution in nearly every run of both arms (median 1.0 s; baseline up to 3.0 s), so the metric could not separate them.
* **The exploratory `iasl_sensitive` arm** (thresholds halved, no hypothesis) looked somewhat better than the default on W4 p95 (median ratio 0.64 vs baseline, goodput ratio 1.06) and similar elsewhere (W5 0.96; W6 0.77, goodput 0.89). It is reported descriptively only; it shows that outcomes depend on the thresholds, which were never calibrated.

### 9.2 Aggregate tables

Each cell: **median** (min to max) over the valid seeds. Latency = service-latency set, intended-arrival basis (docs/iasl/IASL_EXPERIMENTS.md section 4).

#### w1_normal

| metric | baseline | iasl_default | iasl_sensitive |
|---|---|---|---|
| valid runs | 5 of 5 | 5 of 5 | 0 of 0 |
| goodput /s | 180.0 (180.0 to 180.0) | 180.0 (179.9 to 180.0) | - |
| registrations /s | 180.0 (180.0 to 180.0) | 180.0 (179.9 to 180.0) | - |
| p50 ms | 10 (10 to 10) | 10 (10 to 10) | - |
| p95 ms | 14 (13 to 20) | 15 (14 to 17) | - |
| p99 ms | 26 (19 to 73) | 32 (24 to 41) | - |
| queue-full % | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) | - |
| admission-refused % | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) | - |
| refused total % | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) | - |
| timeout % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| error % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| queue util (mean) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| worker util (mean) | 0.12 (0.10 to 0.16) | 0.13 (0.12 to 0.14) | - |
| semaphore util (mean) | 0.23 (0.21 to 0.28) | 0.24 (0.24 to 0.27) | - |
| time restricted % | - | 0 (0 to 0) | - |

#### w2_gradual

| metric | baseline | iasl_default | iasl_sensitive |
|---|---|---|---|
| valid runs | 5 of 5 | 5 of 5 | 0 of 0 |
| goodput /s | 254.0 (246.4 to 257.1) | 246.3 (238.0 to 259.6) | - |
| registrations /s | 254.0 (246.4 to 257.1) | 246.3 (238.0 to 259.6) | - |
| p50 ms | 580 (282 to 663) | 228 (211 to 344) | - |
| p95 ms | 987 (861 to 1039) | 680 (565 to 1208) | - |
| p99 ms | 1104 (902 to 1235) | 849 (696 to 2502) | - |
| queue-full % | 27.7 (27.1 to 30.1) | 0.0 (0.0 to 0.0) | - |
| admission-refused % | 0.0 (0.0 to 0.0) | 28.7 (27.6 to 32.9) | - |
| refused total % | 27.7 (27.1 to 30.1) | 28.7 (27.6 to 32.9) | - |
| timeout % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| error % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| queue util (mean) | 0.53 (0.48 to 0.55) | 0.28 (0.26 to 0.31) | - |
| worker util (mean) | 0.69 (0.66 to 0.71) | 0.73 (0.68 to 0.79) | - |
| semaphore util (mean) | 0.76 (0.73 to 0.78) | 0.79 (0.73 to 0.82) | - |
| time restricted % | - | 53 (50 to 54) | - |

#### w3_burst

| metric | baseline | iasl_default | iasl_sensitive |
|---|---|---|---|
| valid runs | 5 of 5 | 5 of 5 | 0 of 0 |
| goodput /s | 225.4 (209.9 to 234.6) | 262.3 (221.8 to 287.5) | - |
| registrations /s | 225.4 (209.9 to 234.6) | 262.3 (221.8 to 287.5) | - |
| p50 ms | 1309 (1306 to 1324) | 1100 (988 to 1269) | - |
| p95 ms | 1765 (1721 to 1848) | 1629 (1408 to 1807) | - |
| p99 ms | 1808 (1761 to 1901) | 1681 (1449 to 1846) | - |
| queue-full % | 18.2 (14.8 to 19.8) | 14.4 (8.4 to 17.8) | - |
| admission-refused % | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) | - |
| refused total % | 18.2 (14.8 to 19.8) | 14.4 (8.4 to 17.8) | - |
| timeout % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| error % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | - |
| queue util (mean) | 0.47 (0.44 to 0.51) | 0.45 (0.42 to 0.47) | - |
| worker util (mean) | 1.00 (1.00 to 1.00) | 1.00 (1.00 to 1.00) | - |
| semaphore util (mean) | 1.00 (0.96 to 1.00) | 1.00 (0.95 to 1.00) | - |
| time restricted % | - | 20 (0 to 33) | - |

#### w4_overload

| metric | baseline | iasl_default | iasl_sensitive |
|---|---|---|---|
| valid runs | 5 of 5 | 5 of 5 | 5 of 5 |
| goodput /s | 233.9 (230.2 to 299.8) | 217.8 (200.5 to 249.5) | 247.2 (203.1 to 267.5) |
| registrations /s | 233.9 (230.2 to 299.8) | 217.8 (200.5 to 249.5) | 247.2 (203.1 to 267.5) |
| p50 ms | 881 (692 to 907) | 482 (315 to 579) | 379 (297 to 472) |
| p95 ms | 1081 (853 to 1127) | 865 (738 to 6051) | 720 (648 to 992) |
| p99 ms | 1140 (893 to 1221) | 948 (782 to 8614) | 774 (676 to 1063) |
| queue-full % | 55.1 (42.7 to 55.6) | 0.9 (0.3 to 2.7) | 0.3 (0.0 to 0.6) |
| admission-refused % | 0.0 (0.0 to 0.0) | 58.8 (48.1 to 60.0) | 53.6 (50.1 to 61.8) |
| refused total % | 55.1 (42.7 to 55.6) | 59.4 (49.3 to 62.7) | 54.0 (50.3 to 62.2) |
| timeout % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| error % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| queue util (mean) | 0.95 (0.94 to 0.96) | 0.42 (0.39 to 0.44) | 0.41 (0.39 to 0.44) |
| worker util (mean) | 1.00 (1.00 to 1.00) | 1.00 (0.99 to 1.00) | 1.00 (0.99 to 1.00) |
| semaphore util (mean) | 0.99 (0.98 to 1.00) | 0.99 (0.98 to 0.99) | 0.98 (0.98 to 1.00) |
| time restricted % | - | 92 (90 to 94) | 94 (94 to 95) |

#### w5_burst_recovery

| metric | baseline | iasl_default | iasl_sensitive |
|---|---|---|---|
| valid runs | 5 of 5 | 5 of 5 | 5 of 5 |
| goodput /s | 170.5 (162.0 to 172.6) | 163.3 (158.5 to 167.9) | 163.9 (161.1 to 165.7) |
| registrations /s | 170.5 (162.0 to 172.6) | 163.3 (158.5 to 167.9) | 163.9 (161.1 to 165.7) |
| p50 ms | 10 (10 to 12) | 10 (10 to 11) | 10 (10 to 11) |
| p95 ms | 766 (735 to 1065) | 727 (702 to 1008) | 834 (705 to 911) |
| p99 ms | 879 (762 to 1170) | 985 (797 to 1100) | 912 (754 to 986) |
| queue-full % | 17.6 (16.6 to 21.7) | 3.0 (0.9 to 3.4) | 1.2 (0.6 to 3.0) |
| admission-refused % | 0.0 (0.0 to 0.0) | 17.9 (17.4 to 21.7) | 19.4 (18.0 to 21.0) |
| refused total % | 17.6 (16.6 to 21.7) | 21.1 (18.9 to 23.4) | 20.8 (19.9 to 22.1) |
| timeout % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| error % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| queue util (mean) | 0.13 (0.12 to 0.15) | 0.10 (0.10 to 0.11) | 0.11 (0.10 to 0.11) |
| worker util (mean) | 0.23 (0.23 to 0.30) | 0.22 (0.22 to 0.23) | 0.22 (0.22 to 0.23) |
| semaphore util (mean) | 0.31 (0.30 to 0.39) | 0.30 (0.29 to 0.32) | 0.30 (0.29 to 0.31) |
| time restricted % | - | 71 (57 to 71) | 61 (61 to 71) |
| recovery time s | 1.0 (1.0 to 3.0); not recovered 0 of 5 | 1.0 (1.0 to 1.0); not recovered 0 of 5 | 1.0 (1.0 to 1.0); not recovered 0 of 5 |
| queue drain time s | 0.9 (0.9 to 2.0); not recovered 0 of 5 | 0.7 (0.7 to 1.0); not recovered 0 of 5 | 0.7 (0.7 to 1.0); not recovered 0 of 5 |

#### w6_overload_small_seats

| metric | baseline | iasl_default | iasl_sensitive |
|---|---|---|---|
| valid runs | 5 of 5 | 5 of 5 | 5 of 5 |
| goodput /s | 360.6 (336.0 to 441.3) | 304.1 (287.6 to 374.1) | 324.8 (313.5 to 364.4) |
| registrations /s | 83.8 (78.9 to 100.7) | 72.2 (69.1 to 87.3) | 79.4 (73.0 to 85.3) |
| p50 ms | 554 (448 to 590) | 311 (264 to 367) | 337 (271 to 529) |
| p95 ms | 709 (598 to 809) | 637 (493 to 762) | 532 (469 to 8547) |
| p99 ms | 739 (652 to 862) | 857 (583 to 1329) | 572 (508 to 10873) |
| queue-full % | 31.1 (16.5 to 35.9) | 0.3 (0.0 to 0.7) | 0.0 (0.0 to 0.0) |
| admission-refused % | 0.0 (0.0 to 0.0) | 39.8 (30.2 to 43.3) | 37.3 (14.8 to 41.8) |
| refused total % | 31.1 (16.5 to 35.9) | 40.5 (30.4 to 43.5) | 37.3 (14.8 to 41.8) |
| timeout % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| error % | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| queue util (mean) | 0.95 (0.94 to 0.96) | 0.45 (0.42 to 0.47) | 0.41 (0.38 to 0.45) |
| worker util (mean) | 1.00 (1.00 to 1.00) | 1.00 (0.97 to 1.00) | 1.00 (0.95 to 1.00) |
| semaphore util (mean) | 0.98 (0.96 to 0.99) | 0.97 (0.96 to 0.98) | 0.96 (0.96 to 0.98) |
| time restricted % | - | 92 (90 to 94) | 94 (93 to 95) |


### 9.4 Invalid attempts that were re-run

None.

### 9.5 Cells still invalid after the allowed attempts

None.

---

## 10. Data quality, anomalies and what did not work

* **Two unexplained tail events** (both in IASL arms; no other cell among the 75, including all 15 baseline runs of the overload workloads W4, W5 and W6): `w4_overload / iasl_default / seed 3` (342 answers slower than the 5 s client timeout, maximum 11.1 s)
  and `w6_overload_small_seats / iasl_sensitive / seed 1` (1,351 answers, maximum 13.7 s). Neither run had a timeout recorded. Evidence gathered: the server's own queue wait for processed requests peaked at
  672 ms and its status endpoint answered every 0.26 s throughout, so the delay was **not inside the layer's queue**; the server received about 450 requests/s late in the run against 540/s sent and responses
  kept arriving 4 s after the schedule ended, so requests were delayed **before reaching the layer** (client side, operating system or HTTP front end). My first hypothesis (connections beyond the warmed pool) was tested
  and **did not hold**: a 2,400-connection pool was far worse (every run invalid; p95 60 to 115 s), and two repeats of the same cell at the evaluation settings did **not** reproduce the tail (p95 929 ms and 728 ms).
  The cause is unknown. Two events in 30 IASL overload runs cannot be separated from chance (0 of 15 baseline runs), and they were kept in every statistic as pre-registered.
* **The same seed (3) also had the baseline's best W4 run** (300/s goodput, 42.7% refused) and the cell with the worst IASL p95 ratio in W2 (1.40): the pair for that seed was probably disturbed by machine events.
* **Baseline variability is large**: W6 goodput was 336 to 441 across seeds with a clear two-level pattern. This limits what a five-seed paired comparison can say about goodput.
* **The machine was not quiet.** macOS iCloud sync (`fileproviderd`, `bird`) was using several cores during setup and, later, an unrelated Spotify renderer as well; load averages before runs ranged 4.3 to 11.2. I did not stop these (they are not mine) and recorded the load for every run.
* **Replication not completed.** I planned a post-hoc replication on fresh seeds 6 to 10 for the two overload workloads (`scripts/iasl_plan_replication.json`). It ran twice and was discarded both times because the machine was overloaded (load average 20 to 36): the first time partly because I was running other work (documentation agents) at the same moment, which was my mistake; the second
  time because Spotify and iCloud sync were consuming the CPU. The partial results (invalid runs with p95 of 40 to 120 s) are meaningless and were deleted. **The headline results are therefore from a single evaluation session with no independent replication.**
* **A diagnostic wasted several hours** (the large-pool test above): my own re-run rule re-ran cells that could never become valid. The rule has been left as written in section 8, but note it should have had a time cap.
* **Instrument.** The threaded generator and a single-process async driver both failed above a few hundred requests in flight (section 8); results rely on the multi-process asyncio driver validated against the project generator. Absolute throughput (about 357/s capacity) is specific to this machine.

---

## 11. Conclusions (and the weight they can bear)

1. **Safety (H3) is the strongest result.** In 75 runs, across normal load, gradual ramp, burst, sustained 1.5x overload, burst + recovery, and overload with scarce seats, the database stayed correct in every run
   under IASL and without it: no oversell, no duplicate registration, seat counters consistent, rows consistent with what clients saw. IASL never caused an error response. This supports the design goal that adaptive control is isolated from correctness.
2. **At normal load IASL stays out of the way (H4)**: no refusals, no restriction, indistinguishable latency.
3. **Under sustained overload IASL v1 lowers the latency of the requests it serves** (median about 45% lower, p95 about 20 to 30% lower in W4/W2), by refusing somewhat more (about 4 points) and moving refusals to a cheaper point. It **does not increase throughput**, and
   a goodput reduction of up to roughly 14% (median, W4) could not be excluded or confirmed against baseline noise.
4. **No benefit was demonstrated for bursts, recovery or scarce-seat overload.**
5. **Whether IASL "improves performance" depends on what is valued.** If lower queueing delay for admitted requests matters more than refusing a few percent more requests, the data favour IASL under sustained overload; if goodput or fewest refusals matter most, they do not.
   These findings are for one machine, one synthetic workload family, uncalibrated default thresholds, a single session and five seeds, and should not be generalised.

**What would strengthen or overturn these conclusions:** an independent replication on a quiet machine (command below), more seeds, a multi-process server (to separate refusal cost from DB limits), calibrated thresholds on separate calibration seeds, a lower bound above the worker count for the limit,
a latency-target (rather than only threshold) controller, and the recovery metric at finer than one-second resolution.

## 12. Reproduce

```bash
set -a; source .demo.env; set +a                       # MySQL credentials (git-ignored)
PYTHONPATH=. .venv/bin/python scripts/iasl_experiment.py calibrate --permits 4 --requests 6000 --users 96
PYTHONPATH=. .venv/bin/python scripts/iasl_experiment.py run --plan scripts/iasl_plan_evaluation.json --out results/iasl_experiments/evaluation
PYTHONPATH=. .venv/bin/python scripts/iasl_experiment.py report results/iasl_experiments/evaluation
# the replication that could not be completed here (needs a quiet machine; quit Spotify, pause iCloud sync, stop other containers):
PYTHONPATH=. .venv/bin/python scripts/iasl_experiment.py run --plan scripts/iasl_plan_replication.json --out results/iasl_experiments/replication
```

Unit tests of the analysis, the decision rules and the load driver: `tests/test_iasl_experiment_analysis.py`, `tests/test_iasl_experiment_report.py`, `tests/test_iasl_experiment_loadgen.py`.
The experiments only ever touch the database `concurrentreg_exp`; the harness refuses to run against any other.
