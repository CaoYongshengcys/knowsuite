"""SQLite via SQLAlchemy 2.x."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import SQLALCHEMY_URL

engine = create_engine(SQLALCHEMY_URL, connect_args={"check_same_thread": False}, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import models  # noqa: F401  ensure tables registered
    Base.metadata.create_all(bind=engine)
