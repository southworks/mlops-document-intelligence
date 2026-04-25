"""ModelAdmin candidate intake service for unknown/low-confidence documents"""

from typing import Any, Dict, Optional, Tuple

from app.config import get_settings
from app.modeladmin_core.contracts import DocumentProcessingOutcome
from app.modeladmin_core.policy import evaluate_candidate_decision

settings = get_settings()


def evaluate_candidate_trigger(
    document_type: str,
    classification_confidence: Optional[float],
    structured_data: Optional[Dict[str, Any]],
) -> Tuple[bool, Optional[str], bool]:
    outcome = DocumentProcessingOutcome(
        document_id="policy-probe",
        blob_path="",
        processed_blob_path="",
        predicted_document_type=document_type,
        classification_confidence=classification_confidence,
        compose_model_id="policy-probe",
        source_channel="policy-probe",
        structured_data=structured_data,
    )
    decision = evaluate_candidate_decision(
        outcome=outcome,
        confidence_threshold=settings.modeladmin_confidence_threshold,
        always_flag_unknown=settings.modeladmin_always_flag_unknown,
    )
    return decision.should_create, decision.trigger_reason, decision.has_low_confidence
