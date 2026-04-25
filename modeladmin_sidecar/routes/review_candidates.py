"""ModelAdmin review-candidate API handlers for dedicated service runtime."""

import json
from datetime import datetime
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.modeladmin_core.doc_types import to_storage_label
from modeladmin_sidecar.modeladmin_core.service_api_contracts import (
    CandidateApprovalRequest,
    CandidateLabelRequest,
    CandidateRejectionRequest,
    ListReviewCandidatesResponse,
    ReviewCandidateMutationResponse,
    ReviewCandidateResponse,
)
from modeladmin_sidecar.repositories.review_candidate_store import ReviewCandidateStore

router = APIRouter(prefix="/modeladmin/review-candidates", tags=["modeladmin"])


def _serialize_candidate(candidate):
    low_confidence_fields = []
    if candidate.low_confidence_field_names:
        try:
            parsed = json.loads(candidate.low_confidence_field_names)
            if isinstance(parsed, list):
                low_confidence_fields = [str(item) for item in parsed if isinstance(item, str)]
        except json.JSONDecodeError:
            low_confidence_fields = []

    return {
        "id": candidate.id,
        "document_id": candidate.document_id,
        "status": candidate.status,
        "blob_path": candidate.blob_path,
        "processed_blob_path": candidate.processed_blob_path,
        "predicted_document_type": candidate.predicted_document_type,
        "classification_confidence": candidate.classification_confidence,
        "compose_model_id": candidate.compose_model_id,
        "has_low_confidence": candidate.has_low_confidence,
        "trigger_reason": candidate.trigger_reason,
        "low_confidence_fields": low_confidence_fields,
        "low_confidence_field_count": (
            candidate.low_confidence_field_count
            if candidate.low_confidence_field_count is not None
            else (len(low_confidence_fields) if low_confidence_fields else None)
        ),
        "source_channel": candidate.source_channel,
        "original_filename": candidate.original_filename,
        "operator_label": candidate.operator_label,
        "reviewed_at": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
        "approved_at": candidate.approved_at.isoformat() if candidate.approved_at else None,
        "error_details": candidate.error_details,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "updated_at": candidate.updated_at.isoformat() if candidate.updated_at else None,
    }


@router.get("")
@router.get("/")
def list_review_candidates(
    status: Optional[str] = Query(None, description="Filter by candidate workflow status"),
    document_type: Optional[str] = Query(None, description="Filter by predicted document type"),
    trigger_reason: Optional[str] = Query(None, description="Filter by trigger reason"),
    compose_model_id: Optional[str] = Query(None, description="Filter by compose model ID"),
    source_channel: Optional[str] = Query(None, description="Filter by source channel"),
    min_confidence: Optional[float] = Query(
        None,
        ge=0.0,
        le=1.0,
        description="Minimum classification confidence",
    ),
    max_confidence: Optional[float] = Query(
        None,
        ge=0.0,
        le=1.0,
        description="Maximum classification confidence",
    ),
    date_from: Optional[datetime] = Query(None, description="Created-at filter start (ISO-8601)"),
    date_to: Optional[datetime] = Query(None, description="Created-at filter end (ISO-8601)"),
    page: int = Query(1, ge=1, description="Result page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(
        "created_at",
        description=(
            "Sort by: "
            "created_at|updated_at|classification_confidence|status|predicted_document_type"
        ),
    ),
    sort_order: str = Query("desc", description="Sort order: asc|desc"),
    db: Session = Depends(get_db),
) -> ListReviewCandidatesResponse:
    if (
        min_confidence is not None
        and max_confidence is not None
        and min_confidence > max_confidence
    ):
        raise HTTPException(
            status_code=400,
            detail="min_confidence cannot be greater than max_confidence",
        )

    if sort_order.lower() not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

    repository = ReviewCandidateStore(db)
    items, total = repository.list_candidates(
        status=status,
        document_type=document_type,
        trigger_reason=trigger_reason,
        compose_model_id=compose_model_id,
        source_channel=source_channel,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        date_from=date_from,
        date_to=date_to,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return {
        "items": [_serialize_candidate(item) for item in items],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": ceil(total / limit) if total > 0 else 0,
        },
        "filters": {
            "status": status,
            "document_type": document_type,
            "trigger_reason": trigger_reason,
            "compose_model_id": compose_model_id,
            "source_channel": source_channel,
            "min_confidence": min_confidence,
            "max_confidence": max_confidence,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    }


@router.get("/{candidate_id}")
def get_review_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> ReviewCandidateResponse:
    repository = ReviewCandidateStore(db)
    candidate = repository.get_by_id(candidate_id)

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail=f"Review candidate not found: {candidate_id}",
        )

    return {
        "item": _serialize_candidate(candidate)
    }


@router.post("/{candidate_id}/label")
def label_review_candidate(
    candidate_id: str,
    request: CandidateLabelRequest,
    db: Session = Depends(get_db),
) -> ReviewCandidateMutationResponse:
    repository = ReviewCandidateStore(db)
    candidate, changes, error = repository.apply_label(
        candidate_id=candidate_id,
        label=to_storage_label(request.label),
    )

    if error == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"Review candidate not found: {candidate_id}",
        )
    if error == "invalid_state":
        raise HTTPException(
            status_code=409,
            detail=(
                "Candidate cannot be labeled in current state "
                "(approved_for_training or archived)"
            ),
        )
    return {
        "success": True,
        "item": _serialize_candidate(candidate),
        "changes": changes,
    }


@router.post("/{candidate_id}/approve")
def approve_review_candidate(
    candidate_id: str,
    request: CandidateApprovalRequest,
    db: Session = Depends(get_db),
) -> ReviewCandidateMutationResponse:
    _ = request
    repository = ReviewCandidateStore(db)
    candidate, changes, error = repository.apply_approval(
        candidate_id=candidate_id,
    )

    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"Review candidate not found: {candidate_id}")
    if error == "invalid_state":
        raise HTTPException(
            status_code=409,
            detail=(
                "Candidate cannot be approved from current state "
                f"'{candidate.status if candidate else 'unknown'}'"
            ),
        )
    if error == "invalid_state_missing_label":
        raise HTTPException(
            status_code=409,
            detail="Candidate must be labeled before approval",
        )

    return {
        "success": True,
        "item": _serialize_candidate(candidate),
        "changes": changes,
    }


@router.post("/{candidate_id}/reject")
def reject_review_candidate(
    candidate_id: str,
    request: CandidateRejectionRequest,
    db: Session = Depends(get_db),
) -> ReviewCandidateMutationResponse:
    _ = request

    repository = ReviewCandidateStore(db)
    candidate, changes, error = repository.apply_rejection(
        candidate_id=candidate_id,
    )

    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"Review candidate not found: {candidate_id}")
    if error == "invalid_state":
        raise HTTPException(
            status_code=409,
            detail=(
                "Candidate cannot be rejected from current state "
                f"'{candidate.status if candidate else 'unknown'}'"
            ),
        )
    return {
        "success": True,
        "item": _serialize_candidate(candidate),
        "changes": changes,
    }
