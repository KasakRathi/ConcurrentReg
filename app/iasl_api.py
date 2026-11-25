"""Read-only monitoring endpoints for IASL: GET /iasl/status, /iasl/metrics, /iasl/decisions, /iasl/config.

Only GET routes exist. There is deliberately NO endpoint that changes IASL: its settings come from the
environment at start-up (see IASL_CONFIGURATION), so there is no unsafe control operation to protect.
Every handler reads an immutable snapshot that the controller thread published (or a short-lock copy of the
bounded decision log), does no I/O, and never calls into the OS layer, so monitoring cannot slow registrations.
When IASL is off the endpoints still answer, saying so, so a dashboard can tell "off" from "broken".
"""
from fastapi import APIRouter, Query, Request

from app.iasl import serialize
from app.iasl.config import ENV_NAMES, IASLConfig

router = APIRouter(prefix="/iasl")

CALIBRATION_NOTE = ("Thresholds and limits are PROVISIONAL defaults. They have not been calibrated or validated "
                    "by experiment; treat them as starting values only.")
OFF = {"enabled": False, "message": "IASL is switched off (IASL_ENABLED is not true). Nothing is installed on the request path."}


def _runtime(request: Request):
    return getattr(request.app.state, "iasl", None)


def _settings(request: Request):
    return getattr(request.app.state, "iasl_config", None) or IASLConfig()


@router.get("/status")
async def status(request: Request):
    """Is IASL on, what state does it see, what is it doing to admission, and why."""
    runtime = _runtime(request)
    if runtime is None:
        return OFF
    snap = runtime.snapshot()
    controller, admission = snap.controller or {}, snap.admission or {}
    parameter = controller.get("parameter") or {}
    last, action = controller.get("last_decision"), controller.get("last_control_action")
    metrics = serialize.key_metrics(snap.sample)
    if metrics is not None:
        metrics["sample_age_s"] = round(snap.sample.age(runtime.now()), 3)
    assessment = snap.assessment
    return {
        "enabled": True, "attached": snap.attached, "running": snap.running,
        "state": assessment.state.value if assessment else None,
        "state_reason": assessment.reason if assessment else "no sample has been analysed yet",
        "assessment_quality": assessment.quality.value if assessment else None,
        "metrics_quality": snap.sample.quality.value if snap.sample else None,
        "current_metrics": metrics,
        "admission": {
            "limit_in_force": admission.get("limit"), "configured_limit": admission.get("configured_limit"),
            "capacity": admission.get("capacity"), "minimum": parameter.get("minimum"), "maximum": parameter.get("maximum"),
            "initial": parameter.get("initial"), "step": parameter.get("step"),
            "what_it_limits": "a request is admitted only while fewer than this many requests are waiting in the queue",
        },
        "fallback": {
            "active": controller.get("fallback_active"), "watchdog_tripped": admission.get("watchdog_tripped"),
            "mode": _settings(request).fallback_mode, "fallback_limit": controller.get("fallback_limit"),
        },
        "last_control_action": action,
        "last_decision": last,
        "last_decision_reason": last["reason"] if last else None,
        "loop": {
            "sampling_interval_s": _settings(request).sampling_interval_s, "ticks": snap.ticks,
            "failed_ticks": snap.failed_ticks, "consecutive_failures": controller.get("consecutive_failures"),
            "changes": controller.get("changes"), "blocked_changes": controller.get("blocked_changes"),
            "updated_at": snap.updated_wall,
        },
        "calibration": CALIBRATION_NOTE,
    }


@router.get("/metrics")
async def metrics(request: Request, history: int = Query(0, ge=0, le=120, description="also return this many recent samples")):
    """The latest sample, every field typed by kind (instantaneous / interval / window), and the latest analysis."""
    runtime = _runtime(request)
    if runtime is None:
        return OFF
    snap = runtime.snapshot()
    body = {
        "enabled": True,
        "sample": serialize.sample_to_dict(snap.sample, runtime.now()),
        "analysis": serialize.assessment_to_dict(snap.assessment),
        "sampling_interval_s": _settings(request).sampling_interval_s,
    }
    if history:
        body["history"] = [serialize.history_row(s) for s in runtime.history()[-history:]]
    return body


@router.get("/decisions")
async def decisions(request: Request, limit: int = Query(50, ge=1, le=200)):
    """The most recent decisions, oldest first. Idle ticks are counted, not listed (see suppressed_since_last)."""
    runtime = _runtime(request)
    if runtime is None:
        return {**OFF, "decisions": []}
    items = runtime.decisions()
    return {
        "enabled": True, "returned": len(items[-limit:]), "kept": len(items),
        "note": "Repeated idle or blocked ticks are not logged individually; each decision's suppressed_since_last "
                "says how many identical ticks preceded it.",
        "decisions": [d.as_dict() for d in items[-limit:]],
    }


@router.get("/config")
async def config(request: Request):
    """The settings in force. Read-only: change them with the IASL_* environment variables and restart."""
    settings, runtime = _settings(request), _runtime(request)
    body = {
        "enabled": settings.enabled, "active": runtime is not None, "read_only": True,
        "how_to_change": "set the IASL_* environment variables and restart the server; there is no runtime write endpoint",
        "calibration": CALIBRATION_NOTE,
        "settings": settings.as_dict(), "environment_variables": ENV_NAMES,
    }
    if runtime is not None and runtime.controller is not None:
        param = runtime.controller.param
        body["resolved"] = {
            "parameter": param.name, "minimum": param.minimum, "maximum": param.maximum, "initial": param.initial,
            "step": param.step, "largest_single_move": param.max_move,
            "fallback_limit": runtime.controller.status()["fallback_limit"], "fallback_mode": settings.fallback_mode,
        }
    return body
