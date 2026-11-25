from flask import Blueprint, request, jsonify, current_app
from app.db.database import get_db_session
from app.db.models import Registration, Student, Course
from app.db.registration_service import RegistrationService, RegistrationError

registration_bp = Blueprint('registrations', __name__, url_prefix='/api/registrations')

@registration_bp.route('', methods=['POST'])
def submit_registration():
    """
    Submits a registration request into the OS pipeline.
    Request Pipeline:
    Intake Validation -> Admission Control -> Bounded Queue -> Worker -> Semaphore -> DB Transaction
    """
    data = request.get_json() or {}
    student_id = data.get('student_id', '').strip()
    course_id = data.get('course_id')

    if not student_id or course_id is None:
        return jsonify({"success": False, "message": "student_id and course_id are required."}), 400

    admission_controller = current_app.extensions.get('admission_controller')
    if not admission_controller:
        return jsonify({"success": False, "message": "System OS pipeline not initialized."}), 500

    # Wait for completion synchronously up to 5 seconds for normal UI flow
    result = admission_controller.submit_registration(
        student_id=student_id,
        course_id=course_id,
        wait_for_completion=True,
        timeout=5.0
    )

    status_code = 200
    if result.get("status") == "REJECTED":
        status_code = 429  # Too Many Requests / Queue Full
    elif not result.get("success"):
        status_code = 400  # Course full or already registered

    return jsonify(result), status_code

@registration_bp.route('', methods=['GET'])
def list_registrations():
    """Admin: View all confirmed registrations."""
    with get_db_session() as session:
        registrations = session.query(Registration).order_by(Registration.registered_at.desc()).all()
        return jsonify({
            "success": True,
            "count": len(registrations),
            "registrations": [r.to_dict() for r in registrations]
        }), 200

@registration_bp.route('/student/<student_id>', methods=['GET'])
def get_student_registrations(student_id):
    """Retrieve all confirmed registrations for a student."""
    with get_db_session() as session:
        student = session.query(Student).filter(Student.student_id == student_id).first()
        if not student:
            return jsonify({"success": False, "message": f"Student '{student_id}' not found."}), 404

        registrations = session.query(Registration).filter(
            Registration.student_id == student.id,
            Registration.registration_status == 'CONFIRMED'
        ).all()

        return jsonify({
            "success": True,
            "student_id": student.student_id,
            "count": len(registrations),
            "registrations": [r.to_dict() for r in registrations]
        }), 200

@registration_bp.route('/<int:reg_id>', methods=['DELETE'])
def cancel_registration(reg_id):
    """Drop/Cancel a registration within an ACID transaction."""
    try:
        result = RegistrationService.cancel_registration(reg_id)
        return jsonify(result), 200
    except RegistrationError as re:
        return jsonify({"success": False, "code": re.code, "message": re.message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
