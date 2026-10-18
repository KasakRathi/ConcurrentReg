from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class CourseSection(Base):
    __tablename__ = "course_sections"
    __table_args__ = (
        # Safety net: the database itself refuses an impossible seat count.
        CheckConstraint(
            "available_seats >= 0 AND available_seats <= capacity",
            name="ck_seats_in_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_code: Mapped[str] = mapped_column(String(20))
    course_name: Mapped[str] = mapped_column(String(100))
    capacity: Mapped[int]
    available_seats: Mapped[int]


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        # Final protection against duplicate registration, whatever the app does.
        UniqueConstraint("student_id", "section_id", name="uq_student_section"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Refers to students.id (the numeric key), not the "STU001" text code.
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    section_id: Mapped[int] = mapped_column(ForeignKey("course_sections.id"))
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(20), default="REGISTERED")
