"""Unit tests for the three Day 3 building blocks on their own: queue, semaphore, worker pool.

No registration or HTTP is involved. The numbers (capacities, worker counts, sleeps) are
test-fixture values chosen to make the behaviour visible, not research parameters.
"""
import queue
import sys
import threading
import time

import pytest

from app.os_layer.bounded_queue import ADDED, FULL, SHUT_DOWN, BoundedRequestQueue
from app.os_layer.db_semaphore import DbSemaphore
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.worker_pool import WorkerPool
from tests.conftest import wait_until


def run_threads(target, how_many):
    threads = [threading.Thread(target=target) for _ in range(how_many)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)


# ------------------------------------------------------------------ bounded queue

def test_queue_refuses_items_beyond_its_capacity():
    work_queue = BoundedRequestQueue(capacity=3)

    outcomes = [work_queue.try_put(number) for number in range(5)]

    assert outcomes == [ADDED, ADDED, ADDED, FULL, FULL]
    assert work_queue.qsize() == 3
    assert work_queue.max_depth == 3
    assert work_queue.accepted == 3
    assert work_queue.rejected_full == 2


def test_queue_bound_holds_when_many_producers_push_at_once():
    work_queue = BoundedRequestQueue(capacity=5)
    producers, attempts_each = 8, 50
    start_together = threading.Barrier(producers)

    def produce():
        start_together.wait()
        for number in range(attempts_each):
            work_queue.try_put(number)

    run_threads(produce, producers)

    assert work_queue.qsize() == 5                 # nobody is consuming, so exactly the capacity got in
    assert work_queue.accepted == 5
    assert work_queue.rejected_full == producers * attempts_each - 5
    assert work_queue.max_depth == 5


def test_queue_depth_never_passes_capacity_while_producers_and_consumers_race():
    capacity, producers, items_each = 4, 4, 300
    work_queue = BoundedRequestQueue(capacity)
    taken = []
    taken_lock = threading.Lock()

    def produce():
        for number in range(items_each):
            while work_queue.try_put(number) == FULL:
                time.sleep(0)               # full: wait for a consumer to make room

    def consume():
        while True:
            try:
                work_queue.get()
            except queue.ShutDown:
                return
            with taken_lock:
                taken.append(1)

    consumers = [threading.Thread(target=consume) for _ in range(2)]
    for consumer in consumers:
        consumer.start()
    run_threads(produce, producers)
    work_queue.shutdown()                    # consumers finish what is left, then stop
    for consumer in consumers:
        consumer.join(timeout=30)

    assert len(taken) == producers * items_each
    assert work_queue.accepted == producers * items_each
    assert work_queue.max_depth <= capacity


def test_queue_is_first_in_first_out_and_frees_space_after_a_get():
    work_queue = BoundedRequestQueue(capacity=2)
    work_queue.try_put("first")
    work_queue.try_put("second")
    assert work_queue.try_put("third") == FULL

    assert work_queue.get() == "first"
    assert work_queue.try_put("third") == ADDED
    assert [work_queue.get(), work_queue.get()] == ["second", "third"]


def test_shutdown_keeps_accepted_items_but_refuses_new_ones():
    work_queue = BoundedRequestQueue(capacity=3)
    work_queue.try_put("accepted")

    work_queue.shutdown()

    assert work_queue.try_put("too late") == SHUT_DOWN
    assert work_queue.rejected_shut_down == 1
    assert work_queue.get() == "accepted"
    with pytest.raises(queue.ShutDown):
        work_queue.get()


# --------------------------------------------------------------------- semaphore

def test_semaphore_lets_in_at_most_its_permits_and_reaches_that_number():
    semaphore = DbSemaphore(permits=2)
    inside = 0
    most_inside = 0
    counter_lock = threading.Lock()

    def work():
        nonlocal inside, most_inside
        with semaphore.hold():
            with counter_lock:                 # the test counts for itself, independently of DbSemaphore
                inside += 1
                most_inside = max(most_inside, inside)
            time.sleep(0.05)
            with counter_lock:
                inside -= 1

    run_threads(work, 10)

    assert most_inside == 2
    assert semaphore.max_in_critical_section == 2
    assert semaphore.in_critical_section == 0
    assert semaphore.waiting == 0
    assert semaphore.acquisitions == 10


def test_semaphore_reports_how_long_a_caller_waited():
    semaphore = DbSemaphore(permits=1)
    holder_has_permit = threading.Event()

    def hold_for_a_while():
        with semaphore.hold():
            holder_has_permit.set()
            time.sleep(0.2)

    holder = threading.Thread(target=hold_for_a_while)
    holder.start()
    assert holder_has_permit.wait(timeout=5)

    with semaphore.hold() as waited:
        pass
    holder.join()

    assert waited >= 0.1
    assert semaphore.wait_max_s >= 0.1
    assert semaphore.max_waiting == 1


def test_permit_is_returned_when_the_protected_block_raises():
    semaphore = DbSemaphore(permits=1)

    def fail_inside_the_block_five_times():
        for _ in range(5):
            with pytest.raises(RuntimeError):
                with semaphore.hold():
                    raise RuntimeError("simulated database failure")

    # Run it in a thread with a deadline: if a permit leaked, the 2nd round would wait
    # forever, and we want the test to FAIL rather than hang.
    thread = threading.Thread(target=fail_inside_the_block_five_times, daemon=True)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive(), "a permit leaked: a later caller is stuck waiting for it"
    assert semaphore.in_critical_section == 0
    assert semaphore.acquisitions == 5


# ------------------------------------------------------------------- worker pool

def make_counting_handler(seconds):
    """A job handler that sleeps and records how many jobs it was running at the same time."""
    state = {"inside": 0, "most_inside": 0, "done": 0}
    lock = threading.Lock()

    def handler(job):
        with lock:
            state["inside"] += 1
            state["most_inside"] = max(state["most_inside"], state["inside"])
        time.sleep(seconds)
        with lock:
            state["inside"] -= 1
            state["done"] += 1

    return handler, state


@pytest.fixture
def pool_factory():
    pools = []

    def make(worker_count, handler, capacity=50):
        work_queue = BoundedRequestQueue(capacity)
        pool = WorkerPool(work_queue, worker_count, handler)
        pool.start()
        pools.append(pool)
        return pool, work_queue

    yield make
    for pool in pools:
        pool.stop(timeout_seconds=3)


def test_pool_runs_at_most_its_worker_count_and_reaches_that_number(pool_factory):
    handler, state = make_counting_handler(seconds=0.05)
    pool, work_queue = pool_factory(3, handler)

    for number in range(12):
        work_queue.try_put(number)
    assert wait_until(lambda: state["done"] == 12)

    assert state["most_inside"] == 3            # seen from inside the handler
    assert pool.max_active == 3                 # seen by the pool's own counter
    assert pool.active == 0
    assert pool.jobs_finished == 12


def test_worker_survives_a_handler_that_raises(pool_factory):
    handled = []

    def sometimes_fails(job):
        if job % 2 == 1:
            raise ValueError("simulated failure")
        handled.append(job)

    pool, work_queue = pool_factory(2, sometimes_fails)
    for number in range(10):
        work_queue.try_put(number)
    assert wait_until(lambda: pool.jobs_finished == 10)

    assert pool.unexpected_errors == 5
    assert pool.alive_workers() == 2            # no worker died
    assert pool.active == 0
    work_queue.try_put(100)                      # and the pool still works afterwards
    assert wait_until(lambda: 100 in handled)


def test_stop_lets_accepted_jobs_finish_then_workers_exit(pool_factory):
    handler, state = make_counting_handler(seconds=0.05)
    pool, work_queue = pool_factory(2, handler)
    for number in range(6):
        work_queue.try_put(number)

    still_running = pool.stop(timeout_seconds=10)

    assert still_running == []
    assert state["done"] == 6                    # nothing accepted was dropped
    assert pool.alive_workers() == 0
    assert work_queue.try_put(99) == SHUT_DOWN


def test_idle_workers_blocked_on_an_empty_queue_exit_promptly_when_the_pool_stops(pool_factory):
    handler, _state = make_counting_handler(seconds=0)
    pool, _queue = pool_factory(3, handler)
    assert wait_until(lambda: pool.alive_workers() == 3)       # all three are waiting inside get()

    started = time.perf_counter()
    still_running = pool.stop(timeout_seconds=5)

    assert still_running == []
    assert pool.alive_workers() == 0
    assert time.perf_counter() - started < 2                    # woken by the shutdown, not by a timeout


def test_queue_books_balance_after_jobs_finish_or_fail(pool_factory):
    # queue.Queue counts every job taken from it until the worker marks it done (task_done).
    # If that is forgotten, unfinished_tasks only ever grows and queue.join() could never return.
    def sometimes_fails(job):
        if job % 2 == 1:
            raise ValueError("simulated failure")

    pool, work_queue = pool_factory(2, sometimes_fails)
    for number in range(10):
        work_queue.try_put(number)
    assert wait_until(lambda: pool.jobs_finished == 10)

    assert wait_until(lambda: work_queue.unfinished_tasks == 0)  # successes and failures alike are marked done
    joiner = threading.Thread(target=work_queue.join, daemon=True)
    joiner.start()
    joiner.join(timeout=5)
    assert not joiner.is_alive()                                # join() returns, so nothing is left unaccounted for


def test_runtime_provides_queue_shutdown():
    # The graceful stop relies on queue.Queue.shutdown(), which exists since Python 3.13.
    print(f"\nPython {sys.version.split()[0]}")
    assert sys.version_info >= (3, 13), f"Day 3 needs Python 3.13 or newer; this is {sys.version}"
    assert hasattr(queue, "ShutDown") and hasattr(queue.Queue, "shutdown")


def test_pool_cannot_be_started_twice(pool_factory):
    handler, _state = make_counting_handler(seconds=0)
    pool, _queue = pool_factory(1, handler)
    with pytest.raises(RuntimeError):
        pool.start()


# ----------------------------------------------------------------------- settings

@pytest.mark.parametrize("changes", [
    {"queue_capacity": 0}, {"worker_count": 0}, {"db_semaphore_permits": -1}, {"worker_count": 2.5},
])
def test_config_rejects_values_that_are_not_whole_numbers_of_at_least_one(changes):
    with pytest.raises(ValueError):
        OSLayerConfig(**changes)


def test_config_is_read_from_the_environment_with_defaults_for_missing_values(monkeypatch):
    for name in ("QUEUE_CAPACITY", "WORKER_COUNT", "DB_SEMAPHORE_PERMITS"):
        monkeypatch.delenv(name, raising=False)
    assert OSLayerConfig.from_environment() == OSLayerConfig()      # the development defaults

    monkeypatch.setenv("QUEUE_CAPACITY", "7")
    monkeypatch.setenv("WORKER_COUNT", "3")
    monkeypatch.setenv("DB_SEMAPHORE_PERMITS", "5")
    assert OSLayerConfig.from_environment() == OSLayerConfig(queue_capacity=7, worker_count=3, db_semaphore_permits=5)


def test_a_bad_environment_value_names_the_variable(monkeypatch):
    monkeypatch.setenv("WORKER_COUNT", "many")
    with pytest.raises(ValueError, match="WORKER_COUNT"):
        OSLayerConfig.from_environment()
