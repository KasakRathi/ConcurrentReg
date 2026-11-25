"""AdmissionController: the request-path check, hard bounds, watchdog, fallback, thread safety."""
import threading

import pytest

from app.iasl.admission import AdmissionController


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def make(capacity=40, initial=40, fallback=40, watchdog=5.0, clock=None):
    return AdmissionController(capacity, initial, fallback, watchdog, clock=clock or Clock())


def test_requests_are_admitted_below_the_limit_and_refused_at_or_above_it():
    a = make(initial=10)
    assert [a.check(depth) for depth in (0, 9, 10, 11, 39, 40)] == [True, True, False, False, False, False]


def test_at_a_limit_equal_to_the_capacity_every_request_is_admitted_so_the_queues_own_bound_applies():
    a = make(capacity=40, initial=40)
    assert all(a.check(depth) for depth in (0, 39, 40, 500))      # a full queue is the QUEUE's business, not admission's


def test_changing_the_limit_takes_effect_at_once():
    a = make(initial=40)
    assert a.check(20)
    a.set_limit(10)
    assert not a.check(20)
    a.set_limit(25)
    assert a.check(20)


@pytest.mark.parametrize("bad", [0, -1, 41, 10**6, None, True, 7.5, "10", [3]])
def test_the_hard_bound_refuses_any_limit_outside_1_to_capacity_and_keeps_the_old_value(bad):
    a = make(initial=17)
    with pytest.raises(ValueError):
        a.set_limit(bad)
    assert a.effective_limit() == 17


def test_the_bounds_are_inclusive():
    a = make(capacity=40)
    a.set_limit(1)
    assert a.effective_limit() == 1
    a.set_limit(40)
    assert a.effective_limit() == 40


@pytest.mark.parametrize("args", [
    dict(capacity=0, initial=1, fallback=1), dict(capacity=10, initial=11, fallback=10),
    dict(capacity=10, initial=0, fallback=10), dict(capacity=10, initial=5, fallback=11),
    dict(capacity=10, initial=5, fallback=0), dict(capacity=True, initial=1, fallback=1),
])
def test_it_cannot_be_constructed_with_an_impossible_limit(args):
    with pytest.raises(ValueError):
        AdmissionController(args["capacity"], args["initial"], args["fallback"], 5.0)


def test_the_watchdog_must_be_positive():
    for bad in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            AdmissionController(10, 10, 10, bad)


def test_without_heartbeats_the_fallback_limit_takes_over_by_itself():
    clock = Clock()
    a = make(initial=30, fallback=12, watchdog=5.0, clock=clock)
    assert a.effective_limit() == 30 and not a.watchdog_tripped
    clock.now += 5.0
    assert a.effective_limit() == 30                               # exactly at the limit is still alive
    clock.now += 0.1
    assert a.effective_limit() == 12 and a.watchdog_tripped
    assert not a.check(12) and a.check(11)                         # the request path really uses it


def test_a_heartbeat_keeps_the_configured_limit_in_force():
    clock = Clock()
    a = make(initial=30, fallback=12, watchdog=5.0, clock=clock)
    for _ in range(20):
        clock.now += 4.0
        a.heartbeat()
    assert a.effective_limit() == 30


def test_the_watchdog_recovers_when_heartbeats_resume():
    clock = Clock()
    a = make(initial=30, fallback=12, watchdog=5.0, clock=clock)
    clock.now += 60.0
    assert a.effective_limit() == 12
    a.heartbeat()
    assert a.effective_limit() == 30 and not a.watchdog_tripped


def test_explicit_fallback_pins_the_fallback_limit_and_leaving_it_restores_the_configured_one():
    clock = Clock()
    a = make(initial=30, fallback=12, clock=clock)
    a.enter_fallback()
    a.heartbeat()
    assert a.in_fallback and a.effective_limit() == 12
    a.set_limit(25)                                                # still allowed, but not in force during fallback
    assert a.effective_limit() == 12
    a.exit_fallback()
    assert not a.in_fallback and a.effective_limit() == 25


def test_leaving_fallback_counts_as_a_sign_of_life():
    clock = Clock()
    a = make(initial=30, fallback=12, watchdog=5.0, clock=clock)
    a.enter_fallback()
    clock.now += 100.0
    a.exit_fallback()
    assert a.effective_limit() == 30


def test_stats_describe_everything_an_operator_needs():
    clock = Clock()
    a = make(capacity=40, initial=30, fallback=12, clock=clock)
    clock.now += 2.0
    assert a.stats() == {"limit": 30, "configured_limit": 30, "capacity": 40, "fallback": False, "fallback_limit": 12,
                         "watchdog_tripped": False, "seconds_since_heartbeat": 2.0}


def test_concurrent_checks_while_the_limit_changes_never_fail_and_always_give_a_valid_answer():
    a = make(capacity=100, initial=50, fallback=100, watchdog=1000.0)
    errors, answers = [], []

    def check():
        try:
            for depth in range(100):
                answers.append(a.check(depth))
        except Exception as error:
            errors.append(error)

    def move():
        try:
            for value in list(range(1, 101)) * 20:
                a.set_limit(value)
                a.heartbeat()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=check) for _ in range(6)] + [threading.Thread(target=move)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and all(isinstance(x, bool) for x in answers)
    assert 1 <= a.effective_limit() <= 100
