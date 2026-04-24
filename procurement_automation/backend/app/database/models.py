"""SQLAlchemy database models"""

# pylint: disable=not-callable

from sqlalchemy import Column, String, DateTime, Text, Integer, Enum as SQLEnum
from sqlalchemy.sql import func
import uuid
from app.database.connection import Base
from app.models.job import JobStatus


def generate_uuid():
    """Generate a UUID string"""
    return str(uuid.uuid4())


class JobModel(Base):
    """SQLAlchemy model for jobs table"""
    __tablename__ = "jobs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    status = Column(SQLEnum(JobStatus), nullable=False, default=JobStatus.PENDING)
    lang = Column(String(10), nullable=False, default="eng")
    document_type = Column(String(50), nullable=True)
    storage_type = Column(String(50), nullable=True, default="azure")  # Legacy field, optional
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Results
    result = Column(Text, nullable=True)  # JSON string
    error = Column(Text, nullable=True)
    progress = Column(Integer, nullable=True)  # 0-100
    
    def __repr__(self):
        return f"<Job(id={self.id}, filename={self.filename}, status={self.status})>"