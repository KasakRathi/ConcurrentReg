import uuid
import time
import threading
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from app.os_layer.request_queue import BoundedRequestQueue, QueueFullError
from app.os_layer.worker_pool import WorkerPool
from app.os_layer.semaphore_manager import SemaphoreManager
from app.db.database import get_db_session
from app.db.models import RegistrationRequest, Student, Course

logger = logging.getLogger(__name__)

class AdmissionController:
    """
    OS Admission Control Layer:
    - Validates request structure
    - Enforces bounded buffer admission policies
    - Prevents system thrashing under extreme load
    - Supports synchronous wait or asynchronous event completion
    """
    def __init__(self, queue: BoundedRequestQueue, worker_pool: WorkerPool, semaphore_mgr: SemaphoreManager):
        self.queue = queue
        self.worker_pool = worker_pool
        self.semaphore_mgr = semaphore_mgr
        
        # Recent requests memory cache for fast polling / testing
        self._recent_requests: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit_registration(self, student_id: str, course_id: int, wait_for_completion: bool = True, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Intake pipeline for course registration requests:
        1. Unique Request ID generation (UUID)
        2. Intake validation
        3. Persist RECEIVED state
        4. Admission Check against bounded queue
        5. If admitted -> Enqueue with completion event
        6. If wait_for_completion=True -> Await worker execution or timeout
        """
        request_id = str(uuid.uuid4())
        arrival_time = datetime.utcnow()
        start_mono = time.time()

        # Step 1: Input Validation
        if not student_id or not isinstance(student_id, str):
            return {
                "request_id": request_id,
                "success": False,
                "status": "REJECTED",
                "code": "INVALID_STUDENT_ID",
                "message": "Student ID is required and must be a valid string."
            }

        try:
            course_id = int(course_id)
        except (ValueError, TypeError):
            return {
                "request_id": request_id,
                "success": False,
                "status": "REJECTED",
                "code": "INVALID_COURSE_ID",
                "message": "Course ID must be a valid integer."
            }

        # Step 2: Record incoming request in DB
        self._record_intake_in_db(request_id, student_id, course_id, arrival_time)

        # Step 3: Admission Control Check (Attempt Bounded Queue Insertion)
        completion_event = threading.Event()
        result_holder = {}
        request_item = {
            "request_id": request_id,
            "student_id": student_id.strip(),
            "course_id": course_id,
            "arrival_time": arrival_time,
            "completion_event": completion_event,
            "result_holder": result_holder
        }

        try:
            self.queue.push(request_item, block=False)
            # Admitted into bounded queue
            self._update_db_status(request_id, "QUEUED")
        except QueueFullError:
            # OS Queue Capacity Exceeded - Reject gracefully
            elapsed_ms = round((time.time() - start_mono) * 1000, 2)
            self._update_db_status(
                request_id=request_id,
                status="REJECTED",
                processing_time=elapsed_ms,
                error_message="Request Queue Full"
            )
            rejection_result = {
                "request_id": request_id,
                "success": False,
                "status": "REJECTED",
                "code": "QUEUE_FULL",
                "message": "Request Queue Full: System under heavy load. Please retry in a few moments.",
                "processing_time_ms": elapsed_ms
            }
            with self._lock:
                self._recent_requests[request_id] = rejection_result
            return rejection_result

        # If admitted and synchronous execution is desired:
        if wait_for_completion:
            finished = completion_event.wait(timeout=timeout)
            if finished and result_holder:
                with self._lock:
                    self._recent_requests[request_id] = result_holder
                return result_holder
            else:
                # Still processing or timed out waiting for worker
                pending_resp = {
                    "request_id": request_id,
                    "success": False,
                    "status": "PROCESSING",
                    "code": "PROCESSING_TIMEOUT",
                    "message": "Registration is currently processing in the worker queue.",
                    "poll_url": f"/api/requests/{request_id}"
                }
                return pending_resp
        else:
            # Asynchronous return (used during bulk load simulation)
            async_resp = {
                "request_id": request_id,
                "success": True,
                "status": "QUEUED",
                "message": "Registration request accepted into queue.",
                "poll_url": f"/api/requests/{request_id}"
            }
            with self._lock:
                self._recent_requests[request_id] = async_resp
            return async_resp

    def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves request status from cache or database."""
        with self._lock:
            if request_id in self._recent_requests:
                # If cached result is already final, return it
                res = self._recent_requests[request_id]
                if res.get("status") in ("SUCCESS", "FAILED", "REJECTED"):
                    return res

        # Query database for authoritative status
        try:
            with get_db_session() as session:
                req = session.query(RegistrationRequest).filter(RegistrationRequest.request_id == request_id).first()
                if req:
                    data = req.to_dict()
                    with self._lock:
                        self._recent_requests[request_id] = data
                    return data
        except Exception as e:
            logger.error(f"Error reading request {request_id} from DB: {e}")
        return None

    def _record_intake_in_db(self, request_id: str, student_id: str, course_id: int, arrival_time: datetime):
        try:
            with get_db_session() as session:
                req = RegistrationRequest(
                    request_id=request_id,
                    student_id=student_id,
                    course_id=course_id,
                    status="RECEIVED",
                    arrival_time=arrival_time
                )
                session.add(req)
                session.commit()
        except Exception as e:
            logger.warning(f"Error persisting intake request {request_id}: {e}")

    def _update_db_status(self, request_id: str, status: str, processing_time: float = None, error_message: str = None):
        try:
            with get_db_session() as session:
                req = session.query(RegistrationRequest).filter(RegistrationRequest.request_id == request_id).first()
                if req:
                    req.status = status
                    if status in ("SUCCESS", "FAILED", "REJECTED"):
                        req.completion_time = datetime.utcnow()
                    if processing_time is not None:
                        req.processing_time = processing_time
                    if error_message:
                        req.error_message = error_message
                    session.commit()
        except Exception as e:
            logger.warning(f"Error updating request {request_id} status to {status}: {e}")
