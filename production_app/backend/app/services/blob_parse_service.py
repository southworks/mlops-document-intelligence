"""Blob parsing helpers for document read/list endpoints."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.models.document_type import DocumentType, normalize_document_type_value


DocumentTypeFilter = str
MAX_PARALLEL_BLOB_DOWNLOADS = 12


def _normalize_confidence_percent(confidence: Any) -> Optional[float]:
    if confidence is None:
        return None

    try:
        normalized = float(confidence)
    except (TypeError, ValueError):
        return None

    if normalized <= 1.0:
        normalized *= 100

    return round(normalized, 2)


def _normalize_structured_field(field: Any, threshold_percent: float) -> Any:
    if isinstance(field, list):
        return [_normalize_structured_field(item, threshold_percent) for item in field]

    if not isinstance(field, dict):
        return field

    normalized = {
        key: _normalize_structured_field(value, threshold_percent)
        for key, value in field.items()
    }

    if "value" in normalized or "confidence" in normalized:
        confidence = _normalize_confidence_percent(normalized.get("confidence"))
        normalized["confidence"] = confidence
        normalized["has_low_confidence"] = confidence is not None and confidence < threshold_percent

    return normalized


def _any_low_confidence_field(field: Any) -> bool:
    if isinstance(field, list):
        return any(_any_low_confidence_field(item) for item in field)

    if isinstance(field, dict):
        if field.get("has_low_confidence") is True:
            return True
        return any(_any_low_confidence_field(value) for value in field.values())

    return False


def get_document_type(blob_name: str) -> str:
    if blob_name.startswith("invoices/"):
        doc_type = DocumentType.INVOICE.value
    elif blob_name.startswith("purchase-orders/"):
        doc_type = DocumentType.PURCHASE_ORDER.value
    elif blob_name.startswith("goods-receipt-notes/"):
        doc_type = DocumentType.GOODS_RECEIPT_NOTE.value
    else:
        doc_type = DocumentType.UNKNOWN.value
    return normalize_document_type_value(doc_type)


def parse_document_data(blob_name: str, blob_data: dict, document_type: str) -> dict:
    """Parse document data from blob storage JSON format."""
    try:
        settings = get_settings()
        confidence_threshold_percent = round(settings.modeladmin_confidence_threshold * 100, 2)
        classification = blob_data.get("classification") or {}
        classified_type = (
            classification.get("document_type")
            or blob_data.get("document_type")
            or document_type
        )
        classification_confidence = classification.get("confidence", blob_data.get("confidence", 0.0))
        classification_confidence_percent = _normalize_confidence_percent(classification_confidence) or 0.0

        structured_data = _normalize_structured_field(
            blob_data.get("structured_data") or {},
            confidence_threshold_percent,
        )

        response = {
            "blob_name": blob_name,
            "document_type": classified_type,
            "classification_confidence": classification_confidence_percent,
            "job_id": blob_data.get("job_id"),
            "processed_at": blob_data.get("processed_at"),
            "fields": structured_data,
            "has_low_confidence": (
                classification_confidence_percent < confidence_threshold_percent
                or _any_low_confidence_field(structured_data)
            ),
        }

        return response

    except Exception as e:
        print(f"Error parsing document data: {str(e)}")
        return {
            "blob_name": blob_name,
            "document_type": document_type,
            "error": f"Failed to parse: {str(e)}",
            "fields": blob_data.get("structured_data") or {},
            "has_low_confidence": False,
        }


async def _download_and_parse_document(container_client, blob_name: str) -> Optional[Dict[str, Any]]:
    def _read_blob_data() -> dict:
        return json.loads(container_client.download_blob(blob_name).readall())

    try:
        doc_json = await asyncio.to_thread(_read_blob_data)
        doc_type = get_document_type(blob_name)
        return parse_document_data(blob_name, doc_json, doc_type)
    except Exception as e:
        print(f"Error processing blob {blob_name}: {str(e)}")
        return None


async def _load_documents_from_container(
    container_client,
    requested_type: DocumentTypeFilter,
) -> List[Dict[str, Any]]:
    if not container_client:
        return []

    blob_names: List[str] = []
    for blob in container_client.list_blobs():
        blob_name = blob.name or ""
        if not blob_name.endswith(".json"):
            continue
        if blob_name.startswith("thumbnails/"):
            continue
        if not blob_name.endswith("_parsed.json"):
            continue
        blob_names.append(blob_name)

    semaphore = asyncio.Semaphore(MAX_PARALLEL_BLOB_DOWNLOADS)

    async def _worker(name: str) -> Optional[Dict[str, Any]]:
        async with semaphore:
            return await _download_and_parse_document(container_client, name)

    results = await asyncio.gather(*(_worker(name) for name in blob_names), return_exceptions=False)
    documents = [item for item in results if item is not None]

    if requested_type != "all":
        requested_type = normalize_document_type_value(requested_type)
        documents = [doc for doc in documents if normalize_document_type_value(doc.get("document_type")) == requested_type]

    return documents