"""Queue helpers for document processing jobs."""

import json
from typing import Any, Dict

from azure.core.exceptions import ResourceExistsError
from azure.storage.queue import QueueClient

from app.config import get_settings

settings = get_settings()


class QueueMessageValidationError(ValueError):
    """Raised when queue payload is missing required fields."""


def get_queue_client() -> QueueClient:
    """Create a queue client for document processing messages."""
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure storage connection string is missing")
    if not settings.azure_storage_queue_name:
        raise ValueError("Azure storage queue name is missing")

    return QueueClient.from_connection_string(
        conn_str=settings.azure_storage_connection_string,
        queue_name=settings.azure_storage_queue_name,
    )


def ensure_queue_exists(queue_client: QueueClient) -> None:
    """Ensure queue exists before sending/receiving messages."""
    try:
        queue_client.create_queue()
    except ResourceExistsError:
        # Queue creation must be idempotent because both API and worker call this helper.
        pass


def build_document_job_message(
    *,
    document_id: str,
    blob_url: str,
    original_filename: str,
    blob_path: str,
) -> str:
    """Build serialized queue message payload for worker."""
    payload = {
        "documentId": document_id,
        "blobUrl": blob_url,
        "originalFilename": original_filename,
        "blobPath": blob_path,
    }
    return json.dumps(payload)


def enqueue_document_job(
    *,
    document_id: str,
    blob_url: str,
    original_filename: str,
    blob_path: str,
) -> None:
    """Send one processing message to Azure Queue Storage."""
    queue_client = get_queue_client()
    ensure_queue_exists(queue_client)

    message = build_document_job_message(
        document_id=document_id,
        blob_url=blob_url,
        original_filename=original_filename,
        blob_path=blob_path,
    )
    queue_client.send_message(message)


def parse_document_job_message(raw_content: str) -> Dict[str, Any]:
    """Parse and validate queue payload content."""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise QueueMessageValidationError("Queue message is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise QueueMessageValidationError("Queue message must be a JSON object")

    if not payload.get("documentId"):
        raise QueueMessageValidationError("Queue message missing documentId")
    if not payload.get("blobUrl"):
        raise QueueMessageValidationError("Queue message missing blobUrl")

    return payload
