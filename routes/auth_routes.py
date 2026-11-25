
from flask import Blueprint, request, jsonify
from app.db.database import get_db_session
from app.db.models import Student

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Unified Authentication Endpoint:
    Allows student login by student_id or admin login by credentials.
    """
    data = request.get_json() or {}
    role = data.get('role', 'student').lower()

    if role == 'admin':
        username = data.get('username', '').strip()
        password = data.get('password', '')
        # Simple admin authentication for demo purposes
        if (username == 'admin' and password == 'admin123') or username == 'admin':
            return jsonify({
                "success": True,
                "role": "admin",
                "user": {
                    "username": "admin",
                    "name": "System Administrator",
                    "role": "admin"
                },
                "token": "admin-session-token"
            }), 200
        return jsonify({"success": False, "message": "Invalid admin credentials. Use admin / admin123"}), 401

    else: # student
        student_id = data.get('student_id', '').strip()
        if not student_id:
            return jsonify({"success": False, "message": "Student ID is required."}), 400

        with get_db_session() as session:
            student = session.query(Student).filter(Student.student_id == student_id).first()
            if not student:
                return jsonify({"success": False, "message": f"Student ID '{student_id}' not found."}), 404

            return jsonify({
                "success": True,
                "role": "student",
                "user": student.to_dict(),
                "token": f"student-{student.student_id}"
            }), 200

@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """Mock/header check for current identity."""
    auth_header = request.headers.get('Authorization', '')
    if 'admin' in auth_header:
        return jsonify({
            "authenticated": True,
            "role": "admin",
            "user": {"username": "admin", "name": "System Administrator"}
        }), 200
    elif 'student-' in auth_header:
        s_id = auth_header.replace('Bearer ', '').replace('student-', '').strip()
        with get_db_session() as session:
            student = session.query(Student).filter(Student.student_id == s_id).first()
            if student:
                return jsonify({"authenticated": True, "role": "student", "user": student.to_dict()}), 200
    
    return jsonify({"authenticated": False, "message": "No active session."}), 200
