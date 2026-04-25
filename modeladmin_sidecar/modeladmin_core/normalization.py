"""Normalization helpers for document type and confidence values."""

from typing import Optional

from modeladmin_sidecar.modeladmin_core.doc_types import normalize_storage_document_type


def normalize_document_type(document_type: Optional[str]) -> str:
    return normalize_storage_document_type(document_type)


def normalize_confidence(value: Optional[float]) -> float:
    return float(value or 0.0)
