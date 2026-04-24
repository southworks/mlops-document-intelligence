"""Core policy engine for deciding when to create retraining review candidates."""

from typing import Any, Dict, Optional

from app.modeladmin_core.contracts import CandidateDecision, DocumentProcessingOutcome
from app.models.document_type import normalize_document_type_value


def _extract_field_confidence(field_value: Any) -> Optional[float]:
    if isinstance(field_value, dict):
        confidence = field_value.get("confidence")
        if isinstance(confidence, (int, float)):
            return float(confidence)
    return None


def has_low_field_confidence(structured_data: Optional[Dict[str, Any]], threshold: float) -> bool:
    if not structured_data or not isinstance(structured_data, dict):
        return False

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
    confidence_threshold: float,
    always_flag_unknown: bool,
) -> CandidateDecision:
    normalized_type = normalize_document_type_value(outcome.predicted_document_type)
    threshold = float(confidence_threshold)

    if always_flag_unknown and normalized_type == "unknown":
        return CandidateDecision(
            should_create=True,
            trigger_reason="unknown_classification",
            has_low_confidence=False,
            normalized_document_type=normalized_type,
            applied_threshold=threshold,
        )

    confidence = float(outcome.classification_confidence or 0.0)
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
