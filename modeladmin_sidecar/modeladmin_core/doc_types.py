"""Centralized document type aliases and canonical mappings."""

from __future__ import annotations

from typing import Optional


# Canonical names used for training folders / ADI model naming.
_CANONICAL_BY_ALIAS = {
    "invoice": "invoice",
    "invoices": "invoice",
    "po": "purchase-order",
    "purchase-order": "purchase-order",
    "purchase-orders": "purchase-order",
    "purchaseorder": "purchase-order",
    "grn": "goods-receipt-note",
    "goods-receipt-note": "goods-receipt-note",
    "goods-receipt-notes": "goods-receipt-note",
}

# Canonical labels as stored in review-candidate records.
_STORAGE_LABEL_BY_CANONICAL = {
    "invoice": "invoices",
    "purchase-order": "purchase-order",
    "goods-receipt-note": "goods-receipt-note",
}


def normalize_training_document_type(document_type: Optional[str]) -> str:
    """Return canonical singular training document type (or unknown)."""
    if not document_type:
        return "unknown"

    value = document_type.strip().lower()
    return _CANONICAL_BY_ALIAS.get(value, value)


def normalize_storage_document_type(document_type: Optional[str]) -> str:
    """Return normalized label used by policy/review storage (or unknown)."""
    canonical = normalize_training_document_type(document_type)
    if canonical == "unknown":
        return "unknown"
    return _STORAGE_LABEL_BY_CANONICAL.get(canonical, canonical)


def to_storage_label(label: Optional[str]) -> str:
    """Convert a UI/API label into the repository storage representation."""
    return normalize_storage_document_type(label)
