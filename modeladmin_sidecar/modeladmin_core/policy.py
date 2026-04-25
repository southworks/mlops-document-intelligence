"""Core policy engine for deciding when to create retraining review candidates."""

from typing import Any, Dict, Optional

from modeladmin_sidecar.modeladmin_core.contracts import (
    CandidateDecision,
    DocumentProcessingOutcome,
)
from modeladmin_sidecar.modeladmin_core.normalization import (
    normalize_confidence,
    normalize_document_type,
)


def get_threshold_for_type(
    document_type: str,
    threshold_invoice: float,
    threshold_po: float,
    threshold_grn: float,
) -> float:
    if document_type == "invoices":
        return threshold_invoice
    if document_type == "purchase-order":
        return threshold_po
    if document_type == "goods-receipt-note":
        return threshold_grn

    return min(threshold_invoice, threshold_po, threshold_grn)


def _extract_field_confidence(field_value: Any) -> Optional[float]:
    if isinstance(field_value, dict):
        confidence = field_value.get("confidence")
        if isinstance(confidence, (int, float)):
            return float(confidence)
    return None


def has_low_field_confidence(structured_data: Optional[Dict[str, Any]], threshold: float) -> bool:
    if not structured_data or not isinstance(structured_data, dict):
        return False

    # pylint: disable=too-many-nested-blocks
    for field_value in structured_data.values():
        if isinstance(field_value, list):
            for entry in field_value:
                if isinstance(entry, dict):
                    for sub_value in entry.values():
                        confidence = _extract_field_confidence(sub_value)
                        if confidence is not None and confidence < threshold:
                            return True
        else:
            confidence = _extract_field_confidence(field_value)
            if confidence is not None and confidence < threshold:
                return True

    return False


def evaluate_candidate_decision(
    outcome: DocumentProcessingOutcome,
    threshold_invoice: float,
    threshold_po: float,
    threshold_grn: float,
    always_flag_unknown: bool,
) -> CandidateDecision:
    normalized_type = normalize_document_type(outcome.predicted_document_type)
    threshold = get_threshold_for_type(
        normalized_type,
        threshold_invoice=threshold_invoice,
        threshold_po=threshold_po,
        threshold_grn=threshold_grn,
    )

    if always_flag_unknown and normalized_type == "unknown":
        return CandidateDecision(
            should_create=True,
            trigger_reason="unknown_classification",
            has_low_confidence=False,
            normalized_document_type=normalized_type,
            applied_threshold=threshold,
        )

    confidence = normalize_confidence(outcome.classification_confidence)
    if confidence < threshold:
        return CandidateDecision(
            should_create=True,
            trigger_reason="low_confidence",
            has_low_confidence=False,
            normalized_document_type=normalized_type,
            applied_threshold=threshold,
        )

    low_field = has_low_field_confidence(outcome.structured_data, threshold)
    if low_field:
        return CandidateDecision(
            should_create=True,
            trigger_reason="low_field_confidence",
            has_low_confidence=True,
            normalized_document_type=normalized_type,
            applied_threshold=threshold,
        )

    return CandidateDecision(
        should_create=False,
        trigger_reason=None,
        has_low_confidence=False,
        normalized_document_type=normalized_type,
        applied_threshold=threshold,
    )
