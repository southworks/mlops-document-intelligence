"""Database setup and connection management for ModelAdmin service.

NOTE: intentional sync SQLAlchemy (not async).  The modeladmin_sidecar is a
lightweight admin service where sync I/O is sufficient.  Do not migrate to
asyncio/async sessions without a clear concurrency requirement.
"""

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings

SETTINGS = get_modeladmin_sidecar_settings()
DATABASE_URL = os.getenv("MODELADMIN_DATABASE_URL", SETTINGS.modeladmin_database_url)
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=DEBUG,
)

SESSION_LOCAL = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Session:
    db = SESSION_LOCAL()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    try:
        Base.metadata.create_all(bind=engine)
    except OperationalError as exc:
        if "already exists" in str(exc).lower():
            Base.metadata.create_all(bind=engine, checkfirst=True)
        else:
            raise

    _ensure_review_candidate_columns()


def _ensure_review_candidate_columns() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "review_candidates" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("review_candidates")}
    required_columns = {
        "low_confidence_field_names": "TEXT",
        "low_confidence_field_count": "INTEGER",
    }

    with engine.begin() as connection:
        for column_name, sql_type in required_columns.items():
            if column_name in columns:
                continue
            connection.execute(
                text(f"ALTER TABLE review_candidates ADD COLUMN {column_name} {sql_type}")
            )
