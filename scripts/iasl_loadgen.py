"""An asyncio load driver for the IASL experiments. EXPERIMENT ONLY.

Why it exists: the project's workload generator dispatches from one thread into a pool of up to 1,000 threads. Pilot runs
showed that with a few hundred requests in flight the interpreter lock starves the dispatcher for seconds, so the offered load
stops matching the schedule (the run is then invalid) even though the server is idle. This driver keeps the SAME request schedule
(it consumes the generator's own `generate_requests` output, including the intended arrival times) and the SAME response
classification (`workload_generator.classify_response`), but runs everything on one event loop, so thousands of requests can be in
flight without thread contention.

It is validated against the project's generator on identical requests (tests/test_iasl_experiment_loadgen.py).
Open loop: a request is sent at its intended time whatever the server is doing; lateness is measured, never hidden.
"""
import asyncio
import multiprocessing
import time

import httpx

from workload import workload_generator as wg

MAX_CONNECTIONS = 6000
DEFAULT_PROCESSES = 6      # httpx's connection pool does work proportional to the connections open, so ONE process stalls
                           # once a few hundred requests are in flight (measured); several small pools do not


def lateness_stats(records):
    values = sorted((r["sent_offset_s"] - r["intended_offset_s"]) * 1000 for r in records
                    if r.get("sent_offset_s") is not None and r.get("intended_offset_s") is not None)
    if not values:
        return None
    return {"samples": len(values), "mean": sum(values) / len(values), "median": values[len(values) // 2],
            "p95": wg.percentile(values, 95), "p99": wg.percentile(values, 99), "max": values[-1]}


def validity(records, tolerance_ms):
    """The generator's open-loop rule: every request dispatched, none sent more than the tolerance after its intended time."""
    reasons = []
    sent = [r for r in records if r.get("sent_offset_s") is not None]
    if len(sent) != len(records):
        reasons.append(f"{len(records) - len(sent)} of {len(records)} intended requests were never dispatched")
    over = sum(1 for r in sent if (r["sent_offset_s"] - r["intended_offset_s"]) * 1000 > tolerance_ms)
    if over:
        reasons.append(f"{over} requests were sent more than {tolerance_ms} ms after their intended arrival")
    return {"valid": not reasons, "reasons": reasons, "lateness_ms": lateness_stats(records)}


async def _send(client, endpoint, request, t0):
    sent = time.perf_counter()
    status, category, detail = None, None, None
    try:
        response = await client.post(endpoint, json={"student_id": request.student_id, "section_id": request.section_id})
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        category = wg.classify_response(status, body)
    except httpx.TimeoutException as error:
        category, detail = wg.TIMEOUT, type(error).__name__
    except httpx.TransportError as error:
        category, detail = wg.CONNECTION_ERROR, type(error).__name__
    except Exception as error:   # never lose a record
        category, detail = wg.UNKNOWN, f"{type(error).__name__}: {error}"
    end = time.perf_counter()
    return {"sequence": request.sequence, "section_id": request.section_id, "student_id": request.student_id,
            "category": category, "http_status": status, "detail": detail,
            "intended_offset_s": request.planned_offset_s, "sent_offset_s": sent - t0, "end_offset_s": end - t0}


async def _warm(client, count):
    """Open `count` keep-alive connections BEFORE the clock starts, so a burst needs no new connections.

    Connecting hundreds of sockets at the same instant overflows the kernel's accept queue (128 on this macOS) and the surplus
    are refused, which would be measuring the operating system, not the system under test. Batches with small gaps avoid that
    while warming; during the run requests reuse these connections.
    """
    remaining = count
    while remaining > 0:
        batch = min(remaining, 40)
        await asyncio.gather(*[client.get("/os-layer/status") for _ in range(batch)], return_exceptions=True)
        remaining -= batch
        await asyncio.sleep(0.03)


async def _poll(base_url, t0, interval, polls, stop):
    async with httpx.AsyncClient(base_url=base_url, timeout=2) as client:
        while not stop.is_set():
            try:
                body = (await client.get("/os-layer/status")).json()
                admission = body.get("admission") or {}
                polls.append({
                    "t": round(time.perf_counter() - t0, 3), "depth": body["queue"]["depth"], "alive": body["workers"]["alive"],
                    "active": body["workers"]["active"], "permits": body["db_semaphore"]["permits"],
                    "in_cs": body["db_semaphore"]["in_critical_section"], "waiting": body["db_semaphore"]["waiting"],
                    "adm_limit": admission.get("limit"), "adm_rejected": admission.get("rejected"),
                    "qfull": body["queue"]["rejected_queue_full"]})
            except Exception:
                pass   # a missed poll is a gap in the series, never a failed run
            try:
                await asyncio.wait_for(stop.wait(), interval)
            except asyncio.TimeoutError:
                pass


def run_open_loop(requests, base_url, timeout_s=5.0, endpoint="/registrations", poll_interval=0.25, processes=1, warm_connections=0):
    """Send every request at its intended time (open loop). Returns (one record per request in request order, polls, elapsed_s).

    processes > 1 splits the requests round-robin over that many client processes, all aligned to one shared start time, so
    the schedule is still the generator's and offsets from the common origin are comparable across processes.
    """
    if processes <= 1:
        return asyncio.run(_run_open(requests, base_url, timeout_s, endpoint, poll_interval, None, warm_connections))
    chunks = [requests[k::processes] for k in range(processes)]
    context = multiprocessing.get_context("spawn")
    with context.Pool(processes) as pool:
        start_epoch = time.time() + 3.0                      # workers import and connect first, then all start together
        jobs = [(chunk, base_url, timeout_s, endpoint, poll_interval if k == 0 else None, start_epoch,
                 warm_connections // processes) for k, chunk in enumerate(chunks)]
        outputs = pool.map(_open_worker, jobs)
    merged = [None] * len(requests)
    for k, (records, _, _) in enumerate(outputs):
        merged[k::processes] = records
    return merged, outputs[0][1], max(o[2] for o in outputs)


def _open_worker(job):
    chunk, base_url, timeout_s, endpoint, poll_interval, start_epoch, warm = job
    return asyncio.run(_run_open(chunk, base_url, timeout_s, endpoint, poll_interval, start_epoch, warm))


async def _run_open(requests, base_url, timeout_s, endpoint, poll_interval, start_epoch, warm_connections=0):
    limits = httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_CONNECTIONS, keepalive_expiry=120)
    results, polls, tasks = {}, [], []
    stop = asyncio.Event()

    async def tracked(client, request, t0):
        results[request.sequence] = await _send(client, endpoint, request, t0)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout_s, limits=limits) as client:
        if warm_connections:
            await _warm(client, warm_connections)
        if start_epoch is None:
            t0 = time.perf_counter()
        else:                                                # a shared origin: every process computes the same instant
            t0 = time.perf_counter() + (start_epoch - time.time())
            await asyncio.sleep(max(0.0, t0 - time.perf_counter()))
        poller = asyncio.create_task(_poll(base_url, t0, poll_interval, polls, stop)) if poll_interval else None
        for request in requests:
            delay = t0 + request.planned_offset_s - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(tracked(client, request, t0)))
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0
        stop.set()
        if poller:
            await poller
    return [results[r.sequence] for r in requests], polls, elapsed


async def _run_closed(requests, base_url, users, timeout_s, endpoint):
    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    queue = list(requests)
    results = {}
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout_s, limits=limits) as client:
        t0 = time.perf_counter()

        async def user():
            while queue:
                request = queue.pop(0)
                results[request.sequence] = await _send(client, endpoint, request, t0)
        await asyncio.gather(*[user() for _ in range(users)])
        elapsed = time.perf_counter() - t0
    return [results[r.sequence] for r in requests], elapsed


def run_closed_loop(requests, base_url, users, timeout_s=30.0, endpoint="/registrations", processes=1):
    """`users` virtual users, each sending its next request as soon as the previous one is answered (no think time)."""
    if processes <= 1:
        return asyncio.run(_run_closed(requests, base_url, users, timeout_s, endpoint))
    per = max(1, users // processes)
    chunks = [requests[k::processes] for k in range(processes)]
    context = multiprocessing.get_context("spawn")
    with context.Pool(processes) as pool:
        outputs = pool.map(_closed_worker, [(chunk, base_url, per, timeout_s, endpoint) for chunk in chunks])
    merged = [None] * len(requests)
    for k, (records, _) in enumerate(outputs):
        merged[k::processes] = records
    return merged, max(o[1] for o in outputs)


def _closed_worker(job):
    chunk, base_url, users, timeout_s, endpoint = job
    return asyncio.run(_run_closed(chunk, base_url, users, timeout_s, endpoint))
