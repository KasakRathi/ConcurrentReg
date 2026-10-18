import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import CourseSection, Registration, Student

logger = logging.getLogger("registration")

# Result codes. The API layer turns these into HTTP status codes.
SUCCESS = "SUCCESS"
DUPLICATE = "DUPLICATE"
FULL = "FULL"
STUDENT_NOT_FOUND = "STUDENT_NOT_FOUND"
SECTION_NOT_FOUND = "SECTION_NOT_FOUND"
ERROR = "ERROR"


@dataclass
class RegistrationResult:
    code: str
    message: str

    @property
    def success(self):
        return self.code == SUCCESS


def register_student(db, student_code, section_id, request_id=None):
    """Try to register one student in one course section.

    `student_code` is the text code such as "STU001".
    `request_id` lets a caller (the Day 3 OS layer) pass its own id so both log lines match.
    Never raises for expected problems; returns a RegistrationResult instead.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = datetime.now()
    timer = time.perf_counter()
    error_detail = None

    try:
        result = _register(db, student_code, section_id)
    except SQLAlchemyError as error:
        db.rollback()
        error_detail = f"{type(error).__name__}: {getattr(error, 'orig', error)}"
        result = RegistrationResult(ERROR, "Registration failed because of a database error")

    logger.info(json.dumps({
        "event": "registration",
        "request_id": request_id,
        "student_id": student_code,
        "section_id": section_id,
        "started_at": started_at.isoformat(timespec="milliseconds"),
        "result": result.code,
        "error": error_detail,
        "duration_ms": round((time.perf_counter() - timer) * 1000, 2),
    }))
    return result


def _register(db, student_code, section_id):
    # One transaction for the whole request. It starts at the first query below
    # and ends with exactly one commit or rollback on every path.
    student = db.scalar(select(Student).where(Student.student_id == student_code))
    if student is None:
        db.rollback()
        return RegistrationResult(STUDENT_NOT_FOUND, "Student does not exist")

    # The lock query is also our "does this section exist" check.
    section = lock_section(db, section_id)
    if section is None:
        db.rollback()
        return RegistrationResult(SECTION_NOT_FOUND, "Course section does not exist")

    # This read may come from a snapshot taken before we got the lock, so it can
    # miss a registration committed while we waited. The UNIQUE constraint
    # catches that case at insert time (see the IntegrityError handler below).
    if is_already_registered(db, student.id, section_id):
        db.rollback()
        return RegistrationResult(DUPLICATE, "Student is already registered for this course section")

    if section.available_seats <= 0:
        db.rollback()
        return RegistrationResult(FULL, "Course section is full")

    try:
        db.add(Registration(student_id=student.id, section_id=section_id))
        decrease_available_seats(db, section)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        # The unique constraint is the last line of defence against duplicates.
        if "uq_student_section" in str(error.orig):
            return RegistrationResult(DUPLICATE, "Student is already registered for this course section")
        raise

    return RegistrationResult(SUCCESS, "Registration successful")


def lock_section(db, section_id):
    """SELECT ... FOR UPDATE: other transactions wait here until we commit or roll back."""
    query = select(CourseSection).where(CourseSection.id == section_id).with_for_update()
    return db.scalar(query)


def is_already_registered(db, student_pk, section_id):
    query = select(Registration.id).where(
        Registration.student_id == student_pk,
        Registration.section_id == section_id,
    )
    return db.scalar(query) is not None


def decrease_available_seats(db, section):
    section.available_seats -= 1
