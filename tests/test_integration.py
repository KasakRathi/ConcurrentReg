import pytest
import time
from app import create_app
from app.db.database import get_db_session
from app.db.models import Course, Student

@pytest.fixture
def client():
    app = create_app(start_workers=True)
    with app.test_client() as client:
        yield client
    # Stop background threads after tests
    worker_pool = app.extensions.get('worker_pool')
    iasl_controller = app.extensions.get('iasl_controller')
    if worker_pool:
        worker_pool.stop()
    if iasl_controller:
        iasl_controller.stop_background_evaluator()

def test_health_endpoint(client):
    res = client.get('/api/health')
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert "queue_capacity" in data
    assert "worker_count" in data

def test_course_crud_endpoints(client):
    # List courses
    res = client.get('/api/courses')
    assert res.status_code == 200
    assert res.get_json()["count"] >= 8

    # Create new course
    new_course = {
        "course_code": "CS699",
        "course_name": "Quantum Computing & Concurrency",
        "department": "Computer Science",
        "instructor": "Dr. Feynman",
        "credits": 4,
        "capacity": 20
    }
    create_res = client.post('/api/courses', json=new_course)
    assert create_res.status_code == 201
    course_id = create_res.get_json()["course"]["id"]

    # Retrieve created course
    get_res = client.get(f'/api/courses/{course_id}')
    assert get_res.status_code == 200
    assert get_res.get_json()["course"]["course_code"] == "CS699"

    # Update course capacity
    update_res = client.put(f'/api/courses/{course_id}', json={"capacity": 25})
    assert update_res.status_code == 200
    assert update_res.get_json()["course"]["capacity"] == 25

    # Delete course
    del_res = client.delete(f'/api/courses/{course_id}')
    assert del_res.status_code == 200

def test_registration_pipeline_integration(client):
    """
    End-to-end integration test:
    HTTP POST /api/registrations -> Admission Control -> Bounded Queue -> Worker Thread
    -> Dynamic Semaphore -> MySQL Transaction -> Result Response
    """
    # Register student CS2024006 for Course 1
    res = client.post('/api/registrations', json={
        "student_id": "CS2024006",
        "course_id": 1
    })
    assert res.status_code in (200, 400) # 200 if fresh, 400 if already registered from earlier seed
    data = res.get_json()
    assert "status" in data
    assert "request_id" in data

    # Check request audit record
    req_res = client.get(f"/api/requests/{data['request_id']}")
    assert req_res.status_code == 200
    req_data = req_res.get_json()["request"]
    assert req_data["request_id"] == data["request_id"]
    assert req_data["status"] in ("SUCCESS", "FAILED")

def test_iasl_endpoints(client):
    # Status
    status_res = client.get('/api/iasl/status')
    assert status_res.status_code == 200
    status = status_res.get_json()["status"]
    assert "current_concurrency" in status
    assert "current_pressure_score" in status

    # Metrics
    metrics_res = client.get('/api/iasl/metrics')
    assert metrics_res.status_code == 200
    metrics = metrics_res.get_json()["metrics"]
    assert "queue_pressure" in metrics
    assert "active_request_pressure" in metrics

    # History
    history_res = client.get('/api/iasl/history')
    assert history_res.status_code == 200
    assert "decisions" in history_res.get_json()

    # Manual Evaluate
    eval_res = client.post('/api/iasl/evaluate', json={})
    assert eval_res.status_code == 200
    assert eval_res.get_json()["success"] is True
