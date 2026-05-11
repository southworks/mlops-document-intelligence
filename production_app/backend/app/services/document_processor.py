"""Shared document processing pipeline used by API and worker runtimes."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import JobModel, ProcessedDocumentModel
from app.database.connection import SessionLocal
from app.model_registry import get_model_registry
from app.models.job import JobStatus
from app.services.confidence_gate import (
    build_candidate_payload as build_candidate_created_payload,
    compute_confidence,
    notify_modeladmin,
    resolve_active_model_id,
)
from app.services.sas_helpers_service import build_upload_blob_sas_url
from app.services.upload_location import UploadLocation
from processing.compose_extractor import extract_with_compose_from_url, parse_compose_result
settings = get_settings()
upload_location = UploadLocation(settings.azure_storage_container_name)
DOCUMENT_INTELLIGENCE_SAS_TTL_MINUTES = settings.document_intelligence_sas_ttl_minutes

logger = logging.getLogger(__name__)


def resolve_blob_path(blob_path_or_url: str) -> str:
    """Normalize a blob path from either canonical path or URL input."""
    if not blob_path_or_url:
        raise ValueError("blob path or URL is required")

    if blob_path_or_url.startswith("http://") or blob_path_or_url.startswith("https://"):
        parsed = urlparse(blob_path_or_url)
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) < 2:
            raise ValueError("Invalid blobUrl path")
        container_name = path_parts[0]
        blob_name = "/".join(path_parts[1:])
        return f"{container_name}/{blob_name}"

    return upload_location.normalize_path(blob_path_or_url) or blob_path_or_url


def _sync_job_success(db: Optional[Session], job_id: str, payload: dict, document_type: str) -> None:
    if db is None:
        return

    try:
        job = db.query(JobModel).filter(JobModel.id == job_id).first()
        if not job:
            return
        job.status = JobStatus.COMPLETED
        job.document_type = document_type
        job.result = json.dumps(payload)
        job.error = None
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except SQLAlchemyError as db_sync_error:
        db.rollback()
        logger.warning("Jobs success sync skipped: %s", str(db_sync_error))


def _sync_job_failure(db: Optional[Session], job_id: str, error_message: str) -> None:
    if db is None:
        return

    try:
        job = db.query(JobModel).filter(JobModel.id == job_id).first()
        if not job:
            return
        job.status = JobStatus.FAILED
        job.error = error_message
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except SQLAlchemyError as db_sync_error:
        db.rollback()
        logger.warning("Jobs failure sync skipped: %s", str(db_sync_error))


def _upsert_processed_document(
    db: Session,
    *,
    blob_path: str,
    document_type: str,
    compose_result: dict,
    job_id: str,
    original_filename: str,
) -> None:
    """Persist or update processed document projection in backend Postgres index."""
    confidence = compose_result.get("confidence", 0.0)
    row = db.query(ProcessedDocumentModel).filter(ProcessedDocumentModel.blob_path == blob_path).first()

    if row is None:
        row = ProcessedDocumentModel(
            blob_path=blob_path,
            document_type=document_type,
            job_id=job_id,
            original_filename=original_filename,
            classification_confidence=float(confidence or 0.0),
            summary_json=json.dumps(compose_result or {}, default=str, sort_keys=True),
            processed_at=datetime.now(timezone.utc),
        )
        db.add(row)
    else:
        row.document_type = document_type
        row.job_id = job_id
        row.original_filename = original_filename
        row.classification_confidence = float(confidence or 0.0)
        row.summary_json = json.dumps(compose_result or {}, default=str, sort_keys=True)
        row.processed_at = datetime.now(timezone.utc)

    db.commit()


def process_document_job(
    *,
    document_id: str,
    blob_path_or_url: str,
    original_filename: str,
    db: Optional[Session] = None,
    source_channel: str = "background-task",
) -> dict:
    """Process one uploaded document and persist outputs."""
    owns_session = False
    active_db = db

    if active_db is None:
        active_db = SessionLocal()
        owns_session = True

    try:
        blob_path = resolve_blob_path(blob_path_or_url)

        if not settings.azure_document_intelligence_endpoint or not settings.azure_document_intelligence_key:
            raise ValueError("Azure Document Intelligence credentials not configured")

        # Lazy import Azure Document Intelligence client to avoid import-time failures
        # in test environments where the sdk package is not installed.
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential
        except Exception:
            logger.warning(
                "Azure Document Intelligence SDK not available; proceeding without it (tests may mock extractors)."
            )
            DocumentIntelligenceClient = None
            AzureKeyCredential = None

        # Respect configured API version when creating the client (passed to constructor)
        api_version = getattr(settings, "azure_document_intelligence_api_version", None)
        client_kwargs = {}
        if api_version:
            client_kwargs["api_version"] = api_version

        if DocumentIntelligenceClient:
            doc_intel_client = DocumentIntelligenceClient(
                endpoint=settings.azure_document_intelligence_endpoint,
                credential=AzureKeyCredential(settings.azure_document_intelligence_key),
                **client_kwargs,
            )
        else:
            doc_intel_client = None

        registry = get_model_registry()
        compose_model_id = (
            resolve_active_model_id(settings_override=settings)
            or registry.get_active_model_id("compose")
            or settings.azure_compose_model_id
        )
        if not compose_model_id:
            raise ValueError("Azure Compose Model ID not configured")

        sas_url = build_upload_blob_sas_url(blob_path)

        # Step 1: Extract — call Azure Document Intelligence, get back the raw response
        raw_adi = extract_with_compose_from_url(
            doc_intel_client,
            sas_url,
            compose_model_id,
        )

        # Step 2: Parse the raw response into a structured summary
        compose_result = parse_compose_result(raw_adi)
        document_type = compose_result.get("document_type", "unknown")
        confidence = compose_result.get("confidence", 0.0)
        structured_data = compose_result.get("structured_data")

        result_data = {
            "job_id": document_id,
            "original_filename": original_filename,
            "blob_path": blob_path,
            "classification": {
                "document_type": document_type,
                "confidence": confidence,
            },
            "document_type": document_type,
            "classification_confidence": confidence,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "structured_data": structured_data,
        }

        output_path = blob_path

        # Persist the projected summary into backend Postgres synchronously. Candidate triggers
        # are evaluated only after persistence succeeds to keep list/detail/index consistency.
        index_saved = False
        try:
            _upsert_processed_document(
                active_db,
                blob_path=output_path,
                document_type=document_type,
                compose_result=compose_result,
                job_id=document_id,
                original_filename=original_filename,
            )
            index_saved = True
        except Exception as index_error:
            logger.warning("Failed to save processed document index row: %s", str(index_error))

        # Evaluate candidate triggers using the projected summary only (structured_data).
        score = compute_confidence(
            document_type=document_type,
            classification_confidence=confidence,
            structured_data=structured_data,
        )
        should_create_candidate = score.should_notify
        trigger_reason = score.trigger_reason
        has_low_confidence = score.has_low_confidence

        if should_create_candidate and trigger_reason:
            if not index_saved:
                logger.warning(
                    "Candidate trigger detected but processed document index persistence failed; skipping intake for %s",
                    document_id,
                )
            else:
                try:
                    intake_payload = build_candidate_created_payload(
                        document_id=document_id,
                        blob_path=blob_path,
                        processed_blob_path=output_path,
                        document_type=document_type,
                        classification_confidence=confidence,
                        compose_model_id=compose_model_id,
                        source_channel=source_channel,
                        trigger_reason=trigger_reason,
                        has_low_confidence=has_low_confidence,
                        original_filename=original_filename,
                        error_details=compose_result.get("error"),
                        structured_data=structured_data,
                    )
                    notify_modeladmin(intake_payload)
                except Exception as intake_error:
                    logger.warning("ModelAdmin candidate intake failed: %s", str(intake_error))

        response_payload = {
            "success": True,
            "job_id": document_id,
            "document_type": document_type,
            "classification_confidence": confidence,
            "output_path": output_path,
            "processed_at": result_data["processed_at"],
            "structured_data": structured_data,
            "fields_extracted": len([v for v in (structured_data or {}).values() if v]),
        }

        _sync_job_success(active_db, document_id, response_payload, document_type)
        return response_payload

    except Exception as exc:
        logger.exception("Document processing failed for %s", document_id)
        _sync_job_failure(active_db, document_id, str(exc))
        raise
    finally:
        if owns_session and active_db is not None:
            active_db.close()
