# ConcurrentReg — how to explain the OS part and the testing

*Team Vornics. Every number below was measured on 2026-10-19 on this machine (MySQL 8.4.11 in Docker). Where something is not built or not proven, this report says so.*

---

## 0. The one-page cheat sheet

**What it is.** A research prototype that studies what happens when many students try to register for the *same few seats* at the *same moment*, and how to keep the answer correct while keeping the server under control.

**Three ideas to remember: LOCK, LIMIT, PROVE.**

| Idea | In one line | Where |
|---|---|---|
| **LOCK** | The database locks a course's row while one request checks and takes a seat, so two requests can never take the last seat. | MySQL `SELECT ... FOR UPDATE`, plus `UNIQUE` and `CHECK` rules |
| **LIMIT** | Before requests reach the database they pass a bounded queue, a fixed team of worker threads and a semaphore, so overload becomes a polite "no" instead of a meltdown. | `app/os_layer/` |
| **PROVE** | 188 automated tests, including ones that fire real concurrent requests at real MySQL, plus tests we deliberately break to show they can fail. | `tests/` |

**The numbers worth memorising**

| Number | Meaning |
|---|---|
| **188 / 188** | The original Python suite on MySQL 8.4.11 (InnoDB). 0 failed, 0 skipped. (The IASL layer added more tests; current counts are in `docs/iasl/IASL_TESTING.md`.) |
| **169 + 19** | On SQLite: 169 pass, 19 are *skipped with a reason* (they need row locks, which SQLite does not have). |
| **50 of 50** | Remove the row lock and all 50 students get seats in a 10-seat course (3 runs out of 3). With the lock: exactly 10. |
| **3 breaks → 3, 12, 7** | We broke the lock, the semaphore and the queue on purpose. 3, 12 and 7 tests failed. Restored: 188 pass again. |
| **40 → 2** | Live demo: 40 simultaneous requests for a 2-seat course gave 2 registrations, and MySQL stored exactly 2. |
| **77** | Dashboard tests; its schedule maths matches the Python generator bit for bit on 8 configurations. |

---

## 1. The story in 60 seconds: the registrar's office

At 9:00 a thousand students click "register" for a course with 2 seats. Two different things can go wrong:

1. **Correctness.** Two clerks both see "1 seat left" and both sell it. The course is now over-sold.
2. **Overload.** So many requests hit the database at once that everything slows down or falls over.

We solve them in two layers. The **database** guarantees correctness. The **OS layer** (our operating-systems part) controls the load. Picture a registrar's office:

| In the office | In ConcurrentReg | Setting / file |
|---|---|---|
| Students arriving | HTTP requests | — |
| A waiting room with 16 chairs | **Bounded queue** | `QUEUE_CAPACITY=16` · `bounded_queue.py` |
| Door staff who turn people away when the chairs are full | **Refuse at once** (HTTP 503), instead of letting a crowd build up | provisional status code |
| 4 clerks | **Worker threads** | `WORKER_COUNT=4` · `worker_pool.py` |
| "Only 2 clerks may be in the records room at once" | **Semaphore with 2 permits** | `DB_SEMAPHORE_PERMITS=2` · `db_semaphore.py` |
| Each course has one drawer; one clerk opens it at a time | **Row lock** in MySQL | `registration_service.py` |
| Printed rules in the ledger ("never stamp a third name on a 2-seat page") | **`CHECK` and `UNIQUE` constraints** | `models.py` |

The three numbers (16, 4, 2) are **experimental parameters, not recommendations.** They are meant to be varied between runs; the dashboard can change them live.

---

## 2. The OS part

### 2.1 The problem: a race condition on the last seat

"Check the seats, then subtract one" is two steps. If two requests interleave, both pass the check:

```
WITHOUT a lock                           WITH the row lock
request A: read seats = 1                request A: LOCK the course row
request B: read seats = 1                request A: read seats = 1, take it, seats = 0, commit
request A: seats = 0  -> SUCCESS         request B: (waits for the lock) ... then reads seats = 0
request B: seats = 0  -> SUCCESS   X     request B: "Course full"
(one seat sold twice)                    (one seat sold once)
```

In textbook words: the check-and-update is a **critical section**, and the row lock gives it **mutual exclusion**. We tested it: without the lock a 1-seat course was sold to both students, and 50 of 50 students got seats in a 10-seat course.

### 2.2 The journey of one request (this is the diagram to draw)

```
Request ─► [1 API] ─► [2 Bounded queue] ─► [3 Worker pool] ─► [4 Semaphore] ─► [5 MySQL transaction] ─► Answer
            waits       16 chairs, FIFO      4 threads          2 permits         lock · check · commit
            for result  full → refuse 503
```

1. **API** (`main.py`). The endpoint hands the request to the layer and waits for the answer. It does no database work itself, so the web server stays responsive.
2. **Bounded queue** (`bounded_queue.py`). A first-in-first-out line with a fixed size. If it is full, the next request is **refused immediately** and never waits. It counts what it accepted and refused.
3. **Worker pool** (`worker_pool.py`). A fixed number of server threads. Each loops: take a request from the queue (sleeping while it is empty), handle it, repeat. A request that crashes a worker is caught; the worker survives.
4. **Semaphore** (`db_semaphore.py`). Only *P* workers may be inside the database section at once. A worker holds a permit **only while it talks to the database**, and always gives it back, even if something fails (a `with` block).
5. **MySQL transaction** (`registration_service.py`). One transaction: lock the course row, check for a duplicate, check for a free seat, insert the registration and subtract one seat, commit once. Any failure rolls everything back.
6. **The answer travels back** through a Future (a "ticket" the web handler waits on): 201 registered, 409 full or duplicate, 404 unknown, 503 queue full.

Every request also writes one log line with its queue wait, semaphore wait and database time, and `GET /os-layer/status` shows live counters.

### 2.3 Textbook concepts and where they live

| OS concept | In ConcurrentReg |
|---|---|
| Race condition / critical section | the seat check-and-update |
| Mutual exclusion (mutex) | MySQL row lock on the course row; a small lock around each counter |
| Producer–consumer with a bounded buffer | web requests produce, workers consume, through the bounded queue |
| Thread pool | the fixed worker pool |
| Counting semaphore | `DbSemaphore`, *P* permits |
| Backpressure / load shedding | refuse immediately when the queue is full |
| Blocking I/O | the database driver is synchronous; workers wait on MySQL so the web server's event loop does not |
| Futures | the hand-back of the result to the waiting request |
| Graceful shutdown | stop accepting, finish what was accepted, let workers exit |
| Fairness / starvation | first-in-first-out into the workers (final fairness policy is an *open decision*) |
| Deadlock | argued avoided by design: each registration takes one row lock on one course row; the 52-request concurrency test asserts zero transaction errors |

### 2.4 Why three limits and not one?

Each protects a *different* thing:

| Limit | Protects | If you removed it |
|---|---|---|
| **Queue capacity** | memory and waiting time | an endless line; users wait forever |
| **Worker count** | how many things the server does at once | unlimited threads |
| **Semaphore permits** | the database from a stampede | all workers pile onto the same row lock |

**The proof test** (`test_innodb_never_sees_more_blocked_transactions_than_the_semaphore_allows`): with 4 workers all busy, MySQL itself (`information_schema.innodb_trx`) reports **no more than 2 transactions waiting**, which is the permit count. The limit is real, and we measured it from inside the database.

### 2.5 When things go wrong

Tests inject real failures and check nothing leaks: a handler that raises (the worker survives), a real MySQL error while holding a real row lock (the lock, the permit and the worker are all released), a request cancelled while queued (skipped), shutdown while workers wait for a permit (everything finishes, nothing leaks), and "the books balance" (every accepted job is accounted for).

### 2.6 What we did **not** build (say this proudly, it is honest)

No retries, no PostgreSQL comparison, no authentication, and no AI/ML or learned policy. Admission control exists only as an **optional, off-by-default, rule-based layer (IASL v1)** that moves a single admission limit; it is described and measured, including where it did not help, in `docs/iasl/`. Request classification, resizing the queue/workers/semaphore, and a server-side request timeout are not built. The HTTP code for "queue full" (503) is **provisional**, and the exact boundary of the semaphore (currently the whole registration call) and the fairness policy are **open decisions**. This is a research prototype, not a production system.

---

## 3. The testing

### 3.1 The big idea

> We do not only test that it works once. We test the **promises** it makes, **under pressure**, and then we **test the tests**.

Three promises, each with its own tests:

| Promise | Meaning | Proven by |
|---|---|---|
| **A. Correct** | never oversell, never register a student twice, all-or-nothing | registration, concurrency, MySQL tests |
| **B. Controlled** | queue never over capacity, workers ≤ N, permits ≤ P, nothing leaks even on errors | OS component, pipeline and OS-on-MySQL tests |
| **C. Honest measurement** | same seed → same schedule; late sending is measured, never hidden; bad runs are flagged | workload generator tests |

### 3.2 The ladder: 188 tests in 11 files

| Level | File | Tests | What it proves, in one sentence |
|---|---|---:|---|
| Rules | `test_registration.py` | 7 | success, duplicate, course full, unknown student/section, and a failure in the middle rolls everything back |
| API contract | `test_api.py` | 5 | the HTTP answers and bodies match the documented table |
| Real races on MySQL | `test_concurrency.py` | 3 | one seat/two students at the same instant; same student twice; 50 for 10 |
| Real MySQL facts | `test_mysql_innodb.py` | 2 | tables are InnoDB; a 1-seat course through the real API with the row lock held |
| OS parts alone | `test_os_components.py` | 21 | queue bound holds under many threads; semaphore never lets in more than *P*; pool never runs more than *N*; permits return on error; clean shutdown |
| OS parts joined | `test_os_request_pipeline.py` | 9 | limits reached and never exceeded; saturation refuses extras at once; every request is logged; nothing leaks |
| OS parts + real MySQL | `test_os_layer_mysql.py` | 10 | never oversells through the whole layer; InnoDB sees ≤ permits waiting; a real MySQL error leaks nothing |
| Load generator | `test_workload_generator.py` | 45 | deterministic requests per seed, schedule shapes, unknown answers are never "success", timeouts recorded not raised |
| Arrival models | `test_workload_arrival_models.py` | 64 | open vs closed loop, phases, lateness, validity flags with reasons |
| Generator vs real server | `test_workload_live.py` | 5 | the generator against the real backend keeps the invariants and writes a readable, reproducible file |
| Demo controls | `test_demo_api.py` | 17 | the demo endpoints, the SQL invariants (which can fail), and the safety guards |
| **Total** | | **188** | |

### 3.3 Five techniques, in plain words

1. **The starting gun.** Threads wait at a barrier and fire in the same instant, so the race really happens.
2. **Hold the door.** A test grabs the course's row lock itself, so a crowd of requests is truly in flight together before it lets go.
3. **Look inside MySQL.** Tests ask InnoDB how many transactions are waiting on a lock, instead of trusting our own counters.
4. **Inject failures.** Make a handler raise, or cause a real database error, then check no permit, worker or lock is left behind.
5. **Repeatable inputs.** Seeded workloads and fixed fixtures, so a failure can be reproduced.

### 3.4 Testing the tests: break it on purpose

A green test only means something if it *can* go red. So we sabotaged the code, one thing at a time, on real MySQL:

| We broke… | Tests run | Failed | What it shows |
|---|---:|---:|---|
| **the row lock** (removed `FOR UPDATE`) | 12 | **3** | a 1-seat course sold twice; 50 of 50 students seated in a 10-seat course |
| **the semaphore** (allowed 10 extra permits) | 40 | **12** | the limits tests and InnoDB-wait test catch it |
| **the queue** (made it unbounded) | 40 | **7** | the capacity and refusal tests catch it |
| Restored all three | 188 | **0** | everything green again |

A useful teaching point: with the lock removed, the **7 ordinary single-threaded registration tests still passed.** Only the concurrency tests catch a race condition. That is why they exist.

### 3.5 Why we test on MySQL

SQLite has no row locks and silently ignores `FOR UPDATE`, so a race "works" there by luck. We therefore run the locking tests only on MySQL/InnoDB. On SQLite the 19 locking tests **skip with a visible reason** instead of pretending to pass. We would rather skip than lie.

### 3.6 Cross-checks between the pieces

- The dashboard re-implements the generator's schedule in TypeScript. A test compares it to numbers produced by the **real Python code**, bit for bit, on 8 configurations. Breaking the ramp formula on purpose made 2 tests fail.
- The terminal commands the dashboard builds were parsed back by the generator's own argument parser: 8 of 8 identical.
- Code excerpts shown on the website are checked against the real repository files.

### 3.7 Live evidence in the demo (not just tests)

- Four correctness rules computed by **SQL on the live database**: capacity never exceeded; seats left = capacity − registered; 0 ≤ seats ≤ capacity; no student twice in a section. They are tested to fail on broken data.
- After every run, a **cross-check**: the client was told *N* registrations succeeded, and MySQL stores *N* rows.
- A button runs **the project's own test suite from the page** and streams each test as it finishes (188 passed in about 30 seconds on MySQL).

### 3.8 What the tests do **not** prove (say it before they ask)

- They do not prove performance at university scale. Workloads are synthetic and the default numbers are demonstration values.
- One run's timing varies with thread scheduling. Our claim is about **invariants** (never oversell), not about speed.
- They do not show that any admission policy is better in general. IASL v1 (optional, rule-based) was compared with the fixed pipeline on one machine and a few synthetic workloads, with mixed results; see `docs/iasl/IASL_EXPERIMENTS.md`. No learned or adaptive-AI policy is built.
- The browser checks of the dashboard (about 60 checks across the landing page, navbar and demo flow) were run as scripts and are **not yet committed** to the repository.

### 3.9 The 90-second testing explanation (say it like this)

> "We test three promises. **Correct:** we never oversell and never double-register. **Controlled:** our queue, workers and semaphore never exceed their limits, even when things fail. **Honest:** our load generator is repeatable and tells you when a run is not valid. We have 188 automated tests, and the important ones fire real concurrent requests at real MySQL. To make sure the tests can fail, we broke the code on purpose: removing the row lock sold a one-seat course twice and seated 50 students in a 10-seat course, and the tests caught it. We put the broken code back and all 188 pass. Tests that need row locks skip on SQLite and say why, instead of pretending. And in the live demo you can run the whole suite yourself with one button."

---

## 4. The 7-minute live demo script

Start everything with `./scripts/start_demo.sh`. Open `http://localhost:5173/dashboard/demo`.

| Time | Do | Say |
|---|---|---|
| 0:00 | Landing page, then click **Launch experiment** | "A research prototype for registration under heavy simultaneous load. Everything you will see comes from the running backend." |
| 0:30 | **Step 1**: point at the MySQL 8.4.11 badge and the three sliders | "Real MySQL with row locks. Queue, workers and permits are the OS layer's three limits, and I can change them live." |
| 1:00 | **Step 2**: point at the seats and the four green checks, then *Show stored rows* | "These checks are SQL on the live database: the correctness rules. The table is empty: no registrations yet." |
| 1:30 | **Step 3**: choose **Finite-seat race**, press **Run scenario** | "Forty students hit a two-seat course at the same instant." |
| 2:15 | **Step 4**: banner, then the dot timeline | "The client was told 2 succeeded, and MySQL stores 2. The red dots are requests the queue refused immediately, then exactly two green registrations, then 'course full'." |
| 3:00 | Show the 2 stored rows | "Here are the two rows in MySQL." |
| 3:30 | **Step 1**: set queue 4, workers 2, permits 1, **Apply**. Choose **Overload**, run | "Same system, tighter limits. Most requests are refused instantly, and the database still agrees with the client." |
| 4:30 | Scroll to the comparison table | "Each run records the server settings it used, so we can compare." |
| 5:00 | **Step 5**: **Run the test suite** | "This is our real pytest suite, streaming. On MySQL nothing is skipped." |
| 6:30 | Optional: terminal "break it on purpose" (below) | "Now we prove the tests can fail." |
| 7:00 | Close with the cheat sheet | "Lock, limit, prove." |

**Optional live break-it** (in a separate terminal; the running server is unaffected):

```bash
cd "<project folder>" && set -a && source .demo.env && set +a
sed -i '' 's/\.with_for_update()//' app/registration_service.py     # remove the row lock
.venv/bin/python -m pytest tests/test_concurrency.py -q               # expect: 2 failed, 1 passed
git checkout -- app/registration_service.py                           # put it back
.venv/bin/python -m pytest tests/test_concurrency.py -q               # expect: 3 passed
```

Expected failure text: `assert ['SUCCESS', 'SUCCESS'] == ['FULL', 'SUCCESS']` (a 1-seat course sold twice) and `assert 50 <= 10` (50 seats given in a 10-seat course).

---

## 5. Questions judges may ask, with short answers

**Why an OS layer at all, if the database already guarantees correctness?**
Correctness and stability are different. The lock stops over-selling, but without limits a flood would create unlimited threads and connections all fighting for the same row. The layer turns overload into predictable waiting and clean refusals.

**Why a *bounded* queue?**
An unbounded queue hides overload: memory grows and users wait forever. A bounded queue gives a quick, honest "no".

**Why not simply more workers?**
More workers mean more contention on the same row lock. The semaphore caps how many are inside the database; we measured that MySQL never saw more waiting transactions than the permits.

**Semaphore versus row lock?**
The row lock protects *one course's data* (who may change it). The semaphore limits *how many workers are in the database section at all*. Different jobs, different scope.

**Can the semaphore leak a permit and freeze the system?**
Permits are returned in a `with`/`finally`. Tests raise errors inside the protected block, including a real MySQL error, and check nothing leaks.

**Can this deadlock?**
Each registration takes one row lock on one course row, so there is no circular waiting among course locks. That is a design argument, not a formal proof. The 52-request concurrency test does assert that no request ends in a transaction error.

**What happens to a refused request?**
It gets HTTP 503 at once and nothing changes in the database. Retrying is not implemented.

**Why threads, and what about Python's GIL?**
The database driver is synchronous, so a worker spends nearly all its time waiting on MySQL, and while it waits other threads run. The goal is controlling contention, not CPU speed-up.

**What if the server dies mid-registration?**
It is one transaction: commit or rollback, never half. A test forces a failure in the middle and checks everything rolls back.

**How do you know the tests are meaningful?**
We broke the lock, semaphore and queue on purpose and counted failing tests (3, 12, 7), then restored and got 188 green.

**Why do some tests skip on SQLite?**
SQLite ignores row locks, so those tests would be meaningless. They skip with a reason rather than pass falsely.

**Open loop versus closed loop?**
Open loop sends requests on a fixed schedule, like a real crowd, whatever the server does. Closed loop has *N* users who wait for each answer before asking again. We record both and flag open-loop runs that could not keep their schedule.

**Is it reproducible?**
The same seed gives the same schedule and targets. Thread timing is not reproducible, so we claim invariants, not speed.

**Does it scale to a real university?**
We do not claim that. Workloads are synthetic and parameters are demonstration values; calibrated large-scale experiments are future work.

**What is not built yet?**
Retries, AI/ML policies, and a PostgreSQL comparison. An optional rule-based admission layer (IASL v1, off by default) exists; its limits and evaluation are in `docs/iasl/`.

---

## 6. Glossary (one line each)

- **Race condition**: the result depends on which thread happens to run first.
- **Critical section**: code that must not run in two places at once.
- **Mutual exclusion / lock**: only one holder at a time.
- **Semaphore**: a counter of permits; at most *P* holders at a time.
- **Thread / thread pool**: a unit of execution / a fixed team of them.
- **Producer–consumer / bounded buffer**: one side adds work, another takes it, through a fixed-size line.
- **Backpressure / load shedding**: slowing or refusing work when full, instead of collapsing.
- **Transaction**: a group of database steps that all happen or none do.
- **Row lock (InnoDB)**: a lock on one row of a table.
- **Constraint**: a rule the database itself enforces (`UNIQUE`, `CHECK`).
- **Invariant**: something that must always be true (seats never negative).
- **Open / closed loop**: arrivals on a schedule / arrivals driven by waiting users.
- **p95 latency**: 95% of requests were faster than this.
- **Mutation test**: break the code on purpose to see whether a test fails.
