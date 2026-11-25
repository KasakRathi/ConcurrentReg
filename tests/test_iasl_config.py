"""IASL configuration: defaults, parsing, validation, capacity-dependent bounds."""
import dataclasses

import pytest

from app.iasl.config import IASLConfig
from app.os_layer.layer_config import OSLayerConfig


def test_defaults_are_valid_and_iasl_is_off_by_default():
    config = IASLConfig()
    assert config.enabled is False
    assert IASLConfig.from_environment({}).as_dict() == config.as_dict()


def test_existing_os_layer_config_was_not_extended():
    # tests/test_demo_api.py compares OSLayerConfig's dict exactly: IASL settings must live elsewhere.
    assert [f.name for f in dataclasses.fields(OSLayerConfig)] == ["queue_capacity", "worker_count", "db_semaphore_permits"]


def test_values_are_read_from_the_environment():
    config = IASLConfig.from_environment({
        "IASL_ENABLED": "TRUE", "IASL_SAMPLING_INTERVAL_S": "1.5", "IASL_STALE_METRIC_SECONDS": "4",
        "IASL_WATCHDOG_SECONDS": "6", "IASL_COOLDOWN_SECONDS": "2", "IASL_ADMISSION_MIN": "3",
        "IASL_FALLBACK_MODE": "Conservative", "IASL_SMOOTHING_SAMPLES": "5", "IASL_ADMISSION_MAX": " 50 ",
    })
    assert config.enabled is True
    assert config.sampling_interval_s == 1.5
    assert config.admission_min == 3 and config.admission_max == 50
    assert config.fallback_mode == "conservative"
    assert config.smoothing_samples == 5


def test_empty_values_mean_default():
    assert IASLConfig.from_environment({"IASL_ENABLED": "  ", "IASL_ADMISSION_MIN": ""}).enabled is False


@pytest.mark.parametrize("variable, value", [
    ("IASL_ENABLED", "maybe"),
    ("IASL_SAMPLING_INTERVAL_S", "0"),
    ("IASL_SAMPLING_INTERVAL_S", "abc"),
    ("IASL_SAMPLING_INTERVAL_S", "nan"),
    ("IASL_SAMPLING_INTERVAL_S", "inf"),
    ("IASL_ADJUSTMENT_STEP", "0.9"),
    ("IASL_ADJUSTMENT_STEP", "0"),
    ("IASL_OVERLOAD_STEP_MULTIPLIER", "9"),
    ("IASL_OVERLOAD_STEP_MULTIPLIER", "1.5"),
    ("IASL_FALLBACK_MODE", "turbo"),
    ("IASL_ADMISSION_MIN", "0"),
    ("IASL_ADMISSION_MIN", "2.5"),
    ("IASL_EXIT_RATIO", "1.0"),
    ("IASL_SMOOTHING_SAMPLES", "0"),
    ("IASL_DECISION_LOG_SIZE", "5"),
    ("IASL_QUEUE_UTIL_PRESSURE", "0.9"),        # not below the default overload 0.85
    ("IASL_QUEUE_UTIL_OVERLOAD", "1.5"),        # a ratio above 1
    ("IASL_QUEUE_WAIT_P95_PRESSURE_S", "-1"),
    ("IASL_STALE_METRIC_SECONDS", "0.5"),       # less than 2 x the sampling interval
    ("IASL_WATCHDOG_SECONDS", "1.0"),           # less than 3 x the sampling interval
    ("IASL_COOLDOWN_SECONDS", "0.1"),           # less than the sampling interval
    ("IASL_INCREASE_COOLDOWN_SECONDS", "1.0"),  # less than the cooldown
    ("IASL_REVERSAL_LOCKOUT_SECONDS", "1.0"),   # less than the cooldown
])
def test_invalid_values_are_rejected_and_the_message_names_the_variable(variable, value):
    with pytest.raises(ValueError) as caught:
        IASLConfig.from_environment({variable: value})
    assert variable in str(caught.value)


def test_each_threshold_pair_must_be_ordered():
    with pytest.raises(ValueError, match="IASL_ERROR_RATE_PRESSURE"):
        IASLConfig(error_rate_pressure=0.2, error_rate_overload=0.1)


def test_admission_bounds_must_be_ordered_when_both_are_given():
    with pytest.raises(ValueError, match="IASL_ADMISSION_MIN"):
        IASLConfig(admission_min=10, admission_max=5)
    with pytest.raises(ValueError, match="IASL_ADMISSION_INITIAL"):
        IASLConfig(admission_min=4, admission_max=8, admission_initial=2)
    with pytest.raises(ValueError, match="IASL_ADMISSION_INITIAL"):
        IASLConfig(admission_min=4, admission_max=8, admission_initial=9)


def test_a_boolean_is_not_accepted_where_a_number_is_required():
    with pytest.raises(ValueError):
        IASLConfig(smoothing_samples=True)


# ---------------------------------------------------------------- capacity-dependent bounds

def test_automatic_bounds_follow_the_layer_size_and_start_as_permissive_as_no_iasl():
    bounds = IASLConfig().resolve_bounds(queue_capacity=200, worker_count=8)
    assert (bounds.minimum, bounds.maximum, bounds.initial) == (8, 200, 200)


def test_explicit_bounds_are_used_and_the_maximum_is_capped_at_the_queue_capacity():
    config = IASLConfig(admission_min=5, admission_max=500, admission_initial=50)
    bounds = config.resolve_bounds(queue_capacity=100, worker_count=4)
    assert (bounds.minimum, bounds.maximum, bounds.initial) == (5, 100, 50)


def test_automatic_minimum_larger_than_a_tiny_queue_is_reduced_to_the_queue():
    bounds = IASLConfig().resolve_bounds(queue_capacity=2, worker_count=8)
    assert (bounds.minimum, bounds.maximum, bounds.initial) == (2, 2, 2)


def test_impossible_explicit_bounds_stop_start_up_but_are_clamped_when_the_server_is_running():
    config = IASLConfig(admission_min=50)
    with pytest.raises(ValueError, match="IASL_ADMISSION_MIN"):
        config.resolve_bounds(queue_capacity=10, worker_count=2, strict=True)
    lenient = config.resolve_bounds(queue_capacity=10, worker_count=2, strict=False)
    assert (lenient.minimum, lenient.maximum, lenient.initial) == (10, 10, 10)

    config = IASLConfig(admission_initial=60)
    with pytest.raises(ValueError, match="IASL_ADMISSION_INITIAL"):
        config.resolve_bounds(queue_capacity=40, worker_count=2, strict=True)
    assert config.resolve_bounds(queue_capacity=40, worker_count=2, strict=False).initial == 40


def test_fallback_limit_is_always_inside_the_bounds():
    base = IASLConfig(fallback_mode="baseline")
    cons = IASLConfig(fallback_mode="conservative")
    bounds = base.resolve_bounds(100, 4)
    assert base.fallback_limit(bounds, 100) == 100                 # identical to running without IASL
    assert cons.fallback_limit(bounds, 100) == 50
    tight = cons.resolve_bounds(10, 8)                             # minimum 8: half of 10 would be below it
    assert cons.fallback_limit(tight, 10) == 8
