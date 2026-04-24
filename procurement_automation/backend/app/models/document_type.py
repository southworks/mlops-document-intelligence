"""Canonical document type definitions and normalization helpers."""

from enum import Enum
from typing import Optional


class DocumentType(str, Enum):
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase-order"
    GOODS_RECEIPT_NOTE = "goods-receipt-note"
    UNKNOWN = "unknown"


DOCUMENT_TYPE_ALIASES = {
    "invoice": DocumentType.INVOICE,
    "purchase-order": DocumentType.PURCHASE_ORDER,
    "goods-receipt-note": DocumentType.GOODS_RECEIPT_NOTE,
    "unknown": DocumentType.UNKNOWN,
}


def to_document_type(document_type: Optional[str]) -> DocumentType:
    if not document_type:
        return DocumentType.UNKNOWN

    value = document_type.strip().lower()

    # Azure DI compose outputs can include extractor IDs (e.g. invoice-extractor.v0)
    if "invoice" in value and "extractor" in value:
        return DocumentType.INVOICE
    if "purchase-order" in value and "extractor" in value:
        return DocumentType.PURCHASE_ORDER
    if "goods-receipt-note" in value and "extractor" in value:
        return DocumentType.GOODS_RECEIPT_NOTE

    return DOCUMENT_TYPE_ALIASES.get(value, DocumentType.UNKNOWN)


def normalize_document_type_value(document_type: Optional[str]) -> str:
    return to_document_type(document_type).value