"""
Storage Module
Handles saving processed documents to Azure Blob Storage and Azure Tables
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceExistsError

from app.config import get_settings
from app.models.document_type import normalize_document_type_value

logger = logging.getLogger(__name__)

ALLOWED_CANDIDATE_TRIGGER_FOLDERS = {
    "unknown_classification",
    "low_confidence",
    "low_field_confidence",
}


def resolve_candidate_destination_folder(trigger_reason: Optional[str]) -> Optional[str]:
    """Return explicit folder override for candidate-triggered documents.

    Returns None when the trigger does not map to a candidate-specific folder.
    """
    if not trigger_reason:
        return None
    return trigger_reason if trigger_reason in ALLOWED_CANDIDATE_TRIGGER_FOLDERS else None


def get_documents_container_name() -> str:
    """Return configured documents container name with safe fallback."""
    settings = get_settings()
    return settings.azure_storage_container_name or "documents"


def serialize_json_payload(payload: Optional[dict], *, pretty: bool = False) -> str:
    """Serialize JSON payload using one shared implementation."""
    if pretty:
        return json.dumps(payload or {}, indent=2, default=str, sort_keys=True)
    return json.dumps(payload or {}, default=str, sort_keys=True)

# NOTE: `save_result_to_blob` previously wrote a separate processed JSON artifact.
# The pipeline now treats the parsed compose sidecar (created by
# `save_parsed_compose_to_blob`) as the canonical processed artifact. The
# historical `save_result_to_blob` function has been removed to avoid
# duplicating data and simplify the processing flow.


def save_raw_adi_to_blob(
    blob_service_client: BlobServiceClient,
    source_blob_path: str,
    raw_adi_response: Optional[dict],
) -> str:
    """Save raw ADI response next to source blob using same base filename and .json extension."""
    container_name = get_documents_container_name()

    if not source_blob_path:
        raise ValueError("source_blob_path is required")

    blob_name = source_blob_path
    prefix = f"{container_name}/"
    if blob_name.startswith(prefix):
        blob_name = blob_name[len(prefix):]

    raw_blob_name = f"{blob_name}.json"

    try:
        try:
            blob_service_client.create_container(container_name)
        except ResourceExistsError:
            pass

        payload = serialize_json_payload(raw_adi_response, pretty=True)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=raw_blob_name)
        blob_client.upload_blob(payload, overwrite=True)
        return f"{container_name}/{raw_blob_name}"
    except Exception as e:
        logger.error("❌ Failed to save raw ADI blob: %s", str(e))
        raise


def save_parsed_compose_to_blob(
    blob_service_client: BlobServiceClient,
    source_blob_path: str,
    parsed_compose_result: Optional[dict],
) -> str:
    """Save the parsed compose result as a sidecar JSON next to the source blob.

    Example: source 'documents/invoices/job_123_invoice.pdf' -> 'documents/invoices/job_123_invoice_parsed.json'
    Returns the full blob path (container/blob).
    """
    container_name = get_documents_container_name()

    if not source_blob_path:
        raise ValueError("source_blob_path is required")

    blob_name = source_blob_path
    prefix = f"{container_name}/"
    if blob_name.startswith(prefix):
        blob_name = blob_name[len(prefix):]

    # Place the parsed sidecar next to the original file, removing the original extension
    if "/" in blob_name:
        dir_part, file_name = blob_name.rsplit("/", 1)
        stem = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
        parsed_blob_name = f"{dir_part}/{stem}_parsed.json"
    else:
        file_name = blob_name
        stem = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
        parsed_blob_name = f"{stem}_parsed.json"

    try:
        try:
            blob_service_client.create_container(container_name)
        except ResourceExistsError:
            pass

        payload = serialize_json_payload(parsed_compose_result, pretty=True)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=parsed_blob_name)
        blob_client.upload_blob(payload, overwrite=True)
        logger.info("   ✓ Saved parsed compose sidecar: %s/%s", container_name, parsed_blob_name)
        return f"{container_name}/{parsed_blob_name}"
    except Exception as e:
        logger.error("❌ Failed to save parsed compose blob: %s", str(e))
        raise

def save_to_azure_tables(
    storage_connection: str,
    document_type: str,
    mapped_projection: dict,
    blob_path: str,
    job_id: str,
    original_filename: str,
    raw_adi_blob_path: Optional[str] = None,
):
    """
    Save document data to Azure Tables for matching
    Creates entities with proper PartitionKey based on document type
    
    Args:
        storage_connection: Azure Storage connection string
        document_type: Document classification
        mapped_projection: Full parsed projection payload
        blob_path: Path to saved JSON blob
        job_id: Job identifier
        original_filename: Original uploaded filename
    """
    try:
        document_type = normalize_document_type_value(document_type)
        # Initialize table service
        table_service = TableServiceClient.from_connection_string(storage_connection)
        table_name = "Documents"
        
        # Create table if it doesn't exist
        try:
            table_client = table_service.create_table_if_not_exists(table_name)
            if not table_client:
                table_client = table_service.get_table_client(table_name)
        except Exception as e:
            logger.warning("Table creation warning: %s", str(e))
            table_client = table_service.get_table_client(table_name)
        
        # Keep PartitionKey aligned with canonical DocumentType values.
        partition_key = document_type
        logger.info("Using partition key: %s for document of type: %s", partition_key, document_type)
        
        # Prepare entity
        entity = {
            "PartitionKey": partition_key,
            "RowKey": blob_path.replace('documents/', '').replace('processed-documents/', '').replace('/', '_'),
            "Timestamp": datetime.now(timezone.utc),
            "document_type": document_type,
            "blob_path": blob_path,
            "job_id": job_id,
            "original_filename": original_filename,
            "classification_confidence": (mapped_projection or {}).get("confidence", 0.0),
        }
        
        # Add full summary as JSON and preserve raw ADI blob reference for debugging.
        entity["summary_json"] = serialize_json_payload(mapped_projection)
        entity["raw_adi_blob_path"] = raw_adi_blob_path or ""
        
        # Upsert entity
        table_client.upsert_entity(entity)

        logger.info("   ✓ Saved to Azure Tables: %s/%s", partition_key, job_id)
        
    except Exception as e:
        # Don't fail the entire function if table save fails
        logger.warning("⚠️ Failed to save to Azure Tables (non-critical): %s", str(e))
        logger.warning("   Document JSON was still saved to blob storage")
