from flask import Blueprint, request, jsonify
from app.db.database import get_db_session
from app.db.models import Course, Registration

course_bp = Blueprint('courses', __name__, url_prefix='/api/courses')

@course_bp.route('', methods=['GET'])
def list_courses():
    """List all courses with seat availability and filtering."""
    search = request.args.get('search', '').strip().lower()
    department = request.args.get('department', '').strip()

    with get_db_session() as session:
        query = session.query(Course)
        if department:
            query = query.filter(Course.department == department)

        courses = query.all()
        result = []
        for c in courses:
            if search and (search not in c.course_code.lower() and search not in c.course_name.lower()):
                continue
            result.append(c.to_dict())

        return jsonify({
            "success": True,
            "count": len(result),
            "courses": result
        }), 200

@course_bp.route('/<int:course_id>', methods=['GET'])
def get_course(course_id):
    """Retrieve detailed course information and currently enrolled students."""
    with get_db_session() as session:
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return jsonify({"success": False, "message": f"Course ID {course_id} not found."}), 404

        registrations = session.query(Registration).filter(
            Registration.course_id == course.id,
            Registration.registration_status == 'CONFIRMED'
        ).all()

        return jsonify({
            "success": True,
            "course": course.to_dict(),
            "enrolled_students": [r.to_dict() for r in registrations]
        }), 200

@course_bp.route('', methods=['POST'])
def create_course():
    """Admin: Add a new course."""
    data = request.get_json() or {}
    course_code = data.get('course_code', '').strip().upper()
    course_name = data.get('course_name', '').strip()
    department = data.get('department', '').strip()
    instructor = data.get('instructor', '').strip()
    credits = int(data.get('credits', 3))
    capacity = int(data.get('capacity', 30))
    semester = int(data.get('semester', 5))
    description = data.get('description', '')

    if not course_code or not course_name or not department or not instructor:
        return jsonify({"success": False, "message": "All required fields must be supplied."}), 400

    with get_db_session() as session:
        existing = session.query(Course).filter(Course.course_code == course_code).first()
        if existing:
            return jsonify({"success": False, "message": f"Course code '{course_code}' already exists."}), 409

        new_course = Course(
            course_code=course_code,
            course_name=course_name,
            department=department,
            instructor=instructor,
            credits=credits,
            capacity=capacity,
            enrolled_count=0,
            semester=semester,
            description=description
        )
        session.add(new_course)
        session.commit()
        return jsonify({"success": True, "course": new_course.to_dict()}), 201

@course_bp.route('/<int:course_id>', methods=['PUT'])
def update_course(course_id):
    """Admin: Update an existing course."""
    data = request.get_json() or {}
    with get_db_session() as session:
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return jsonify({"success": False, "message": f"Course ID {course_id} not found."}), 404

        if 'course_name' in data:
            course.course_name = data['course_name'].strip()
        if 'instructor' in data:
            course.instructor = data['instructor'].strip()
        if 'department' in data:
            course.department = data['department'].strip()
        if 'credits' in data:
            course.credits = int(data['credits'])
        if 'capacity' in data:
            new_cap = int(data['capacity'])
            if new_cap < course.enrolled_count:
                return jsonify({
                    "success": False,
                    "message": f"Capacity ({new_cap}) cannot be less than currently enrolled students ({course.enrolled_count})."
                }), 400
            course.capacity = new_cap
        if 'description' in data:
            course.description = data['description']

        session.commit()
        return jsonify({"success": True, "course": course.to_dict()}), 200

@course_bp.route('/<int:course_id>', methods=['DELETE'])
def delete_course(course_id):
    """Admin: Delete a course."""
    with get_db_session() as session:
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return jsonify({"success": False, "message": f"Course ID {course_id} not found."}), 404

        session.delete(course)
        session.commit()
        return jsonify({"success": True, "message": f"Course '{course.course_code}' deleted."}), 200
