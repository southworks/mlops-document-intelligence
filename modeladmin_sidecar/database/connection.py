"""Database setup and connection management for ModelAdmin service.

NOTE: intentional sync SQLAlchemy (not async).  The modeladmin_sidecar is a
lightweight admin service where sync I/O is sufficient.  Do not migrate to
asyncio/async sessions without a clear concurrency requirement.
"""

import os

from sqlalchemy import create_engine
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
    Base.metadata.create_all(bind=engine)
