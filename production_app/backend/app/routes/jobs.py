"""Jobs endpoint for checking processing status"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import json

from app.database import get_db, JobModel
from app.models.job import Job, JobStatus, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the status and result of a specific job
    
    Args:
        job_id: Job ID returned from upload endpoint
        
    Returns:
        JobResponse with current status and result (if completed)
    """
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Parse result if available
    result = None
    if job.result:
        try:
            result = json.loads(job.result)
        except (json.JSONDecodeError, ValueError):
            result = {"raw": job.result}
    
    return JobResponse(
        job_id=job.id,
        status=job.status,
        message=_get_status_message(job.status),
        created_at=job.created_at,
        result=result,
        error=job.error,
        progress=job.progress
    )


@router.get("/", response_model=List[Job])
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Number of jobs to return"),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
    db: Session = Depends(get_db)
):
    """
    List all jobs with optional filtering
    
    Args:
        status: Filter by job status (pending, processing, completed, failed)
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip (pagination)
        
    Returns:
        List of Job objects
    """
    query = db.query(JobModel)
    
    if status:
        query = query.filter(JobModel.status == status)
    
    jobs = query.order_by(JobModel.created_at.desc()).offset(offset).limit(limit).all()
    
    # Convert to Pydantic models
    result = []
    for job in jobs:
        job_dict = {
            "id": job.id,
            "filename": job.filename,
            "file_path": job.file_path,
            "status": job.status,
            "lang": job.lang,
            "document_type": job.document_type,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "result": json.loads(job.result) if job.result else None,
            "error": job.error,
            "progress": job.progress
        }
        result.append(Job(**job_dict))
    
    return result


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a job and its associated data
    
    Args:
        job_id: Job ID to delete
        
    Returns:
        Success message
    """
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # TODO: Also delete file from storage
    # storage = get_storage()
    # await storage.delete(job.file_path)
    
    db.delete(job)
    db.commit()
    
    return {"message": f"Job {job_id} deleted successfully"}


def _get_status_message(status: JobStatus) -> str:
    """Get user-friendly status message"""
    messages = {
        JobStatus.PENDING: "Job is queued and waiting to be processed",
        JobStatus.PROCESSING: "Job is currently being processed",
        JobStatus.COMPLETED: "Job completed successfully",
        JobStatus.FAILED: "Job failed during processing"
    }
    return messages.get(status, "Unknown status")
