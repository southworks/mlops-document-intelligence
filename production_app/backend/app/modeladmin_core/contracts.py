"""Domain contracts for ModelAdmin candidate decisioning."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class DocumentProcessingOutcome:
    document_id: str
    blob_path: str
    processed_blob_path: str
    predicted_document_type: str
    classification_confidence: Optional[float]
    compose_model_id: str
    source_channel: str
    original_filename: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    processing_error: Optional[str] = None


@dataclass(frozen=True)
class CandidateDecision:
    should_create: bool
    trigger_reason: Optional[str]
    has_low_confidence: bool
    normalized_document_type: str
    applied_threshold: Optional[float]
