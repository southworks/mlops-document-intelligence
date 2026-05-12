"""Internal shared ModelAdmin core package."""

from modeladmin_sidecar.modeladmin_core.boundary_contracts import (
    APPROVED_SAMPLE_EXPORT_EVENT,
    CANDIDATE_CREATED_EVENT,
    ApprovedSampleExportV1Payload,
    CandidateCreatedV1Payload,
    CandidateCreatedV1Response,
)
from modeladmin_sidecar.modeladmin_core.contracts import (
    CandidateDecision,
    DocumentProcessingOutcome,
)
from modeladmin_sidecar.modeladmin_core.normalization import (
    normalize_confidence,
    normalize_document_type,
)

__all__ = [
    "CANDIDATE_CREATED_EVENT",
    "APPROVED_SAMPLE_EXPORT_EVENT",
    "CandidateCreatedV1Payload",
    "CandidateCreatedV1Response",
    "ApprovedSampleExportV1Payload",
    "CandidateDecision",
    "DocumentProcessingOutcome",
    "normalize_document_type",
    "normalize_confidence",
]
