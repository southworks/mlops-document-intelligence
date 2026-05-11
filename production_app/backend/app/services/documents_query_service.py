"""Query helpers for document listing and pending-upload synthesis."""

# pylint: disable=broad-exception-caught

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import JobModel, ProcessedDocumentModel
from app.models.document_type import DocumentType, normalize_document_type_value
from app.models.job import JobStatus
from app.services.blob_parse_service import parse_document_data
from app.services.upload_location import UploadLocation


TABLE_DOCUMENT_TYPES = tuple(doc_type.value for doc_type in DocumentType)

PROCESSING_STATE_UPLOADING = "Uploading"
PROCESSING_STATE_QUEUED = "Uploaded/Queued"
PROCESSING_STATE_PROCESSING = "Processing"
PROCESSING_STATE_PENDING = "Pending Processing"
PROCESSING_STATE_PROCESSED = "Processed"
PROCESSING_STATE_UNKNOWN_FINAL = "Unknown (Final)"
PROCESSING_STATE_FAILED = "Failed"


def build_processing_state(*, status: Optional[str], document_type: str, pending_processing: bool) -> str:
    """Return a canonical processing state label for list/grid rendering."""
    status_value = (status or "").lower()
    normalized_type = normalize_document_type_value(document_type)

    if status_value == "uploading":
        return PROCESSING_STATE_UPLOADING
    if status_value in {"uploaded", "queued", "pending"}:
        return PROCESSING_STATE_QUEUED
    if status_value == "processing":
        return PROCESSING_STATE_PROCESSING
    if status_value == "failed":
        return PROCESSING_STATE_FAILED
    if pending_processing:
        return PROCESSING_STATE_PENDING
    if status_value == "completed" and normalized_type == "unknown":
        return PROCESSING_STATE_UNKNOWN_FINAL
    return PROCESSING_STATE_PROCESSED


def _to_iso_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def query_documents_from_db(db_session: Session, requested_type: str) -> List[Dict[str, Any]]:
    """Load processed document summaries from backend Postgres index."""
    settings = get_settings()
    container_prefix = f"{settings.azure_storage_container_name}/"

    query = db_session.query(ProcessedDocumentModel)
    if requested_type != "all":
        query = query.filter(ProcessedDocumentModel.document_type == requested_type)

    rows = query.order_by(ProcessedDocumentModel.processed_at.desc()).all()

    documents: List[Dict[str, Any]] = []
    for row in rows:
        blob_path = row.blob_path
        if not blob_path:
            continue

        blob_name = blob_path
        if blob_name.startswith(container_prefix):
            blob_name = blob_name[len(container_prefix):]

        try:
            projection = json.loads(row.summary_json or "{}")
        except json.JSONDecodeError:
            projection = {}

        raw_confidence = _to_float(row.classification_confidence, default=0.0)
        if raw_confidence > 1.0:
            raw_confidence = raw_confidence / 100.0

        blob_data = dict(projection)
        blob_data["document_type"] = normalize_document_type_value(
            blob_data.get("document_type") or row.document_type or requested_type
        )
        blob_data["confidence"] = _to_float(blob_data.get("confidence"), default=raw_confidence)
        blob_data["job_id"] = row.job_id
        blob_data["processed_at"] = _to_iso_datetime(row.processed_at)

        parsed = parse_document_data(
            blob_name=blob_name,
            blob_data=blob_data,
            document_type=normalize_document_type_value(row.document_type or requested_type),
        )
        parsed["pending_processing"] = False
        parsed_status = JobStatus.COMPLETED.value
        parsed["status"] = parsed_status
        parsed["processing_state"] = build_processing_state(
            status=parsed_status,
            document_type=parsed.get("document_type", "unknown"),
            pending_processing=False,
        )
        documents.append(parsed)

    return documents


def list_inflight_job_documents(db_session, requested_type: str) -> List[Dict[str, Any]]:
    """Build synthetic document summaries from non-completed job rows.

    These rows represent uploads still moving through queue/processing and eliminate
    the need for listing upload blobs in the documents UI path.
    """
    settings = get_settings()
    upload_location = UploadLocation(settings.azure_storage_container_name)

    job_rows = (
        db_session.query(JobModel)
        .filter(JobModel.status != JobStatus.COMPLETED)
        .order_by(JobModel.created_at.desc())
        .all()
    )

    results: List[Dict[str, Any]] = []
    for job in job_rows:
        normalized_type = normalize_document_type_value(job.document_type)
        if requested_type != "all":
            if requested_type == "unknown" and normalized_type != "unknown":
                continue
            if requested_type != "unknown" and normalized_type != requested_type:
                continue

        normalized_path = upload_location.normalize_path(job.file_path) or job.file_path
        created_at = _to_iso_datetime(job.created_at)
        completed_at = _to_iso_datetime(job.completed_at)
        status_value = job.status.value if hasattr(job.status, "value") else str(job.status)

        results.append(
            {
                "blob_name": normalized_path,
                "document_type": normalized_type,
                "classification_confidence": 0.0,
                "job_id": job.id,
                "processed_at": completed_at or created_at,
                "fields": {},
                "has_low_confidence": False,
                "pending_processing": status_value in {JobStatus.PENDING.value, JobStatus.PROCESSING.value},
                "status": status_value,
                "processing_state": build_processing_state(
                    status=status_value,
                    document_type=normalized_type,
                    pending_processing=status_value in {JobStatus.PENDING.value, JobStatus.PROCESSING.value},
                ),
                "raw_data": {
                    "blob_path": normalized_path,
                    "original_filename": job.filename,
                    "upload_last_modified": created_at,
                },
            }
        )

    return results


def count_pending_unknown_jobs(db_session) -> int:
    """Count inflight jobs that should render as pending unknown documents."""
    job_rows = (
        db_session.query(JobModel)
        .filter(JobModel.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
        .all()
    )

    total = 0
    for job in job_rows:
        normalized_type = normalize_document_type_value(job.document_type)
        if normalized_type == "unknown":
            total += 1
    return total


def count_documents_by_type_from_db(db_session: Session) -> Dict[str, int]:
    """Count documents by type from backend Postgres index."""
    counts = {doc_type: 0 for doc_type in TABLE_DOCUMENT_TYPES}
    for doc_type in TABLE_DOCUMENT_TYPES:
        counts[doc_type] = (
            db_session.query(ProcessedDocumentModel)
            .filter(ProcessedDocumentModel.document_type == doc_type)
            .count()
        )
    return counts


def get_processed_job_ids_from_db(db_session: Session) -> Set[str]:
    """Collect processed job IDs from backend Postgres index."""
    rows = db_session.query(ProcessedDocumentModel.job_id).all()
    return {row[0] for row in rows if row[0]}


def get_document_from_db(db_session: Session, blob_name: str) -> Optional[Dict[str, Any]]:
    """Look up a single processed document from backend Postgres index by blob path."""
    settings = get_settings()
    container_prefix = f"{settings.azure_storage_container_name}/"
    full_blob_path = (
        blob_name if blob_name.startswith(container_prefix)
        else f"{container_prefix}{blob_name}"
    )

    row = (
        db_session.query(ProcessedDocumentModel)
        .filter(ProcessedDocumentModel.blob_path == full_blob_path)
        .first()
    )
    if row is None:
        return None

    try:
        projection = json.loads(row.summary_json or "{}")
    except json.JSONDecodeError:
        projection = {}

    raw_confidence = _to_float(row.classification_confidence, default=0.0)
    if raw_confidence > 1.0:
        raw_confidence = raw_confidence / 100.0

    display_blob_name = row.blob_path
    if display_blob_name.startswith(container_prefix):
        display_blob_name = display_blob_name[len(container_prefix):]

    blob_data = dict(projection)
    blob_data["document_type"] = normalize_document_type_value(
        blob_data.get("document_type") or row.document_type or "unknown"
    )
    blob_data["confidence"] = _to_float(blob_data.get("confidence"), default=raw_confidence)
    blob_data["job_id"] = row.job_id
    blob_data["processed_at"] = _to_iso_datetime(row.processed_at)

    parsed = parse_document_data(
        blob_name=display_blob_name,
        blob_data=blob_data,
        document_type=normalize_document_type_value(row.document_type or "unknown"),
    )
    parsed["pending_processing"] = False
    parsed["status"] = JobStatus.COMPLETED.value
    parsed["processing_state"] = build_processing_state(
        status=JobStatus.COMPLETED.value,
        document_type=parsed.get("document_type", "unknown"),
        pending_processing=False,
    )
    return parsed


def count_pending_uploads_by_job_id(uploads_container_client, processed_job_ids: Set[str]) -> int:
    """Count uploads whose job_id is not present in processed job_ids index."""
    if not uploads_container_client:
        return 0

    pending = 0
    for blob in uploads_container_client.list_blobs():
        blob_name = blob.name or ""
        if not blob_name:
            continue
        if blob_name.endswith(".json"):
            continue
        upload_job_id = blob_name.split("_", 1)[0] if "_" in blob_name else blob_name
        if upload_job_id not in processed_job_ids:
            pending += 1
    return pending


def get_processed_job_ids_from_processed_blob_listing(processed_container_client) -> Set[str]:
    """Collect processed job IDs by scanning processed JSON blob names only (no downloads)."""
    if not processed_container_client:
        return set()

    processed_job_ids = set()
    for blob in processed_container_client.list_blobs():
        blob_name = blob.name or ""
        if not blob_name.endswith(".json"):
            continue
        file_name = blob_name.rsplit("/", 1)[-1]
        job_id = file_name.split("_", 1)[0] if "_" in file_name else file_name
        if job_id:
            processed_job_ids.add(job_id)
    return processed_job_ids


def build_pending_upload_documents(uploads_container_client, processed_job_ids: Set[str]) -> List[Dict[str, Any]]:
    """Build synthetic document entries for uploaded files not yet processed (by job_id)."""
    settings = get_settings()
    upload_location = UploadLocation(settings.azure_storage_container_name)

    pending_documents: List[Dict[str, Any]] = []
    if not uploads_container_client:
        return pending_documents

    for blob in uploads_container_client.list_blobs():
        blob_name = blob.name
        if not blob_name:
            continue
        if blob_name.endswith(".json"):
            continue

        upload_job_id = blob_name.split("_", 1)[0] if "_" in blob_name else blob_name
        if upload_job_id in processed_job_ids:
            continue

        upload_blob_path = upload_location.normalize_path(blob_name)

        original_filename = Path(blob_name).name
        pending_documents.append(
            {
                "blob_name": upload_blob_path,
                "document_type": "unknown",
                "classification_confidence": 0.0,
                "job_id": upload_job_id,
                "processed_at": blob.last_modified.isoformat() if getattr(blob, "last_modified", None) else None,
                "vendor": {"name": None, "address": None},
                "customer": {"name": None, "address": None},
                "financial": {
                    "subtotal": None,
                    "total_tax": None,
                    "invoice_total": None,
                    "amount_due": None,
                },
                "items": [],
                "confidence": {},
                "has_low_confidence": False,
                "pending_processing": True,
                "raw_data": {
                    "blob_path": upload_blob_path,
                    "original_filename": original_filename,
                    "upload_last_modified": blob.last_modified.isoformat() if getattr(blob, "last_modified", None) else None,
                },
            }
        )

    return pending_documents