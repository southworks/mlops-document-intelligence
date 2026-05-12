"""Boundary intake endpoints for runtime-to-ModelAdmin service communication."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.modeladmin_core.boundary_contracts import (
    CandidateCreatedV1Payload,
    CandidateCreatedV1Response,
)
from modeladmin_sidecar.repositories.review_candidate_repository import ReviewCandidateRepository
from modeladmin_sidecar.telemetry import increment_counter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/boundary/modeladmin", tags=["modeladmin-boundary"])


@router.post("/candidate-created")
def intake_candidate_created(
    payload: CandidateCreatedV1Payload,
    x_service_auth: Optional[str] = Header(default=None, alias="X-Service-Auth"),
    db: Session = Depends(get_db),
) -> CandidateCreatedV1Response:
    try:
        settings = get_modeladmin_sidecar_settings()
        expected_api_key = (settings.boundary_api_key or "").strip()
        if expected_api_key and x_service_auth != expected_api_key:
            increment_counter("boundary_intake.unauthorized")
            raise HTTPException(status_code=401, detail="Unauthorized ModelAdmin boundary request")

        repo = ReviewCandidateRepository(db)
        low_confidence_field_names = payload.low_confidence_field_names or []

        existing = repo.get_by_document_and_compose_model(
            document_id=payload.document_id,
            compose_model_id=payload.compose_model_id,
        )
        if existing:
            increment_counter("boundary_intake.duplicate")
            return CandidateCreatedV1Response(accepted=True, candidate_id=existing.id)

        candidate = repo.create_candidate(
            document_id=payload.document_id,
            blob_path=payload.blob_path,
            processed_blob_path=payload.processed_blob_path,
            predicted_document_type=payload.predicted_document_type,
            classification_confidence=float(payload.classification_confidence or 0.0),
            compose_model_id=payload.compose_model_id,
            has_low_confidence=payload.has_low_confidence,
            trigger_reason=payload.trigger_reason,
            source_channel=payload.source_channel,
            original_filename=payload.original_filename,
            error_details=payload.processing_error,
            low_confidence_field_names=(
                json.dumps(low_confidence_field_names)
                if low_confidence_field_names
                else None
            ),
            low_confidence_field_count=(
                len(low_confidence_field_names)
                if low_confidence_field_names
                else None
            ),
        )

        increment_counter("boundary_intake.accepted")
        logger.info(
            "ModelAdmin boundary candidate accepted",
            extra={
                "candidate_id": candidate.id,
                "document_id": payload.document_id,
                "compose_model_id": payload.compose_model_id,
                "trigger_reason": payload.trigger_reason,
            },
        )

        return CandidateCreatedV1Response(accepted=True, candidate_id=candidate.id)
    except HTTPException:
        raise
    except Exception as exc:
        increment_counter("boundary_intake.failed")
        logger.exception("ModelAdmin boundary intake failed")
        raise HTTPException(status_code=500, detail=f"Boundary intake failed: {exc}") from exc
