"""DEVELOPMENT / TEST DATA ONLY. These students and courses are made up."""
from app import models
from app.database import Base, SessionLocal, engine


def seed_dev_data(db):
    for number in range(1, 11):
        db.add(models.Student(student_id=f"STU{number:03d}", name=f"Test Student {number}"))

    db.add(models.CourseSection(
        course_code="CSE301", course_name="Operating Systems (test data)",
        capacity=5, available_seats=5,
    ))
    db.add(models.CourseSection(
        course_code="CSE302", course_name="Database Systems (test data)",
        capacity=2, available_seats=2,
    ))
    db.commit()


def reset_and_seed():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        seed_dev_data(db)
    finally:
        db.close()


if __name__ == "__main__":
    reset_and_seed()
    print("Database reset and seeded with development data.")
