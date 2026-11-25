import time
import logging
from datetime import datetime
from sqlalchemy.exc import IntegrityError, OperationalError
from app.db.database import get_db_session
from app.db.models import Student, Course, Registration, RegistrationRequest

logger = logging.getLogger(__name__)

class RegistrationError(Exception):
    def __init__(self, message, code="REGISTRATION_FAILED"):
        super().__init__(message)
        self.message = message
        self.code = code

class RegistrationService:
    """
    Transactional Course Registration Service with Row-Level Locking and ACID guarantees.
    Prevents over-enrollment and duplicate registrations under high concurrent contention.
    """

    @staticmethod
    def register_student(student_external_id: str, course_id: int, request_id: str = None, max_retries: int = 3):
        """
        Executes course registration in an explicit ACID transaction with row-level locking.
        
        Algorithm:
        1. Begin Transaction
        2. Validate Student exists
        3. Lock Course row with SELECT ... FOR UPDATE
        4. Validate Course exists
        5. Check if Student is already registered (Application check)
        6. Check if Seats are available (enrolled_count < capacity)
        7. Insert Registration row (Database UNIQUE constraint protects against races)
        8. Increment Course.enrolled_count
        9. Commit Transaction
        If any validation fails or error occurs:
           Rollback Transaction and record error
        """
        attempts = 0
        contention_detected = False
        retried = False

        while attempts < max_retries:
            attempts += 1
            start_time = time.time()
            try:
                with get_db_session() as session:
                    # 1. Validate Student existence
                    student = session.query(Student).filter(Student.student_id == student_external_id).first()
                    if not student:
                        raise RegistrationError(f"Student '{student_external_id}' not found.", code="STUDENT_NOT_FOUND")

                    # 2. Acquire Row-Level Lock on Course row
                    # with_for_update() executes 'SELECT ... FOR UPDATE' in MySQL InnoDB
                    course = session.query(Course).filter(Course.id == course_id).with_for_update().first()
                    if not course:
                        raise RegistrationError(f"Course ID {course_id} not found.", code="COURSE_NOT_FOUND")

                    # 3. Check for existing active registration (Application Check)
                    existing_reg = session.query(Registration).filter(
                        Registration.student_id == student.id,
                        Registration.course_id == course.id,
                        Registration.registration_status == 'CONFIRMED'
                    ).first()
                    if existing_reg:
                        raise RegistrationError(
                            f"Already Registered: Student '{student_external_id}' is already registered for {course.course_code}.",
                            code="ALREADY_REGISTERED"
                        )

                    # 4. Check Seat Availability (Capacity Check)
                    if course.enrolled_count >= course.capacity:
                        raise RegistrationError(
                            f"Course is Full: '{course.course_name}' has reached capacity ({course.capacity}/{course.capacity}).",
                            code="COURSE_FULL"
                        )

                    # 5. Insert Registration Record
                    new_reg = Registration(
                        student_id=student.id,
                        course_id=course.id,
                        registration_status='CONFIRMED',
                        registered_at=datetime.utcnow()
                    )
                    session.add(new_reg)

                    # 6. Increment Enrolled Count atomically within transaction
                    course.enrolled_count += 1

                    # 7. Commit Transaction
                    session.commit()

                    proc_time = round((time.time() - start_time) * 1000, 2)
                    logger.info(
                        f"[TRANSACTION COMMIT] Registered student {student_external_id} for course {course.course_code}. "
                        f"Enrolled: {course.enrolled_count}/{course.capacity}. Elapsed: {proc_time}ms"
                    )

                    return {
                        "success": True,
                        "status": "SUCCESS",
                        "message": "Registration Successful",
                        "registration_id": new_reg.id,
                        "student_id": student.student_id,
                        "student_name": student.name,
                        "course_id": course.id,
                        "course_code": course.course_code,
                        "course_name": course.course_name,
                        "enrolled_count": course.enrolled_count,
                        "capacity": course.capacity,
                        "attempts": attempts,
                        "contention": contention_detected,
                        "retried": retried,
                        "processing_time_ms": proc_time
                    }

            except IntegrityError as ie:
                # Catch database-level UNIQUE constraint violations (race condition safety net)
                logger.warning(f"[DB CONSTRAINT VIOLATION] Integrity error for {student_external_id} in course {course_id}: {ie}")
                return {
                    "success": False,
                    "status": "FAILED",
                    "code": "ALREADY_REGISTERED",
                    "message": "Already Registered (enforced by DB unique constraint)",
                    "attempts": attempts,
                    "contention": True,
                    "retried": retried
                }

            except OperationalError as oe:
                # Database lock wait timeout or deadlock detected
                contention_detected = True
                retried = True
                logger.warning(f"[DB CONTENTION] Lock wait or deadlock on attempt {attempts}/{max_retries}: {oe}")
                if attempts < max_retries:
                    time.sleep(0.05 * (2 ** attempts))  # exponential backoff
                    continue
                else:
                    return {
                        "success": False,
                        "status": "FAILED",
                        "code": "DB_LOCK_TIMEOUT",
                        "message": "Database Error: Lock contention timeout under concurrent load",
                        "attempts": attempts,
                        "contention": True,
                        "retried": True
                    }

            except RegistrationError as re:
                # Controlled domain validation failures (e.g. course full, already registered)
                return {
                    "success": False,
                    "status": "FAILED",
                    "code": re.code,
                    "message": re.message,
                    "attempts": attempts,
                    "contention": contention_detected,
                    "retried": retried
                }

            except Exception as e:
                logger.error(f"[TRANSACTION ROLLBACK] Unexpected registration error: {e}", exc_info=True)
                return {
                    "success": False,
                    "status": "FAILED",
                    "code": "INTERNAL_ERROR",
                    "message": f"Database Error: {str(e)}",
                    "attempts": attempts,
                    "contention": contention_detected,
                    "retried": retried
                }

        return {
            "success": False,
            "status": "FAILED",
            "code": "MAX_RETRIES_EXCEEDED",
            "message": "Registration failed after maximum retry attempts.",
            "attempts": attempts,
            "contention": True,
            "retried": True
        }

    @staticmethod
    def cancel_registration(registration_id: int):
        """
        Cancels an existing registration within a transaction and safely decrements seat count.
        """
        start_time = time.time()
        with get_db_session() as session:
            reg = session.query(Registration).filter(Registration.id == registration_id).first()
            if not reg:
                raise RegistrationError("Registration record not found.", code="NOT_FOUND")

            course = session.query(Course).filter(Course.id == reg.course_id).with_for_update().first()
            if course and course.enrolled_count > 0:
                course.enrolled_count -= 1

            course_code = course.course_code if course else "Unknown"
            session.delete(reg)
            session.commit()

            proc_time = round((time.time() - start_time) * 1000, 2)
            logger.info(f"[TRANSACTION COMMIT] Cancelled registration {registration_id} for course {course_code}. Elapsed: {proc_time}ms")

            return {
                "success": True,
                "status": "CANCELLED",
                "message": "Registration cancelled successfully.",
                "processing_time_ms": proc_time
            }
