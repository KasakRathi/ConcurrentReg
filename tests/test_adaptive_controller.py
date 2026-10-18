from app.adaptive_controller import AdaptiveController, AdaptiveMetrics


def test_low_contention_increases_concurrency_after_persistence():
    controller = AdaptiveController(
        initial_concurrency=4,
        persistence=2,
    )

    metrics = AdaptiveMetrics(
        queue_length=0,
        active_requests=1,
        max_concurrency=16,
        contention_rate=0.05,
        retry_rate=0.02,
    )

    assert controller.decide(metrics) == "maintain"
    assert controller.decide(metrics) == "increase"
    assert controller.current_concurrency == 5


def test_high_contention_decreases_concurrency_after_persistence():
    controller = AdaptiveController(
        initial_concurrency=4,
        persistence=2,
    )

    metrics = AdaptiveMetrics(
        queue_length=16,
        active_requests=16,
        max_concurrency=16,
        contention_rate=0.95,
        retry_rate=0.90,
    )

    assert controller.decide(metrics) == "maintain"
    assert controller.decide(metrics) == "decrease"
    assert controller.current_concurrency == 3


def test_medium_contention_maintains_concurrency():
    controller = AdaptiveController(
        initial_concurrency=4,
        persistence=2,
    )

    metrics = AdaptiveMetrics(
        queue_length=4,
        active_requests=4,
        max_concurrency=16,
        contention_rate=0.50,
        retry_rate=0.40,
    )

    assert controller.decide(metrics) == "maintain"
    assert controller.current_concurrency == 4


def test_persistence_prevents_immediate_switching():
    controller = AdaptiveController(
        initial_concurrency=4,
        persistence=3,
    )

    metrics = AdaptiveMetrics(
        queue_length=16,
        active_requests=16,
        max_concurrency=16,
        contention_rate=0.95,
        retry_rate=0.90,
    )

    assert controller.decide(metrics) == "maintain"
    assert controller.current_concurrency == 4

    assert controller.decide(metrics) == "maintain"
    assert controller.current_concurrency == 4

    assert controller.decide(metrics) == "decrease"
    assert controller.current_concurrency == 3


def test_concurrency_does_not_exceed_maximum():
    controller = AdaptiveController(
        initial_concurrency=16,
        max_concurrency=16,
        persistence=1,
    )

    metrics = AdaptiveMetrics(
        queue_length=0,
        active_requests=0,
        max_concurrency=16,
        contention_rate=0.0,
        retry_rate=0.0,
    )

    assert controller.decide(metrics) == "maintain"
    assert controller.current_concurrency == 16


def test_concurrency_does_not_go_below_minimum():
    controller = AdaptiveController(
        initial_concurrency=1,
        min_concurrency=1,
        persistence=1,
    )

    metrics = AdaptiveMetrics(
        queue_length=16,
        active_requests=16,
        max_concurrency=16,
        contention_rate=1.0,
        retry_rate=1.0,
    )

    assert controller.decide(metrics) == "maintain"
    assert controller.current_concurrency == 1