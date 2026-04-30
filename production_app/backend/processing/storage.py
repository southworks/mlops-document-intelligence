"""
Storage Module
Handles saving processed documents to Azure Blob Storage and Azure Tables
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional
from azure.data.tables import TableServiceClient

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

def save_to_azure_tables(
    storage_connection: str,
    document_type: str,
    mapped_projection: dict,
    blob_path: str,
    job_id: str,
    original_filename: str,
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

        # Upsert entity
        table_client.upsert_entity(entity)

        logger.info("   ✓ Saved to Azure Tables: %s/%s", partition_key, job_id)
        
    except Exception as e:
        # Don't fail the entire function if table save fails
        logger.warning("⚠️ Failed to save to Azure Tables (non-critical): %s", str(e))
        logger.warning("   Document JSON was still saved to blob storage")
