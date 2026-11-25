# IASL Detailed Design (as built)

| | |
|---|---|
| **Status** | **Implemented.** Began as the Stage 1 proposal; reconciled with the code in `app/iasl/`, `app/iasl_api.py` and `app/os_layer/request_pipeline.py`. Section 14 lists every place the build differs from what was first proposed. |
| **Companions** | `IASL_ARCHITECTURE.md` (placement, threads, safety layers), `IASL_CONFIGURATION.md` (settings), `IASL_TESTING.md` (test record), `IASL_EXPERIMENTS.md` (measured evaluation). Existing-code claims are cited in `IASL_IMPLEMENTATION_AUDIT.md`. |
| **Default values** | Every numeric default below is **provisional and uncalibrated**. None is an experimentally validated value. `IASL_EXPERIMENTS.md` ran the defaults unmodified and reports what happened; it does not establish that they are good values. |
| **Performance claims** | None are made in this document. |

---

## 1. Scope

**Built (v1):** a deterministic, rule-based loop that observes the OS layer and moves one parameter (the admission depth limit) within hard bounds; read-only status endpoints; a bounded decision log; fallback.

**Not built:** resizing the queue, workers or semaphore (unsupported by the current classes); request classification/filtering; a server-side request timeout (so timeout rate is reported as *unavailable*); any runtime-write endpoint; ML/LLM/RL; multi-process deployment (all counters are per process).

---

## 2. Design invariants

Each is tested (`IASL_TESTING.md` section 3 maps requirements to tests).

| # | Invariant | Where it lives |
|---|---|---|
| I1 | With `IASL_ENABLED` unset/false, no IASL object exists, no hook is installed, and `submit()` behaves exactly as before. | `app/main.py` `create_app`; `request_pipeline.py` (hooks default to `None`) |
| I2 | The effective admission limit is always an integer in `[1, queue_capacity]`. | `admission.py` `set_limit` / constructor |
| I3 | When the limit equals `queue_capacity`, the admission check is skipped; behaviour is identical to the existing queue-full path. | `admission.py` `check` |
| I4 | An admission rejection is never reported as a registration outcome and never reaches the database. | `request_pipeline.py` `submit` |
| I5 | Nothing under `app/iasl/` imports `app.registration_service`, `app.models`, `app.database`, `app.seed`, `app.os_layer`, any SQL library or `importlib`; nothing under `app/os_layer/` imports `app.iasl`. | `tests/test_iasl_boundary.py` |
| I6 | An exception in the admission check or the observer never fails a request. | `request_pipeline.py` `_admitted`, `_tell_observer` |
| I7 | If the controller thread stops, the request path reverts to the fallback limit within `IASL_WATCHDOG_SECONDS` without that thread's help. | `admission.py` `effective_limit` |
| I8 | The controller changes at most one parameter per tick, by at most the overload move, and not within the cooldown of the previous change. | `controller.py`, `guardrails.py` |
| I9 | The seat/duplicate invariants checked by `demo_api.database_state()` hold after every IASL MySQL test run. | `tests/test_iasl_app.py` |

**Soft bound with several submitters.** I2 and I3 concern the *limit*. How tightly the *queue depth* follows the limit depends on the caller: `submit()` runs on the single event-loop thread in production, where the check and the enqueue are not interleaved with another submitter and the depth is held at the limit (tested). If several threads call `submit()` at once they can all pass the depth check before any enqueues, so the depth can exceed the limit by at most (submitters - 1); the queue's own capacity is a hard bound regardless.

---

## 3. Choice of control parameter

| Option | Request-path cost | Failure hazard | Effect | Verdict |
|---|---|---|---|---|
| **A. Admission depth limit** (admit iff queue depth < L) | one int compare, no lock | none beyond a wrong number (bounded by I2) | bounds queueing delay | **Chosen** |
| B. In-flight limit (queued + running) | counter inc on admit, dec on every exit | a missed exit path (cancel, error, shutdown) **leaks slots permanently** | bounds total concurrency | Rejected for v1: leak risk on the correctness-adjacent path |
| C. Token-bucket rate limit | lock or atomic on every request | needs a rate target; rate does not equal load when service time varies | smooths arrivals | Rejected for v1: needs a calibrated rate; more state |
| D. Resize queue/workers/semaphore | n/a | **cannot be done safely with the current classes** (audit section 6) | n/a | Out of scope |

Consequences accepted with A: it limits *waiting*, not *running*; it cannot raise throughput; the effect is a latency-versus-refusal trade.

**Feedback hazard that shaped the signals.** If the analyzer counted *admission rejections* as an overload signal, lowering L would cause rejections, which would look like overload, which would lower L further (positive feedback). So **admission rejections are never an analyzer input**, and queue utilisation is measured against the queue's **physical capacity**, not against L. The loop is closed on latency and physical queue pressure.

---

## 4. Metrics (`app/iasl/telemetry.py`, `metrics.py`, `types.py`)

### 4.1 Telemetry recorder (the only new request-path write)

`OutcomeRecorder` is fed by the layer *after* the caller's Future is resolved, on the worker thread, and also when a queued job was cancelled.

```python
class OutcomeRecorder:
    def __init__(self, ring_size: int = 2048, clock=time.monotonic): ...
    def on_completed(self, code: str, queue_wait_s, db_section_s, server_s) -> None: ...   # one lock, O(1)
    def on_cancelled(self) -> None: ...
    def counters(self) -> dict:   # {"by_outcome": {...}, "completed": n, "cancelled": n, "invalid_observations": n}
    def window(self, now, window_s, min_samples) -> WindowStats:   # copy ring under lock, sort outside
```

* `on_completed` has **no timestamp argument**: the completion time is stamped by the recorder's own clock, the same clock the readers pass to `window()` (a caller-supplied time from a different clock would silently corrupt the window).
* `server_s` = worker finished - enqueued (end to end inside the server, includes queue wait). `db_section_s` (semaphore hold, which includes row-lock wait, so it is *not* pure DB time) is accepted for completeness but **not stored**; the controller does not use it.
* Ring: `deque(maxlen=IASL_LATENCY_RING_SIZE)` of `(finished_at, queue_wait_s, server_s)`. If completions exceed the ring within the window, `WindowStats.covered_s` reports the shorter span really covered. Unusable durations (negative, NaN, non-numeric) are counted in `invalid_observations` and never stored.
* Percentiles use the **nearest-rank rule of the workload generator** (`percentile()` in `workload_generator.py`); fewer than `IASL_MIN_LATENCY_SAMPLES` samples gives `None`, never an extrapolation. `counters()["completed"]` excludes cancelled jobs.

### 4.2 Sample schema

Instantaneous values, interval measurements and window measurements are different kinds and are kept in separate typed blocks.

```python
@dataclass(frozen=True, eq=False)
class MetricsSample:
    taken_at: float                 # monotonic
    wall_time: str                  # ISO, for humans
    interval_s: float | None        # time since previous sample (None on first / after a restart)
    quality: MetricQuality          # OK | DEGRADED | INVALID | RESTART  (STALE is assigned later, by the analyzer)
    restart: bool                   # kept separately so a RESTART is never hidden by a higher-precedence INVALID
    issues: tuple[str, ...]         # why quality is not OK
    gauges: Gauges                  # instantaneous
    interval: IntervalRates | None  # derived from counter differences over interval_s
    window: WindowStats             # over the last IASL_LATENCY_WINDOW_SECONDS
    admission_limit: int | None
    unavailable: dict               # metric -> reason (static, see 4.5)
```

| Block | Fields | Source | Kind |
|---|---|---|---|
| `Gauges` | `queue_depth`, `queue_capacity`, `queue_utilization`, `workers_alive`, `workers_active`, `workers_idle`, `worker_utilization`, `sem_permits`, `sem_in_use`, `sem_available`, `sem_waiting`, `sem_utilization`, `sem_waiting_ratio` (waiting / permits; added because the analyzer needs it) | `snapshot()` (existing) | instantaneous |
| `IntervalRates` | `arrivals_per_s`, `queue_full_rejections_per_s`, `admission_rejections_per_s`, `completed_per_s`, `queue_full_rejection_rate` (queue-full refusals / arrivals; `0.0` when no arrivals), `error_rate` (`ERROR` outcomes / completions; `None` when no completions), `avg_queue_wait_s` (delta `queue_wait.total_s` / delta `jobs_dequeued`) | counter differences of `snapshot()` and of the recorder | interval |
| `WindowStats` | `covered_s`, `samples`, `queue_wait_p50/p95/p99_s`, `server_latency_p50/p95/p99_s` | recorder ring | sliding window |

`arrivals` = delta of (`accepted` + `rejected_queue_full` + `rejected_shutting_down` + `admission.rejected`). Reused from the existing snapshot: every gauge, `accepted`, both queue refusals, `queue_wait.total_s`/`jobs_dequeued`. **New**: `admission.rejected` (counted by the layer) and the recorder's outcomes and window. Without a recorder, `completed_per_s` falls back to the layer's `jobs_finished` and `error_rate` is `None`. Lifetime high-water marks (`max_depth`, `max_active`, `max_waiting`) are **not used** (they cannot be windowed).

### 4.3 Counters per lifecycle stage

Mapped in Architecture section 3. The collector never recomputes a counter that already exists; it only differences them.

### 4.4 Validation, restart, staleness

* **Validation** per field: finite number, `>= 0`, `queue_depth <= queue_capacity`, `workers_active <= workers_alive`, `sem_in_use <= sem_permits`. A violation sets `quality=INVALID` with the field named in `issues` (for example `queue.depth_invalid`, `queue.depth_exceeds_capacity`); the offending value becomes `None`, never silently clamped.
* **Snapshot failure** (an exception) gives `INVALID` with `issues=("snapshot_failed:<ExceptionType>",)`. A failing recorder gives `INVALID` with `recorder_failed:<ExceptionType>`.
* **Restart**: the layer object changed (re-attach), or any cumulative counter decreased: `quality=RESTART`, `restart=True`, `interval=None`. Analyzer history is cleared (the `/demo/os-layer` swap resets all counters).
* **Long interval** (`dt > 5 x IASL_SAMPLING_INTERVAL_S`, i.e. the loop stalled): `DEGRADED`, rates still computed but flagged. `non_positive_interval` and `no_alive_workers` are also `DEGRADED`.
* **Staleness** is judged where the sample is *used*: `StateAnalyzer.assess(sample, now)` treats a sample older than `IASL_STALE_METRIC_SECONDS` as `STALE`.
* **Precedence** when several apply: INVALID > RESTART > DEGRADED > OK. The first sample after start has no interval values and is `OK` (warming up, not a fault).
* **Idle is not degraded.** No traffic means no latency samples; that is a valid state, not missing data.

### 4.5 Unavailable metrics (reported, never invented)

| Metric | Reason |
|---|---|
| `timed_out_requests`, `timeout_rate` | No server-side request timeout exists (audit section 6). Client-side `TIMEOUT` is visible only in result files. |
| `db_timeouts` | No DB-level timeout configured. |
| `db_lock_wait` | Only obtainable from `information_schema.innodb_trx` on MySQL with the `PROCESS` privilege, cached by InnoDB when polled faster than about 0.1 s; absent on SQLite; **not read by application code**. |
| DB error *count* | Derived from the recorder's `ERROR` outcomes only; errors that escape the handler are in `workers.unexpected_errors`. |

---

## 5. State analyzer (`app/iasl/analyzer.py`)

Input: one `MetricsSample`. Output: `Assessment(state, previous_state, quality, held, candidate, signals, transition, reason, worse_streak, better_streak)`; each `Signal` carries its value, class, level and thresholds.

### 5.1 Signals

| Signal | Definition | Class | Pressure / overload (enter) |
|---|---|---|---|
| `queue_utilization` | mean of the last `IASL_SMOOTHING_SAMPLES` of depth / **physical capacity** | primary | 0.50 / 0.85 |
| `queue_wait_p95_s` | window p95 of queue wait | primary | 0.10 s / 0.50 s |
| `queue_full_rejection_rate` | interval | primary | 0.01 / 0.05 |
| `error_rate` | interval, `ERROR` / completions | primary | 0.02 / 0.10 |
| `worker_utilization` | mean of the last k of active / alive | corroborating | 0.90 / 0.99 |
| `semaphore_waiting_ratio` | mean of the last k of waiting / permits | corroborating | 1.0 / 3.0 |

Worker or semaphore saturation alone is **not** pressure: all workers busy with an empty queue is a healthy, fully used system. Backlog is the decisive evidence; utilisation corroborates. All thresholds are **provisional**.

### 5.2 Levels and per-signal hysteresis

A signal's level is 0 (ok), 1 (pressure), 2 (overload). It rises when the value reaches an *enter* threshold and falls only when the value drops below `enter x IASL_EXIT_RATIO` (default 0.7), so a signal hovering at a threshold does not flap. A missing value (`None`) is excluded and its level reset to 0 (old pressure is not carried forward).

### 5.3 Aggregation

```
candidate = OVERLOADED      if  >=1 primary signal at level 2  AND  >=1 other signal at level >= 1
          = UNDER_PRESSURE  if  >=1 primary signal at level >= 1   OR  >=2 corroborating signals at level >= 1
          = HEALTHY         otherwise
```

If fewer than `IASL_MIN_PRIMARY_SIGNALS` (default 2) primary signals are available the sample is treated as `DEGRADED` and **the state is held**. (`queue_full_rejection_rate` is `0.0` with no arrivals, so an idle system still has two primary signals after its first sample.)

### 5.4 State machine with consecutive-sample validation

* **Escalate** (towards OVERLOADED): after `IASL_ESCALATE_SAMPLES` (default 2) consecutive candidates worse than the current state. A level is skipped only if every candidate in the streak was the higher state.
* **De-escalate** (towards HEALTHY): one level at a time, after `IASL_DEESCALATE_SAMPLES` (default 5) consecutive better candidates.
* Fast to worsen, slow to recover, by design. A sample equal to the current state resets both streaks. `DEGRADED` / `INVALID` / `STALE` samples **hold** the state and freeze the streaks (they do not reset them).
* `RESTART` resets history and the state to HEALTHY (with a recorded transition if it was not already).
* Every transition records the signals, levels, thresholds crossed and a plain-language reason.

---

## 6. Controller, decision engine, guardrails

### 6.1 Parameter definition (`types.py` `ControlParameter`)

```python
@dataclass(frozen=True)
class ControlParameter:
    name: str                  # "admission_depth_limit"
    minimum: int               # IASL_ADMISSION_MIN, automatic = worker count
    maximum: int               # IASL_ADMISSION_MAX, capped at the queue capacity
    initial: int               # IASL_ADMISSION_INITIAL, automatic = maximum (identical to no IASL)
    step: int                  # max(1, round(IASL_ADJUSTMENT_STEP x (maximum - minimum)))
    cooldown_s: float          # IASL_COOLDOWN_SECONDS (a DECREASE may follow the last change after this)
    increase_cooldown_s: float # IASL_INCREASE_COOLDOWN_SECONDS (an INCREASE may follow after this; longer by default)
    reversal_lockout_s: float; overload_multiplier: int
    max_reversals: int; oscillation_window_s: float; oscillation_hold_s: float
    # max_move = step x overload_multiplier;   built by ControlParameter.from_config(config, bounds)
```

Minimum, maximum, initial, step and cooldowns are all explicit. `minimum` defaults to the worker count so a burst never finds fewer admitted slots than workers; this is a **provisional** choice. The step is stored as whole units (not the fraction).

### 6.2 Decision engine (`engine.py`; pure function, no side effects)

`decide(assessment, param, state, in_fallback=False) -> ProposedAction(kind, parameter, target, rule_id, reason)`, where `target` is the value wanted **before** bounds are applied (`None` for a hold). First matching rule wins:

| Rule | Condition | Action | Reason text (abridged) |
|---|---|---|---|
| R0 | `in_fallback` is true | `HOLD` | "fallback active; limit pinned at the fallback value" |
| R1 | the assessment was held or its quality is not OK (`DEGRADED`, `STALE`, `INVALID`, `RESTART`) | `HOLD` (never increase) | "metrics not reliable ...; never increasing on bad data" |
| R1b | the state is worse than HEALTHY but **this sample** looks HEALTHY | `HOLD` | "recovering: neither tightening further nor relaxing yet" |
| R1c | the state is HEALTHY but this sample already shows pressure or overload | `HOLD` (never increase) | "waiting for it to be confirmed" |
| R2 | OVERLOADED, `L > minimum` | `DECREASE` by `overload_multiplier x step` | "overloaded: ..." |
| R3 | UNDER_PRESSURE and `queue_utilization` or `queue_full_rejection_rate` at level >= 1 | `DECREASE` by `step` | "queue pressure rising: ..." |
| R4 | UNDER_PRESSURE otherwise (latency, error or corroborating only) | `HOLD` | "pressure is not queue-driven; not adding admission" |
| R5 | HEALTHY and `L < maximum` | `INCREASE` by `step` | "healthy for sustained samples; restoring admission" |
| R6 | HEALTHY and already at the maximum | `HOLD` | "healthy and already at the maximum; no change needed" |

At the floor, R2 and R3 return a `HOLD` under their own rule id ("already at the minimum"), so a hold at the minimum is never reported as R6.

R1b and R1c were added during integration: the analyzer's state is deliberately slow to recover (section 5.4), and without R1b the engine kept tightening for several ticks after the load had gone (observed in the closed-loop test: the limit fell 24 -> 16 -> 8 with an empty queue). When the state is worse than the current sample, the engine acts on the milder of the two (an OVERLOADED state with an UNDER_PRESSURE sample uses R3, not R2), and it only relaxes when both the state and the sample are HEALTHY. R0 is part of the pure function; the controller handles fallback itself (section 6.6) and does not call `decide()` while in fallback.

### 6.3 Guardrails (`guardrails.py`; module functions over immutable values)

`review(proposed, param, state, now) -> Verdict(result: ALLOW | CLAMP | BLOCK, final_value, blocked_by, note)`, and `after_applied(state, param, kind, new_value, now) -> (new_state, oscillating)`:

| Check | Rule |
|---|---|
| Known parameter / action / target | only the registered parameter; only `INCREASE`/`DECREASE`; a target that is not a whole number, or does not move in the stated direction, is rejected |
| Step size | a move larger than `step x overload_multiplier` is cut to it (`CLAMP`) |
| Bounds | the value is clamped into `[minimum, maximum]`; if that leaves no change, `BLOCK(at_bound)`. Checked **before** timing so the reported reason is the most useful one |
| Oscillation hold | while `now < hold_until`, every change is blocked (`oscillation_hold`) |
| Cooldown | measured from the previous change of either kind and chosen by the **proposed** move: a DECREASE waits `cooldown_s`, an INCREASE waits `increase_cooldown_s`. A needed decrease right after an increase is therefore prompt, and relaxing is always slower than tightening |
| Reversal lockout | an INCREASE is blocked until `reversal_lockout_s` after a DECREASE, so the effect of the decrease is observed first |
| Oscillation detection | `after_applied` counts direction reversals inside `oscillation_window_s`; at `max_reversals` it starts a hold of `oscillation_hold_s` and clears the count |

The engine's target is deliberately **not** pre-clamped, so the guardrails do the clamping and the tests can prove it. `AdmissionController.set_limit` repeats the hard bound check independently (defence in depth, I2).

### 6.4 Admission controller (`admission.py`, on the request path)

```python
class AdmissionController:
    def __init__(self, capacity, initial, fallback_limit, watchdog_s, clock=time.monotonic): ...
    def check(self, queue_depth) -> bool:    # True = admit. O(1), lock-free
        limit = self.effective_limit()
        return True if limit >= self.capacity else queue_depth < limit
    def set_limit(self, value) -> None       # ValueError unless 1 <= value <= capacity (previous value kept)
    def heartbeat(self); enter_fallback(self); exit_fallback(self)   # exit also counts as a sign of life
    def effective_limit(self)                # fallback limit if in fallback OR heartbeat older than the watchdog
    def stats(self) -> dict                  # limit, configured_limit, capacity, fallback, fallback_limit, watchdog_tripped, seconds_since_heartbeat
```

The `submit()` change in `request_pipeline.py` (replacing the old placeholder comment):

```python
if self.admission is not None and not self.queue.is_shutdown and not self._admitted(job):
    with self._lock: self._rejected_admission += 1
    future.set_result(RegistrationResult(ADMISSION_REJECTED, "Request rejected by admission control"))
    self._log_rejection(job, ADMISSION_REJECTED)
    return future
outcome = self.queue.try_put(job)   # unchanged
```

`_admitted(job)` calls `admission.check(job.queue_depth_at_arrival)` (the depth `submit()` already reads for its log line, so no extra `qsize()`); any exception returns `True` (admit) and is logged once. A shut-down queue is not asked (it keeps its own `SHUTTING_DOWN` message). The HTTP response is **503** (`HTTP_STATUS[ADMISSION_REJECTED]` in `app/main.py`) with the body `{"success": false, "message": "Request rejected by admission control"}`, distinct from the queue-full message so clients and experiments can tell them apart. `Retry-After` is deliberately not added.

`submit()` runs on the event-loop thread; the check performs a few attribute reads, one clock read and an integer comparison, and takes no lock on the admit path. The layer's `snapshot()` carries an additive `"admission"` block (`enabled`, `rejected`, `limit`, `configured_limit`, `fallback`, `watchdog_tripped`) **only while an admission controller is installed**, so with IASL off the snapshot is exactly as before.

### 6.5 Decision record (`types.py` `Decision`)

Emitted for every limit change, state transition, guardrail block, fallback enter/exit, and attach/reset. Repeated identical idle `HOLD` ticks or identical blocks are **coalesced**: counted, and reported as `suppressed_since_last` on the next recorded decision, so a quiet system does not flood the log.

```json
{
  "id": 17, "event": "iasl_decision", "at_wall": "2026-11-25T10:00:03.250", "at_monotonic": 1234.56,
  "previous_state": "UNDER_PRESSURE", "current_state": "OVERLOADED",
  "metrics_used": {
    "signals": {"queue_utilization": {"value": 0.91, "level": 2, "pressure": 0.5, "overload": 0.85}, "...": {}},
    "quality": "OK", "transition": "UNDER_PRESSURE -> OVERLOADED: ...", "admission_limit_seen": 160,
    "sample_issues": [], "interval_s": 0.5},
  "action": "DECREASE", "parameter": "admission_depth_limit",
  "previous_value": 160, "new_value": 122,
  "rule": "R2", "reason": "overloaded: queue_utilization=0.91 ...; reducing by 38",
  "guardrail": "ALLOW", "blocked_by": null, "suppressed_since_last": 3
}
```

Actions are `INCREASE`, `DECREASE`, `HOLD` (a state change, or a blocked/refused attempt: `guardrail` and `blocked_by` say which), `FALLBACK_ENTER`, `FALLBACK_EXIT` and `RESET`. Stored in a bounded deque (`IASL_DECISION_LOG_SIZE`) and also logged as JSON on logger `iasl`, in the existing `json.dumps` + `event` style, so `tests/conftest.py:log_events()` works unchanged.

### 6.6 Adaptive controller (`controller.py`)

Owns the parameter state (current value, last change time and direction, reversal history, oscillation hold) and performs the seven steps of the loop: observe (the sample), determine state (the assessment), select one action (engine), validate (guardrails), apply (`admission.set_limit`), record (decision), observe the result on the next tick. It calls the admission controller's `heartbeat()` at the end of each tick.

* **Failures:** a tick that raises calls `record_failure`; at `IASL_FALLBACK_AFTER_FAILURES` (default 3) consecutive failures, or `IASL_FALLBACK_AFTER_DEGRADED` (default 10) consecutive untrusted (`INVALID` / `STALE` / `DEGRADED`) assessments, it enters fallback. A single `RESTART` sample does not count towards the untrusted streak.
* **Fallback:** `enter_fallback` puts the limit at the fallback value. While in fallback the controller does not call `decide()`. Fallback exits after `IASL_FALLBACK_RECOVERY_SAMPLES` (default 10) consecutive `OK`, non-held ticks; the controller hands the limit back at the fallback value first (no jump) and the cooldown applies before its first move.
* `IASL_FALLBACK_MODE`: `baseline` (default; fallback limit = queue capacity, identical to running without IASL) or `conservative` (`max(minimum, capacity // 2)`).
* **Oscillation:** two records are written: the change itself and a `HOLD` with `blocked_by="oscillation_detected"`.
* **Re-attach:** `reinitialize(bounds, fallback_limit, reason, applier=...)` recomputes the parameter, clears fallback state, switches to the new admission controller and records a `RESET`.

---

## 7. Runtime and lifecycle (`runtime.py`)

```python
class IASLRuntime:
    def __init__(self, config, clock=time.monotonic, wall_clock=datetime.now): ...
    def attach(self, layer, strict=True)  # build admission + recorder for this layer, install hooks, reset state
    def start(self)                       # spawn the daemon thread named "iasl-controller" (RuntimeError before attach or twice)
    def stop(self, timeout_seconds=5.0)   # set the event and join; logs iasl_stop_timeout if the thread will not stop
    def tick(self)                        # one full loop iteration; public so tests are deterministic; never raises
    def snapshot(self) -> IASLSnapshot    # immutable: enabled, attached, running, ticks, failed_ticks, sample, assessment, controller, admission
    def history(self); decisions(self, limit=None); describe(self); now(self)
```

* The loop uses drift-free scheduling (`deadline += interval`), catches every exception per tick (the last-resort handler logs `iasl_loop_error`), and **does not fire a burst of catch-up ticks** if a tick overran: it skips ahead.
* `lifespan` order: build layer -> `iasl.attach(layer)` (strict) -> `layer.start()` -> `iasl.start()`; shutdown: `iasl.stop()` -> `layer.stop()`.
* `reconfigure_os_layer` (`POST /demo/os-layer`): `iasl.attach(new_layer, strict=False)` **before** the new layer takes traffic. Bounds are recomputed from the new size and **clamped** (the server is already running, so it must not refuse); the attach is logged as an `iasl_attached` event and a `RESET` decision is recorded. The old layer keeps its own admission controller, which stops receiving heartbeats and falls back to its fallback limit while it drains.
* Published state is replaced as a whole immutable object, and recent history as an immutable tuple, so HTTP handlers never take the runtime lock. Recent history holds 120 samples.
* `tick()` and `attach()` share one re-entrant lock (attach can run on a request thread).
* Pre-existing, not caused by IASL and not changed: `lifespan` stops the layer captured in its closure, so after a `/demo/os-layer` swap the *original* layer is stopped again at shutdown and the replacement is not. IASL keeps its own handle and stops cleanly regardless.

---

## 8. Read-only API (`app/iasl_api.py`; serializers in `app/iasl/serialize.py`)

Four `GET` routes only; any other method returns 405. Handlers read the snapshot published by the last tick (decisions: a short-lock copy of the bounded log), do no I/O, and never call into the OS layer. With IASL off they answer `{"enabled": false, "message": ...}` (`/iasl/config` still shows the settings that would apply).

| Endpoint | Content |
|---|---|
| `GET /iasl/status` | `enabled`, `attached`, `running`, `state` and `state_reason`, `assessment_quality`, `metrics_quality`, `current_metrics`, `admission` (`limit_in_force`, `configured_limit`, `capacity`, `minimum`, `maximum`, `initial`, `step`), `fallback` (`active`, `watchdog_tripped`, `mode`, `fallback_limit`), `last_control_action`, `last_decision`, `last_decision_reason`, `loop` counters, a calibration note |
| `GET /iasl/metrics[?history=0..120]` | `sample` (typed blocks `gauges` / `interval` / `window`, `quality`, `issues`, `age_s`, `unavailable`), `analysis` (state, signals with levels and thresholds, streaks, transition), optional compact `history` |
| `GET /iasl/decisions[?limit=1..200]` | `returned`, `kept`, a note, and `decisions` oldest first |
| `GET /iasl/config` | `settings`, `environment_variables`, `resolved` bounds, `read_only: true`, how to change it, a calibration note |

`last_control_action` is the last *real* action (a change, fallback or reset), not an idle hold.

---

## 9. Configuration

All settings, defaults and ranges are in `IASL_CONFIGURATION.md`, read from `app/iasl/config.py` (`IASLConfig`, a frozen dataclass separate from `OSLayerConfig`, whose exact shape an existing test asserts). Environment variables are parsed once at start-up; an invalid value raises `ValueError` naming the variable and the server does not start. The brief's illustrative `IASL_HEALTHY_THRESHOLD` / `IASL_PRESSURE_THRESHOLD` / `IASL_OVERLOAD_THRESHOLD` are replaced by per-signal threshold pairs, because one scalar cannot express a multi-signal analyzer. Capacity-dependent checks (`min <= initial <= max <= capacity`) run in `attach()` via `IASLConfig.resolve_bounds`: strict at start-up (refuses to start), lenient at a `/demo/os-layer` swap (clamps and logs).

---

## 10. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Disabled | config | no IASL objects (I1) |
| Bad config | parse | refuse to start, name the variable |
| `snapshot()` raises | collector | sample `INVALID`; engine R1 holds; fallback after N untrusted ticks |
| Counter goes backwards / layer swapped | collector | `RESTART`; analyzer history cleared |
| Metric NaN / negative / out of range | collector | `INVALID`, value `None` |
| Sample older than the stale limit | analyzer (`assess(sample, now)`) | `STALE`; state held |
| Too few primary signals | analyzer | `DEGRADED`; state held |
| Controller tick raises | runtime / controller | counted; fallback after N consecutive failures |
| Controller thread dead or stalled | request-path watchdog | fallback limit (I7) |
| Admission check raises | `submit()` | admit, logged once (I6) |
| Observer raises | worker | ignored, logged once (I6) |
| Limit set out of `[1, capacity]` | `AdmissionController` | `ValueError`; unchanged |
| Oscillation | guardrails | hold, logged |
| Shutdown while admitting | `submit()` | `SHUTTING_DOWN` message preserved |

---

## 11. Tests

The test record, with commands and results, is `IASL_TESTING.md`. In short: 18 files `tests/test_iasl_*.py`, of which 15 test IASL itself (unit tests per module, integration through the real OS layer and application, MySQL-only correctness tests, the import-boundary test, robustness and edge-path tests) and 3 test the experiment tooling (`scripts/iasl_analysis.py`, `iasl_loadgen.py`, `iasl_report.py`); plus `tests/iasl_enabled_plugin.py`, which runs the existing unmodified suite with IASL on. Time is injected (`clock`) and the loop is driven by `IASLRuntime.tick()`, so unit tests do not sleep.

---

## 12. Integration changes, file by file

Listed in Architecture section 7. Two points worth stating here:

* **Rejection classification (distinct response).** `ADMISSION_REJECTED` was added to `workload_generator.py` (`ALL_CATEGORIES`, `KNOWN_RESPONSES[(503, "Request rejected by admission control")]`) and to the frontend `Category` type, theme and comparison table. Old result files lack the key; the frontend reads counts with `?? 0`. The excerpted `arrival_offsets` function and the other excerpted backend lines are untouched (a frontend test asserts they are exact).
* **`/os-layer/status` stays backward compatible**: it gains only the additive `"admission"` block, and only while IASL is on. `test_api.py` asserts specific keys, not the whole body, and the frontend parser checks specific fields only.

---

## 13. Evaluation

Not planned here any more: the evaluation was designed, pre-registered, run and written up in **`IASL_EXPERIMENTS.md`** (set-up, workloads, metric definitions, hypotheses and decision rules, deviations, results and limitations). This document makes no claim about performance.

---

## 14. Differences between the proposal and the build

| Area | Proposed | As built |
|---|---|---|
| Decision engine | `decide(assessment, sample, param_state)` returning a `delta`; rules R0 to R6 | `decide(assessment, param, state, in_fallback=False)` returning `ProposedAction(kind, parameter, target, rule_id, reason)` with the pre-bounds target; **R1b and R1c added** (observed flaw: tightening on a stale state); R1 covers every held or non-OK assessment including `RESTART`; the controller does not call `decide()` in fallback, so R0 is reachable only by a direct call |
| Guardrails | a `Guardrails` class | module functions `review()` and `after_applied()` |
| Cooldown | "after a decrease / after an increase" | chosen by the **proposed** move, measured from the previous change of either kind |
| `ControlParameter` | `step_fraction` | integer `step` plus the lockout, multiplier and oscillation settings |
| `Gauges` | no `sem_waiting_ratio` | `sem_waiting_ratio` added (the analyzer needs it) |
| `OutcomeRecorder.on_completed` | design text implied a caller time; `counters()` returned `dict[str, int]` | **no timestamp argument** (stamped by the recorder's own clock); `counters()` returns `{by_outcome, completed, cancelled, invalid_observations}`; `window()` takes `min_samples` |
| OS-layer hooks | duck-typed hooks, `submit()` calls `qsize()` | duck-typed, as proposed; the check reuses `queue_depth_at_arrival` (no extra `qsize()`); `_admitted` and `_tell_observer` swallow and log-once any hook error |
| `/os-layer/status` `admission` block | `enabled`, `limit`, `rejected`, `fallback` | also `configured_limit` and `watchdog_tripped`; present only while IASL is on |
| Decision record | flat `metrics_used`; `holds_since_last_event` | nested `signals` (value, level, thresholds), `quality`, `transition`, `admission_limit_seen`, `sample_issues`, `interval_s`; coalescing is reported as `suppressed_since_last` |
| Snapshot-failure issue text | `snapshot_failed` | `snapshot_failed:<ExceptionType>` |
| Staleness | "judged by the controller" | judged by the analyzer's `assess(sample, now)` |
| Runtime | `attach`, `start`, `stop`, `tick`, `snapshot` | also `history()`, `decisions()`, `describe()`, `now()`; `attach(layer, strict=True)`; a loop that skips ahead instead of firing catch-up ticks; a lock-free published history |
| Re-attach record | "an `iasl_attached` decision is logged" | an `iasl_attached` log event **and** a `RESET` decision |
| Admission-limit exactness | not discussed | exact with the single event-loop submitter; overshoot by at most (submitters - 1) with several (tested) |
| `IASL_ENABLED` spellings | `1/true/yes` or `0/false/no` | also `on` / `off`, case-insensitive |
| Test plan | a plan | built; recorded in `IASL_TESTING.md` |
| Evaluation preview | a plan preview in this document | moved to, and superseded by, `IASL_EXPERIMENTS.md` |

All eight "design choices you may overrule" from the proposal were kept as built: the admission **depth** limit; a minimum equal to the worker count; 503 with a distinct message and no `Retry-After`; duck-typed hooks so `os_layer` never imports `app.iasl`; `baseline` as the default fallback; coalesced idle `HOLD` ticks; `create_app(os_config=None, iasl_config=None)`; and prompt decreases with slow increases.
