"""Upload endpoint for receiving invoice files"""

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, HTTPException, Query, Depends
from datetime import datetime, timezone
import uuid

from app.storage import get_storage
from app.config import get_settings
from app.database import get_db, JobModel
from app.models.job import JobStatus
from app.services.document_processor import process_document_job
from app.services.upload_location import UploadLocation
from sqlalchemy.orm import Session

router = APIRouter(prefix="/upload", tags=["upload"])
settings = get_settings()
upload_location = UploadLocation(settings.azure_storage_container_name)

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'}


def validate_file_type(filename: str) -> bool:
    """Validate file extension"""
    return any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)


@router.post("/")
async def upload_invoice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    lang: str = Query("eng", description="Language for OCR (eng, spa, etc.)"),
    document_type: str = Query(None, description="Type of document (invoice, receipt, etc.)"),
    db: Session = Depends(get_db)
):
    """
    Upload a document and schedule it for background processing.

    Args:
        file: Document file (PDF or image)
        lang: OCR language code (for future use)
        document_type: Optional - will be auto-detected by classifier

    Returns:
        JSON with job_id, filename, and file_path
    """
    
    # Validate file type
    if not validate_file_type(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    try:
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Generate unique filename with job_id prefix for queue worker correlation
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{job_id}_{timestamp}_{file.filename}"
        
        # Get storage adapter
        storage = get_storage()
        
        # Upload file directly to container root (no subfolder needed)
        file_path = await storage.upload(
            file.file,
            unique_filename,
            folder=None
        )

        blob_path = upload_location.normalize_path(file_path)
        if not blob_path:
            raise ValueError("Could not resolve blob path for uploaded file")

        blob_url = upload_location.build_read_sas_url(
            blob_path=blob_path,
            account_name=None,
            account_key=None,
            ttl_minutes=settings.document_intelligence_sas_ttl_minutes,
            connection_string=settings.azure_storage_connection_string,
        )
        
        # ✅ CREATE DATABASE RECORD
        job = JobModel(
            id=job_id,
            filename=file.filename,
            file_path=file_path,
            status=JobStatus.PENDING,
            lang=lang,
            document_type=document_type
        )
        db.add(job)
        db.commit()

        job.status = JobStatus.PROCESSING
        db.commit()

        background_tasks.add_task(
            process_document_job,
            document_id=job_id,
            blob_path_or_url=blob_path,
            original_filename=file.filename,
            db=None,
            source_channel="background-task",
        )

        message = "File uploaded and scheduled for background processing."

        return {
            "job_id": job_id,
            "filename": file.filename,
            "file_path": file_path,
            "blob_name": unique_filename,
            "blob_url": blob_url,
            "status": "processing",
            "message": message
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error uploading file: {str(e)}"
        ) from e
