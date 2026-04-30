"""Shared document processing pipeline used by API and worker runtimes."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from azure.storage.blob import BlobServiceClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import JobModel
from app.model_registry import get_model_registry
from app.models.job import JobStatus
from app.services.confidence_gate import (
    build_candidate_payload as build_candidate_created_payload,
    compute_confidence,
    notify_modeladmin,
    resolve_active_model_id,
)
from app.services.sas_helpers_service import build_upload_blob_sas_url, is_publicly_fetchable_url
from app.services.upload_location import UploadLocation
from processing.compose_extractor import extract_with_compose, extract_with_compose_from_url, parse_compose_result
from processing.storage import (
    save_raw_adi_to_blob,
    save_to_azure_tables,
    save_parsed_compose_to_blob,
)
from processing.thumbnail import generate_thumbnail

settings = get_settings()
upload_location = UploadLocation(settings.azure_storage_container_name)
DOCUMENT_INTELLIGENCE_SAS_TTL_MINUTES = settings.document_intelligence_sas_ttl_minutes

logger = logging.getLogger(__name__)


def get_blob_client() -> BlobServiceClient:
    """Initialize Azure Blob Storage client."""
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure Storage connection string not configured")
    return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)


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


def process_document_job(
    *,
    document_id: str,
    blob_path_or_url: str,
    original_filename: str,
    db: Optional[Session] = None,
    source_channel: str = "queue-worker",
) -> dict:
    """Process one uploaded document and persist outputs."""
    try:
        blob_path = resolve_blob_path(blob_path_or_url)
        blob_client = get_blob_client()
        uploads_container = upload_location.get_container_client(blob_client)

        blob_name = upload_location.extract_blob_name(blob_path)
        if not blob_name:
            raise ValueError("Invalid blob path")

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

        file_bytes = None
        sas_url = build_upload_blob_sas_url(blob_path)

        # Step 1: Extract — call Azure Document Intelligence, get back the raw response
        if is_publicly_fetchable_url(sas_url):
            raw_adi = extract_with_compose_from_url(
                doc_intel_client,
                sas_url,
                compose_model_id,
            )
        else:
            blob_data = uploads_container.download_blob(blob_name).readall()
            file_bytes = blob_data if isinstance(blob_data, bytes) else blob_data.encode()
            raw_adi = extract_with_compose(
                doc_intel_client,
                file_bytes,
                compose_model_id,
            )

        # Step 2: Persist raw ADI response to blob storage
        raw_adi_blob_path = None
        try:
            raw_adi_blob_path = save_raw_adi_to_blob(
                blob_service_client=blob_client,
                source_blob_path=blob_path,
                raw_adi_response=raw_adi,
            )
        except Exception as raw_blob_error:
            logger.warning("Failed to save raw ADI response blob: %s", str(raw_blob_error))

        # Step 3: Parse the raw response into a structured summary
        compose_result = parse_compose_result(raw_adi)
        document_type = compose_result.get("document_type", "unknown")
        confidence = compose_result.get("confidence", 0.0)
        structured_data = compose_result.get("structured_data")

        # Persist the parsed compose result as a sidecar file next to the original blob
        parsed_compose_blob_path = None
        try:
            parsed_compose_blob_path = save_parsed_compose_to_blob(
                blob_service_client=blob_client,
                source_blob_path=blob_path,
                parsed_compose_result=compose_result,
            )
        except Exception as parsed_blob_error:
            logger.warning("Failed to save parsed compose sidecar: %s", str(parsed_blob_error))

        try:
            if file_bytes is None:
                blob_data = uploads_container.download_blob(blob_name).readall()
                file_bytes = blob_data if isinstance(blob_data, bytes) else blob_data.encode()
            thumbnail_url = generate_thumbnail(file_bytes, blob_client, original_filename, document_id)
        except Exception as thumb_error:
            logger.warning("Thumbnail generation failed: %s", str(thumb_error))
            thumbnail_url = None

        result_data = {
            "job_id": document_id,
            "original_filename": original_filename,
            "blob_path": blob_path,
            "thumbnail_url": thumbnail_url,
            "classification": {
                "document_type": document_type,
                "confidence": confidence,
            },
            "document_type": document_type,
            "classification_confidence": confidence,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "structured_data": structured_data,
        }

        # Use parsed-sidecar as the canonical processed artifact (no separate processed JSON)
        output_path = parsed_compose_blob_path or blob_path

        # Persist the projected summary into Azure Tables synchronously. Candidate triggers
        # should be evaluated against this stored projection only. If table persistence fails
        # we will log and skip candidate intake to avoid downstream races.
        table_saved = False
        try:
            save_to_azure_tables(
                settings.azure_storage_connection_string,
                document_type,
                compose_result,
                output_path,
                document_id,
                original_filename,
                raw_adi_blob_path=raw_adi_blob_path,
            )
            table_saved = True
        except Exception as table_error:
            logger.warning("Failed to save to Azure Tables: %s", str(table_error))

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
            if not table_saved:
                logger.warning(
                    "Candidate trigger detected but Azure Table persistence failed; skipping intake for %s",
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
            "thumbnail_url": thumbnail_url,
            "processed_at": result_data["processed_at"],
            "structured_data": structured_data,
            "fields_extracted": len([v for v in (structured_data or {}).values() if v]),
        }

        _sync_job_success(db, document_id, response_payload, document_type)
        return response_payload

    except Exception as exc:
        logger.exception("Document processing failed for %s", document_id)
        _sync_job_failure(db, document_id, str(exc))
        raise
