import dataclasses
from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.os_layer import request_pipeline
from app.registration_service import RegistrationResult
from tests.conftest import count_registrations, get_section


@pytest.fixture
def client():
    # "with" runs the app's startup and shutdown, which start and stop the OS-layer workers.
    with TestClient(app) as test_client:
        yield test_client


def test_post_registration_then_duplicate(client, db):
    section_id = get_section(db, "CSE301").id
    body = {"student_id": "STU001", "section_id": section_id}

    first = client.post("/registrations", json=body)
    second = client.post("/registrations", json=body)

    assert first.status_code == 201
    assert first.json() == {"success": True, "message": "Registration successful"}
    assert second.status_code == 409
    assert second.json() == {
        "success": False,
        "message": "Student is already registered for this course section",
    }


def test_post_unknown_student_is_404(client):
    response = client.post("/registrations", json={"student_id": "NOPE", "section_id": 1})
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_full_queue_is_answered_with_the_provisional_503(client, monkeypatch):
    # The queue-full response is not decided in the Master MD; 503 is a placeholder (see main.py).
    refused = Future()
    refused.set_result(RegistrationResult(request_pipeline.QUEUE_FULL, request_pipeline.QUEUE_FULL_MESSAGE))
    monkeypatch.setattr(app.state.os_layer, "submit", lambda student_code, section_id: refused)

    response = client.post("/registrations", json={"student_id": "STU001", "section_id": 1})

    assert response.status_code == 503
    assert response.json() == {"success": False, "message": "Request queue is full"}


def test_status_endpoint_reports_configuration_and_counters(client):
    client.post("/registrations", json={"student_id": "STU001", "section_id": 1})

    status = client.get("/os-layer/status").json()

    assert status["config"] == dataclasses.asdict(app.state.os_layer.config)
    assert status["queue"]["accepted"] == 1
    assert status["queue"]["capacity"] == status["config"]["queue_capacity"]
    assert status["workers"]["jobs_finished"] == 1
    assert status["db_semaphore"]["acquisitions"] == 1


def test_request_arriving_after_shutdown_began_gets_503_and_registers_nothing(client, db):
    app.state.os_layer.stop()         # what the app does when it shuts down (the fixture will stop it again; that is harmless)

    response = client.post("/registrations", json={"student_id": "STU001", "section_id": 1})

    assert response.status_code == 503
    assert response.json() == {"success": False, "message": "Server is shutting down"}
    assert count_registrations(db, 1) == 0
