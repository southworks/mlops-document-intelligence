"""Unified document management endpoints for invoices, purchase orders, and unknown documents"""

# pylint: disable=broad-exception-caught

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.services.upload_location import UploadLocation
from app.services.document_processor import process_document_job
from app.services.storage_clients_service import (
    get_blob_client,
    get_container_client_safe,
    get_documents_table_client,
)
from app.services.documents_query_service import (
    count_pending_unknown_jobs,
    count_documents_by_type_from_table,
    list_inflight_job_documents,
    query_documents_from_table,
)
from app.services.blob_parse_service import (
    get_document_type,
    parse_document_data,
    _load_documents_from_container,
)
from app.services.sas_helpers_service import build_read_sas_url_for_blob_path
from app.database import get_db
from app.database.connection import SessionLocal
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

        # TABLE-ONLY MODE: List rendering uses persisted table data + inflight jobs only.
        # Blob fallback has been removed to ensure consistent, fast list performance.
        table_client = get_documents_table_client()
        table_documents = query_documents_from_table(table_client, normalized_type)
        documents = table_documents or []

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


async def _compute_document_stats() -> Dict[str, Any]:
    """Compute fast document stats (count-only)."""
    blob_client = get_blob_client()
    container_client = get_container_client_safe(blob_client, DOCUMENTS_CONTAINER_NAME)
    table_client = get_documents_table_client()

    stats = {
        "invoice": {"total": 0},
        "purchase-order": {"total": 0},
        "goods-receipt-note": {"total": 0},
        "unknown": {"total": 0}
    }

    table_counts = count_documents_by_type_from_table(table_client)
    if table_counts is not None:
        for doc_type, count in table_counts.items():
            stats[doc_type]["total"] = count
    elif container_client:
        parsed_docs = await _load_documents_from_container(container_client, "all")
        for doc in parsed_docs:
            doc_type = doc.get("document_type", "unknown")
            if doc_type not in stats:
                doc_type = "unknown"
            stats[doc_type]["total"] += 1

    pending_uploads = 0
    try:
        with SessionLocal() as db_session:
            pending_uploads = count_pending_unknown_jobs(db_session)
    except SQLAlchemyError:
        pending_uploads = 0

    stats["unknown"]["pending_processing"] = pending_uploads
    stats["unknown"]["total"] += pending_uploads

    total_documents = sum(s["total"] for s in stats.values())
    return {
        "total_documents": total_documents,
        "pending_uploads": pending_uploads,
        "by_type": stats,
    }


@router.get("/stats")
async def get_document_stats():
    """Get fast document stats (count-focused)."""
    try:
        return await _compute_document_stats()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting stats: {str(e)}"
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
    
    Process one document immediately using the same pipeline used by the queue worker.

    This endpoint is retained for manual processing/debug scenarios and handles:
    1. Document classification (invoice vs purchase-order vs goods-receipt-note)
    2. Structured field extraction
    3. Thumbnail generation
    4. Results saved to documents container
    5. Metadata saved to Azure Tables
    
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
        - thumbnail_url
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
async def get_document(blob_name: str):
    """
    Get detailed document data by blob name (with folder path)
    
    Args:
        blob_name: Full path of blob in documents container (e.g., "invoices/abc123.json")
        
    Returns:
        Detailed document data with all fields and confidence scores
    """
    try:
        # Use DocumentRepository for local/azure abstraction
        from app.repositories.document_repository import DocumentRepository
        repo = DocumentRepository()
        
        doc = await repo.get_document_by_blob_name(blob_name)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document not found: {blob_name}")
        
        doc_type = get_document_type(blob_name)
        parsed_doc = parse_document_data(blob_name, doc, doc_type)
        return parsed_doc
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
        blob_path: Full path to blob (e.g., "documents/file.pdf" or "thumbnails/thumb.jpg")
        
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


