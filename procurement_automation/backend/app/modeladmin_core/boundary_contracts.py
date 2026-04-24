"""Versioned boundary contracts for ModelAdmin runtime/service split."""

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


CANDIDATE_CREATED_EVENT = "modeladmin.candidate.created.v1"
APPROVED_SAMPLE_EXPORT_EVENT = "modeladmin.samples.approved.v1"


class CandidateCreatedV1Payload(BaseModel):
    """Payload emitted when a document is enrolled as a review candidate."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    event_name: Literal["modeladmin.candidate.created.v1"] = CANDIDATE_CREATED_EVENT
    contract_version: Literal["1.0.0"] = "1.0.0"
    document_id: str
    compose_model_id: str
    idempotency_key: str

    blob_path: str
    processed_blob_path: str
    source_channel: str

    predicted_document_type: str
    classification_confidence: Optional[float] = None
    has_low_confidence: bool
    trigger_reason: str

    original_filename: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    processing_error: Optional[str] = None

    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CandidateCreatedV1Response(BaseModel):
    """Synchronous boundary response for candidate-created intake."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    contract_version: Literal["1.0.0"] = "1.0.0"
    accepted: bool
    candidate_id: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
