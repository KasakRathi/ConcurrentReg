import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. See .env.example.")

# Pool sized for up to 60 simultaneous connections (MySQL allows 151 by default),
# so concurrent tests are not silently throttled by SQLAlchemy's default of 15.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=40)

# Every request / thread must create its own session from this factory.
SessionLocal = sessionmaker(bind=engine, autoflush=False)

Base = declarative_base()


def get_db():
    """FastAPI dependency: give one request its own session, then close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
