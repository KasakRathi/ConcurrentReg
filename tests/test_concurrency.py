import threading

from app import models
from app import registration_service as service
from app.database import SessionLocal
from tests.conftest import count_registrations, get_section, requires_mysql


@requires_mysql
def test_one_seat_two_students_at_the_same_time(db):
    section = models.CourseSection(
        course_code="TEST1", course_name="One seat (test)", capacity=1, available_seats=1,
    )
    db.add(section)
    db.add(models.Student(student_id="CONC_A", name="Concurrent A"))
    db.add(models.Student(student_id="CONC_B", name="Concurrent B"))
    db.commit()
    section_id = section.id

    results = {}
    start_together = threading.Barrier(2)

    def attempt(student_code):
        session = SessionLocal()  # each simulated request gets its own session
        try:
            start_together.wait()
            results[student_code] = service.register_student(session, student_code, section_id)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt, args=(code,)) for code in ("CONC_A", "CONC_B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    codes = sorted(result.code for result in results.values())
    print(f"\nconcurrency results: { {k: v.code for k, v in results.items()} }")

    assert codes == [service.FULL, service.SUCCESS]
    assert count_registrations(db, section_id) == 1
    assert get_section(db, "TEST1").available_seats == 0  # no overselling


def run_requests_together(requests, section_id):
    """Fire all registration requests at the same moment, each on its own session.

    `requests` is a list of student codes. Returns (results, errors): the
    RegistrationResult of each request, and any exception that escaped a thread.
    """
    results = []
    errors = []
    start_together = threading.Barrier(len(requests))

    def attempt(student_code):
        session = SessionLocal()
        try:
            start_together.wait()
            results.append(service.register_student(session, student_code, section_id))
        except Exception as error:  # an exception escaping the service is a test failure
            errors.append(error)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt, args=(code,)) for code in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


@requires_mysql
def test_same_student_twice_at_the_same_time(db):
    section = get_section(db, "CSE301")  # capacity 5, so seats never run out
    section_id = section.id

    results, errors = run_requests_together(["STU001", "STU001"], section_id)

    print(f"\nsame-student results: {sorted(r.code for r in results)}")
    assert errors == []
    assert sorted(r.code for r in results) == [service.DUPLICATE, service.SUCCESS]
    assert count_registrations(db, section_id) == 1
    assert get_section(db, "CSE301").available_seats == 4  # decreased exactly once


@requires_mysql
def test_fifty_students_compete_for_ten_seats(db):
    section = models.CourseSection(
        course_code="TEST10", course_name="Ten seats (test)", capacity=10, available_seats=10,
    )
    db.add(section)
    valid_codes = [f"BULK{number:02d}" for number in range(50)]
    for code in valid_codes:
        db.add(models.Student(student_id=code, name=f"Bulk {code}"))
    db.commit()
    section_id = section.id

    invalid_codes = ["GHOST1", "GHOST2"]
    results, errors = run_requests_together(valid_codes + invalid_codes, section_id)

    counts = {code: sum(1 for r in results if r.code == code) for code in {r.code for r in results}}
    print(f"\n52 concurrent requests -> {counts}")

    db.rollback()
    registered_codes = [
        code for (code,) in db.query(models.Student.student_id)
        .join(models.Registration, models.Registration.student_id == models.Student.id)
        .filter(models.Registration.section_id == section_id)
    ]
    successes = counts.get(service.SUCCESS, 0)
    final_seats = get_section(db, "TEST10").available_seats

    assert errors == []
    assert len(results) == 52
    assert service.ERROR not in counts                      # no uncaught transaction errors
    assert counts.get(service.STUDENT_NOT_FOUND) == 2       # the two invalid students
    assert successes <= 10                                  # no overselling
    assert final_seats >= 0                                 # no negative seats
    assert successes + final_seats == 10                    # seat conservation
    assert len(registered_codes) == successes               # every success has a row, and nothing else does
    assert len(set(registered_codes)) == len(registered_codes)  # no duplicates
    assert set(registered_codes) <= set(valid_codes)        # nothing registered for invalid students
    assert successes == 10 and counts.get(service.FULL) == 40  # 50 valid requests, 10 seats
