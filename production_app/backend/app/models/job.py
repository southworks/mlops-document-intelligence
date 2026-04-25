"""Job models for tracking OCR processing status"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """Job processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobCreate(BaseModel):
    """Request model for creating a new job"""
    filename: str
    file_path: str
    lang: str = "eng"
    document_type: Optional[str] = None


class Job(BaseModel):
    """Complete job model"""
    id: str
    filename: str
    file_path: str
    status: JobStatus
    lang: str
    document_type: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[int] = None  # 0-100
    
    model_config = ConfigDict(from_attributes=True)


class JobResponse(BaseModel):
    """API response for job endpoints"""
    job_id: str
    status: JobStatus
    message: str
    created_at: datetime
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[int] = None
