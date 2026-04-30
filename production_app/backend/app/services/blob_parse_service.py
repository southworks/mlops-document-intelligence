"""Blob parsing helpers for document read/list endpoints."""

from typing import Any, Optional

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
