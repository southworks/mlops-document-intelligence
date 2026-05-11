"""Unified document management endpoints for invoices, purchase orders, and unknown documents"""

# pylint: disable=broad-exception-caught

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from typing import List, Dict
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.upload_location import UploadLocation
from app.services.document_processor import process_document_job
from app.services.documents_query_service import (
    get_document_from_db,
    list_inflight_job_documents,
    query_documents_from_db,
)
from app.services.sas_helpers_service import build_read_sas_url_for_blob_path
from app.database import get_db
from app.models.document_type import DocumentType, normalize_document_type_value

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
upload_location = UploadLocation(settings.azure_storage_container_name)
DOCUMENTS_CONTAINER_NAME = settings.azure_storage_container_name

DOCUMENT_TYPE_FILTERS = {doc_type.value for doc_type in DocumentType}
DOCUMENT_TYPE_FILTERS.add("all")


@router.get("", response_model=List[Dict], include_in_schema=False)
@router.get("/", response_model=List[Dict])
async def list_documents(
    document_type: str = Query("all", alias="type", description="Filter by document type"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    List documents from the configured documents container/folder with optional type filtering
    
    Works with both local and Azure storage
    
    Args:
        document_type: Filter by document type (invoice, purchase-order, unknown, or all)
        page: Page number for pagination
        limit: Number of items per page
        
    Returns:
        List of document summaries with confidence indicators
    """
    try:
        requested_type = (document_type or "all").strip().lower()
        if requested_type not in DOCUMENT_TYPE_FILTERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid document type filter '{document_type}'. Allowed: {sorted(DOCUMENT_TYPE_FILTERS)}",
            )

        normalized_type = "all" if requested_type == "all" else normalize_document_type_value(requested_type)

        # DB-INDEX MODE: List rendering uses persisted Postgres index rows + inflight jobs.
        documents = query_documents_from_db(db, normalized_type)

        # Merge inflight job documents (uploads still processing) with completed table records
        documents.extend(list_inflight_job_documents(db, normalized_type))
        
        # Sort by date descending (most recent first)
        documents.sort(
            key=lambda x: x.get('invoice_date') or x.get('po_date') or x.get('receipt_date') or x.get('processed_at') or '',
            reverse=True
        )
        
        # Apply pagination
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        return documents[start_idx:end_idx]
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing documents: {str(e)}"
        ) from e


@router.post("/process-new")
async def process_new_document(
    blob_path: str = Body(...),
    job_id: str = Body(...),
    original_filename: str = Body(...),
    db: Session = Depends(get_db),
):
    """
    Process a newly uploaded document for initial classification and field extraction.
    
    Process one document immediately using the same pipeline used by background processing.

    This endpoint is retained for manual processing/debug scenarios and handles:
    1. Document classification (invoice vs purchase-order vs goods-receipt-note)
    2. Structured field extraction
    3. Results saved to documents container
    4. Metadata indexed in backend Postgres
    
    Args:
        blob_path: Path to blob in documents container (e.g., "documents/job_id_timestamp_file.pdf")
        job_id: Unique job identifier for tracking
        original_filename: Original filename for reference
        
    Returns:
        Dict with processed document metadata including:
        - job_id
        - document_type (invoice, purchase-order, goods-receipt-note, unknown)
        - classification_confidence
        - structured_data (extracted fields)
        - output_path (where JSON was saved)
    """
    try:
        return process_document_job(
            document_id=job_id,
            blob_path_or_url=blob_path,
            original_filename=original_filename,
            db=db,
            source_channel="process-new-api",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing document: {str(e)}"
        ) from e


@router.get("/{blob_name:path}")
async def get_document(blob_name: str, db: Session = Depends(get_db)):
    """
    Get detailed document data by blob name (with folder path)

    Args:
        blob_name: Full path of blob (e.g., "documents/abc123.pdf")

    Returns:
        Detailed document data with all fields and confidence scores
    """
    try:
        doc = get_document_from_db(db, blob_name)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document not found: {blob_name}")
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {str(e)}"
        ) from e


@router.post("/generate-sas-url")
async def generate_sas_url(blob_path: str = Body(..., embed=True)):
    """
    Generate SAS URL for secure blob access
    
    Args:
        blob_path: Full path to blob (e.g., "documents/file.pdf")
        
    Returns:
        Secure URL with SAS token (expires in 1 hour)
    """
    if not settings.azure_storage_connection_string:
        raise HTTPException(
            status_code=500,
            detail="Azure Storage account credentials not configured"
        )
    
    try:
        url = build_read_sas_url_for_blob_path(blob_path, ttl_minutes=60)
        return {
            "url": url,
            "expires_in_seconds": 3600
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating SAS URL: {str(e)}"
        ) from e


