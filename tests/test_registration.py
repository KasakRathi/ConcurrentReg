import pytest
from sqlalchemy.exc import OperationalError

from app import registration_service as service
from app.registration_service import register_student
from tests.conftest import count_registrations, get_section, requires_mysql


def test_successful_registration(db):
    section = get_section(db, "CSE301")

    result = register_student(db, "STU001", section.id)

    assert result.code == service.SUCCESS
    assert count_registrations(db, section.id) == 1
    assert get_section(db, "CSE301").available_seats == 4


def test_duplicate_registration(db):
    section = get_section(db, "CSE301")

    first = register_student(db, "STU001", section.id)
    second = register_student(db, "STU001", section.id)

    assert first.code == service.SUCCESS
    assert second.code == service.DUPLICATE
    assert count_registrations(db, section.id) == 1
    assert get_section(db, "CSE301").available_seats == 4


def test_course_full(db):
    section = get_section(db, "CSE301")
    section.available_seats = 0
    db.commit()

    result = register_student(db, "STU001", section.id)

    assert result.code == service.FULL
    assert count_registrations(db, section.id) == 0
    assert get_section(db, "CSE301").available_seats == 0


def test_invalid_student(db):
    section = get_section(db, "CSE301")

    result = register_student(db, "NOPE999", section.id)

    assert result.code == service.STUDENT_NOT_FOUND
    assert count_registrations(db, section.id) == 0
    assert get_section(db, "CSE301").available_seats == 5


def test_invalid_section(db):
    result = register_student(db, "STU001", 9999)

    assert result.code == service.SECTION_NOT_FOUND
    assert count_registrations(db, 9999) == 0


def test_failure_in_the_middle_rolls_everything_back(db, monkeypatch):
    section = get_section(db, "CSE301")

    def fail_after_insert(db, section):
        db.flush()  # the registration INSERT really reaches the database...
        raise OperationalError("UPDATE", {}, Exception("simulated crash"))  # ...then we crash

    monkeypatch.setattr(service, "decrease_available_seats", fail_after_insert)

    result = register_student(db, "STU001", section.id)

    assert result.code == service.ERROR
    assert count_registrations(db, section.id) == 0
    assert get_section(db, "CSE301").available_seats == 5


# The service recognises the duplicate by the constraint name in MySQL's error text;
# SQLite words that message differently, so this test is MySQL-only.
@requires_mysql
def test_unique_constraint_is_handled_cleanly_when_the_duplicate_check_misses(db, monkeypatch):
    section = get_section(db, "CSE301")
    register_student(db, "STU001", section.id)
    # Pretend the application check missed the existing registration (this is
    # what a concurrent request can see). The database constraint must stop it.
    monkeypatch.setattr(service, "is_already_registered", lambda db, student_pk, section_id: False)

    result = register_student(db, "STU001", section.id)

    assert result.code == service.DUPLICATE
    assert count_registrations(db, section.id) == 1
    assert get_section(db, "CSE301").available_seats == 4
