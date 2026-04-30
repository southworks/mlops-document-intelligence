"""Boundary intake endpoints for runtime-to-ModelAdmin service communication."""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.modeladmin_core.boundary_contracts import (
    CandidateCreatedV1Payload,
    CandidateCreatedV1Response,
)
from modeladmin_sidecar.modeladmin_core import get_threshold_for_type, normalize_document_type
from modeladmin_sidecar.repositories.review_candidate_repository import ReviewCandidateRepository
from modeladmin_sidecar.telemetry import increment_counter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/boundary/modeladmin", tags=["modeladmin-boundary"])


def _extract_low_confidence_field_names(
    structured_data: Optional[Dict[str, Any]],
    threshold: float,
) -> list[str]:
    if not structured_data or not isinstance(structured_data, dict):
        return []

    field_names: list[str] = []

    for field_name, field_value in structured_data.items():
        if isinstance(field_value, dict):
            confidence = field_value.get("confidence")
            if isinstance(confidence, (int, float)) and float(confidence) < threshold:
                field_names.append(field_name)
            continue

        if isinstance(field_value, list):
            for entry in field_value:
                if not isinstance(entry, dict):
                    continue
                for sub_field_name, sub_field_value in entry.items():
                    if not isinstance(sub_field_value, dict):
                        continue
                    confidence = sub_field_value.get("confidence")
                    if isinstance(confidence, (int, float)) and float(confidence) < threshold:
                        field_names.append(f"{field_name}.{sub_field_name}")

    return list(dict.fromkeys(field_names))


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
        threshold = get_threshold_for_type(
            normalize_document_type(payload.predicted_document_type),
            threshold_invoice=settings.confidence_threshold_invoice,
            threshold_po=settings.confidence_threshold_po,
            threshold_grn=settings.confidence_threshold_grn,
        )
        low_confidence_field_names = _extract_low_confidence_field_names(
            payload.structured_data,
            threshold,
        )

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
