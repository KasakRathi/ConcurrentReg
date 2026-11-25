import pytest
from app.os_layer.request_queue import BoundedRequestQueue
from app.os_layer.semaphore_manager import SemaphoreManager
from app.os_layer.worker_pool import WorkerPool
from app.iasl.metrics import MetricsCollector
from app.iasl.controller_history import ControllerHistory
from app.iasl.adaptive_controller import IASLController

@pytest.fixture
def iasl_setup():
    queue = BoundedRequestQueue(capacity=100)
    sem_mgr = SemaphoreManager(initial_permits=2, min_permits=1, max_permits=4)
    worker_pool = WorkerPool(queue=queue, worker_count=4, semaphore_mgr=sem_mgr)
    metrics_collector = MetricsCollector(queue, worker_pool, sem_mgr)
    history = ControllerHistory()
    
    controller = IASLController(
        metrics_collector=metrics_collector,
        semaphore_mgr=sem_mgr,
        history=history,
        min_concurrency=1,
        max_concurrency=4,
        default_concurrency=2,
        persistence=2
    )
    return controller, sem_mgr

def test_medium_pressure_maintains_concurrency(iasl_setup):
    controller, sem_mgr = iasl_setup
    metrics = {
        "pressure_score": 0.50,
        "classification": "MEDIUM",
        "queue_length": 10,
        "contention_rate": 0.1,
        "retry_rate": 0.05
    }
    res = controller.evaluate_system(metrics)
    assert res["decision"] == "MAINTAIN"
    assert res["new_concurrency"] == 2
    assert sem_mgr.semaphore.max_permits == 2

def test_low_pressure_requires_persistence_to_increase(iasl_setup):
    controller, sem_mgr = iasl_setup
    metrics_low = {
        "pressure_score": 0.10,
        "classification": "LOW",
        "queue_length": 0,
        "contention_rate": 0.0,
        "retry_rate": 0.0
    }
    # Cycle 1: observation 1 of 2 -> should MAINTAIN
    res1 = controller.evaluate_system(metrics_low)
    assert res1["decision"] == "MAINTAIN"
    assert res1["new_concurrency"] == 2

    # Cycle 2: observation 2 of 2 -> reaches persistence threshold -> INCREASE
    res2 = controller.evaluate_system(metrics_low)
    assert res2["decision"] == "INCREASE"
    assert res2["new_concurrency"] == 3
    assert sem_mgr.semaphore.max_permits == 3

def test_high_pressure_requires_persistence_to_decrease(iasl_setup):
    controller, sem_mgr = iasl_setup
    metrics_high = {
        "pressure_score": 0.85,
        "classification": "HIGH",
        "queue_length": 80,
        "contention_rate": 0.5,
        "retry_rate": 0.3
    }
    # Cycle 1: observation 1 of 2 -> MAINTAIN
    res1 = controller.evaluate_system(metrics_high)
    assert res1["decision"] == "MAINTAIN"
    assert res1["new_concurrency"] == 2

    # Cycle 2: observation 2 of 2 -> DECREASE
    res2 = controller.evaluate_system(metrics_high)
    assert res2["decision"] == "DECREASE"
    assert res2["new_concurrency"] == 1
    assert sem_mgr.semaphore.max_permits == 1

def test_minimum_concurrency_respected(iasl_setup):
    controller, sem_mgr = iasl_setup
    metrics_high = {
        "pressure_score": 0.95,
        "classification": "HIGH",
        "queue_length": 95,
        "contention_rate": 0.8,
        "retry_rate": 0.6
    }
    # Reduce to minimum (1)
    controller.evaluate_system(metrics_high)
    controller.evaluate_system(metrics_high)
    assert controller.current_concurrency == 1

    # High pressure again -> should not go below min_concurrency (1)
    controller.evaluate_system(metrics_high)
    res = controller.evaluate_system(metrics_high)
    assert res["decision"] == "MAINTAIN"
    assert res["new_concurrency"] == 1
    assert sem_mgr.semaphore.max_permits == 1

def test_maximum_concurrency_respected(iasl_setup):
    controller, sem_mgr = iasl_setup
    metrics_low = {
        "pressure_score": 0.05,
        "classification": "LOW",
        "queue_length": 0,
        "contention_rate": 0.0,
        "retry_rate": 0.0
    }
    # Step from 2 -> 3
    controller.evaluate_system(metrics_low)
    controller.evaluate_system(metrics_low)
    assert controller.current_concurrency == 3

    # Step from 3 -> 4 (max)
    controller.evaluate_system(metrics_low)
    controller.evaluate_system(metrics_low)
    assert controller.current_concurrency == 4

    # Try stepping beyond max (4)
    controller.evaluate_system(metrics_low)
    res = controller.evaluate_system(metrics_low)
    assert res["decision"] == "MAINTAIN"
    assert res["new_concurrency"] == 4
    assert sem_mgr.semaphore.max_permits == 4

def test_persistence_resets_on_alternating_pressure(iasl_setup):
    controller, sem_mgr = iasl_setup
    metrics_high = {"pressure_score": 0.85, "classification": "HIGH", "queue_length": 80, "contention_rate": 0.4, "retry_rate": 0.2}
    metrics_low = {"pressure_score": 0.10, "classification": "LOW", "queue_length": 0, "contention_rate": 0.0, "retry_rate": 0.0}

    # 1 High observation
    controller.evaluate_system(metrics_high)
    assert controller.consecutive_high_count == 1

    # Followed by 1 Low observation -> High count should reset to 0
    controller.evaluate_system(metrics_low)
    assert controller.consecutive_high_count == 0
    assert controller.consecutive_low_count == 1
    assert controller.current_concurrency == 2
