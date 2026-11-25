import pytest
from concurrent.futures import ThreadPoolExecutor
from app.db.database import init_db, get_db_session
from app.db.models import Student, Course, Registration
from app.db.registration_service import RegistrationService

@pytest.fixture(autouse=True)
def setup_db():
    init_db(seed=True)
    yield

def test_successful_registration_and_seat_decrement():
    with get_db_session() as session:
        # Create a fresh course with capacity 2
        course = Course(
            course_code="TEST101",
            course_name="Test Concurrency Course",
            department="Computer Science",
            instructor="Test Prof",
            capacity=2,
            enrolled_count=0
        )
        session.add(course)
        session.commit()
        course_id = course.id

    # Register student CS2024001
    res = RegistrationService.register_student("CS2024001", course_id)
    assert res["success"] is True
    assert res["status"] == "SUCCESS"
    assert res["enrolled_count"] == 1

    # Verify in DB
    with get_db_session() as session:
        c = session.query(Course).filter(Course.id == course_id).first()
        assert c.enrolled_count == 1
        assert c.available_seats == 1

def test_duplicate_registration_prevention():
    with get_db_session() as session:
        course = Course(
            course_code="TEST102",
            course_name="Test Duplicate Prevention",
            department="Computer Science",
            instructor="Test Prof",
            capacity=10,
            enrolled_count=0
        )
        session.add(course)
        session.commit()
        course_id = course.id

    # First registration -> SUCCESS
    res1 = RegistrationService.register_student("CS2024002", course_id)
    assert res1["success"] is True

    # Duplicate registration -> FAILED
    res2 = RegistrationService.register_student("CS2024002", course_id)
    assert res2["success"] is False
    assert res2["code"] == "ALREADY_REGISTERED"

    # Enrolled count should remain strictly 1
    with get_db_session() as session:
        c = session.query(Course).filter(Course.id == course_id).first()
        assert c.enrolled_count == 1

def test_course_full_rejection():
    with get_db_session() as session:
        # Strict capacity of 1
        course = Course(
            course_code="TEST103",
            course_name="Test Strict Capacity",
            department="Computer Science",
            instructor="Test Prof",
            capacity=1,
            enrolled_count=0
        )
        session.add(course)
        session.commit()
        course_id = course.id

    # First student takes the only seat
    res1 = RegistrationService.register_student("CS2024003", course_id)
    assert res1["success"] is True

    # Second student should be rejected
    res2 = RegistrationService.register_student("CS2024004", course_id)
    assert res2["success"] is False
    assert res2["code"] == "COURSE_FULL"
    assert "Course is Full" in res2["message"]

    # Verify no over-enrollment
    with get_db_session() as session:
        c = session.query(Course).filter(Course.id == course_id).first()
        assert c.enrolled_count == 1

def test_concurrent_registrations_zero_over_enrollment():
    """
    Simulates 10 concurrent threads attempting to register for a course with only 3 seats.
    Guarantees exactly 3 succeed, 7 fail with COURSE_FULL, and enrolled_count == 3.
    """
    with get_db_session() as session:
        course = Course(
            course_code="HOTSPOT99",
            course_name="Extreme Contention Elective",
            department="Computer Science",
            instructor="Test Prof",
            capacity=3,
            enrolled_count=0
        )
        session.add(course)
        session.commit()
        course_id = course.id

    students = [f"CS2024{i:03d}" for i in range(1, 11)]

    def do_register(s_id):
        return RegistrationService.register_student(s_id, course_id)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(do_register, students))

    successes = [r for r in results if r["success"] is True]
    failures = [r for r in results if r["success"] is False]

    assert len(successes) == 3, f"Expected exactly 3 successes, got {len(successes)}"
    assert len(failures) == 7, f"Expected exactly 7 failures, got {len(failures)}"

    with get_db_session() as session:
        c = session.query(Course).filter(Course.id == course_id).first()
        assert c.enrolled_count == 3, f"Capacity violation! Enrolled: {c.enrolled_count}, Max: 3"
        regs = session.query(Registration).filter(Registration.course_id == course_id).count()
        assert regs == 3

def test_cancellation_and_seat_restoration():
    with get_db_session() as session:
        course = Course(
            course_code="TEST105",
            course_name="Cancellation Test",
            department="Computer Science",
            instructor="Test Prof",
            capacity=5,
            enrolled_count=0
        )
        session.add(course)
        session.commit()
        course_id = course.id

    # Register
    res = RegistrationService.register_student("CS2024005", course_id)
    reg_id = res["registration_id"]

    # Cancel
    cancel_res = RegistrationService.cancel_registration(reg_id)
    assert cancel_res["success"] is True

    # Seat should be restored
    with get_db_session() as session:
        c = session.query(Course).filter(Course.id == course_id).first()
        assert c.enrolled_count == 0
        assert c.available_seats == 5
