"""Service-owned persistence adapter for review candidates."""

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import ReviewCandidateModel
from modeladmin_sidecar.repositories.review_candidate_repository import ReviewCandidateRepository


class ReviewCandidateStore:
    """ModelAdmin service persistence boundary for candidate workflows."""

    def __init__(self, db: Session):
        self._repo = ReviewCandidateRepository(db)

    def list_candidates(
        self,
        *,
        status: Optional[str],
        document_type: Optional[str],
        trigger_reason: Optional[str],
        compose_model_id: Optional[str],
        source_channel: Optional[str],
        min_confidence: Optional[float],
        max_confidence: Optional[float],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        page: int,
        limit: int,
        sort_by: str,
        sort_order: str,
    ) -> Tuple[list[ReviewCandidateModel], int]:
        return self._repo.list_candidates(
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

    def get_by_id(self, candidate_id: str) -> Optional[ReviewCandidateModel]:
        return self._repo.get_by_id(candidate_id)

    def get_by_document_and_compose_model(
        self,
        *,
        document_id: str,
        compose_model_id: str,
    ) -> Optional[ReviewCandidateModel]:
        return self._repo.get_by_document_and_compose_model(
            document_id=document_id,
            compose_model_id=compose_model_id,
        )

    def create_candidate(
        self,
        *,
        document_id: str,
        blob_path: str,
        processed_blob_path: str,
        predicted_document_type: str,
        classification_confidence: float,
        compose_model_id: str,
        has_low_confidence: bool,
        trigger_reason: str,
        source_channel: Optional[str],
        original_filename: Optional[str],
        error_details: Optional[str],
        low_confidence_field_names: Optional[str] = None,
        low_confidence_field_count: Optional[int] = None,
    ) -> ReviewCandidateModel:
        return self._repo.create_candidate(
            document_id=document_id,
            blob_path=blob_path,
            processed_blob_path=processed_blob_path,
            predicted_document_type=predicted_document_type,
            classification_confidence=classification_confidence,
            compose_model_id=compose_model_id,
            has_low_confidence=has_low_confidence,
            trigger_reason=trigger_reason,
            source_channel=source_channel,
            original_filename=original_filename,
            error_details=error_details,
            low_confidence_field_names=low_confidence_field_names,
            low_confidence_field_count=low_confidence_field_count,
        )

    def apply_label(
        self,
        *,
        candidate_id: str,
        label: str,
    ):
        return self._repo.apply_label(
            candidate_id=candidate_id,
            label=label,
        )

    def apply_approval(
        self,
        *,
        candidate_id: str,
    ):
        return self._repo.apply_approval(
            candidate_id=candidate_id,
        )

    def apply_rejection(
        self,
        *,
        candidate_id: str,
    ):
        return self._repo.apply_rejection(
            candidate_id=candidate_id,
        )
