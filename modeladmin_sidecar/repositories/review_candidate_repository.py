"""Repository for ModelAdmin review candidate persistence"""

from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import (
    ReviewCandidateModel,
)


class ReviewCandidateRepository:
    """Data access layer for review candidates"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_document_and_compose_model(
        self,
        document_id: str,
        compose_model_id: str,
    ) -> Optional[ReviewCandidateModel]:
        return (
            self.db.query(ReviewCandidateModel)
            .filter(
                ReviewCandidateModel.document_id == document_id,
                ReviewCandidateModel.compose_model_id == compose_model_id,
            )
            .first()
        )

    def create_candidate(
        self,
        document_id: str,
        blob_path: str,
        processed_blob_path: str,
        predicted_document_type: str,
        classification_confidence: float,
        compose_model_id: str,
        has_low_confidence: bool,
        trigger_reason: str,
        source_channel: str,
        original_filename: Optional[str] = None,
        error_details: Optional[str] = None,
        low_confidence_field_names: Optional[str] = None,
        low_confidence_field_count: Optional[int] = None,
    ) -> ReviewCandidateModel:
        candidate = ReviewCandidateModel(
            document_id=document_id,
            status="new",
            blob_path=blob_path,
            processed_blob_path=processed_blob_path,
            predicted_document_type=predicted_document_type,
            classification_confidence=classification_confidence,
            compose_model_id=compose_model_id,
            has_low_confidence=has_low_confidence,
            trigger_reason=trigger_reason,
            low_confidence_field_names=low_confidence_field_names,
            low_confidence_field_count=low_confidence_field_count,
            source_channel=source_channel,
            original_filename=original_filename,
            error_details=error_details,
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def get_by_id(self, candidate_id: str) -> Optional[ReviewCandidateModel]:
        return (
            self.db.query(ReviewCandidateModel)
            .filter(ReviewCandidateModel.id == candidate_id)
            .first()
        )

    def list_candidates(
        self,
        status: Optional[str] = None,
        document_type: Optional[str] = None,
        trigger_reason: Optional[str] = None,
        compose_model_id: Optional[str] = None,
        source_channel: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        page: int = 1,
        limit: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Tuple[List[ReviewCandidateModel], int]:
        query = self.db.query(ReviewCandidateModel)

        if status:
            query = query.filter(ReviewCandidateModel.status == status)
        if document_type:
            query = query.filter(ReviewCandidateModel.predicted_document_type == document_type)
        if trigger_reason:
            query = query.filter(ReviewCandidateModel.trigger_reason == trigger_reason)
        if compose_model_id:
            query = query.filter(ReviewCandidateModel.compose_model_id == compose_model_id)
        if source_channel:
            query = query.filter(ReviewCandidateModel.source_channel == source_channel)
        if min_confidence is not None:
            query = query.filter(ReviewCandidateModel.classification_confidence >= min_confidence)
        if max_confidence is not None:
            query = query.filter(ReviewCandidateModel.classification_confidence <= max_confidence)
        if date_from is not None:
            query = query.filter(ReviewCandidateModel.created_at >= date_from)
        if date_to is not None:
            query = query.filter(ReviewCandidateModel.created_at <= date_to)

        total = query.count()

        sortable_columns = {
            "created_at": ReviewCandidateModel.created_at,
            "updated_at": ReviewCandidateModel.updated_at,
            "classification_confidence": ReviewCandidateModel.classification_confidence,
            "status": ReviewCandidateModel.status,
            "predicted_document_type": ReviewCandidateModel.predicted_document_type,
        }
        sort_column = sortable_columns.get(sort_by, ReviewCandidateModel.created_at)
        order_expr = asc(sort_column) if sort_order.lower() == "asc" else desc(sort_column)

        items = (
            query
            .order_by(order_expr)
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return items, total

    def apply_label(
        self,
        candidate_id: str,
        label: str,
    ) -> Tuple[Optional[ReviewCandidateModel], Optional[dict], Optional[str]]:
        candidate = self.get_by_id(candidate_id)
        if not candidate:
            return None, None, "not_found"

        if candidate.status in {"approved_for_training", "archived"}:
            return None, None, "invalid_state"

        previous_label = candidate.operator_label
        previous_status = candidate.status

        candidate.operator_label = label
        candidate.reviewed_at = datetime.now(timezone.utc)
        if candidate.status == "new":
            candidate.status = "reviewed"

        self.db.commit()
        self.db.refresh(candidate)

        changes = {
            "old_label": previous_label,
            "new_label": label,
            "old_status": previous_status,
            "new_status": candidate.status,
        }
        return candidate, changes, None

    def apply_approval(
        self,
        candidate_id: str,
    ) -> Tuple[Optional[ReviewCandidateModel], Optional[dict], Optional[str]]:
        """
        Approve a reviewed candidate for training.
        State transition: reviewed -> approved_for_training
        """
        candidate = self.get_by_id(candidate_id)
        if not candidate:
            return None, None, "not_found"

        if candidate.status != "reviewed":
            return None, None, "invalid_state"
        if not candidate.operator_label:
            return candidate, None, "invalid_state_missing_label"

        previous_status = candidate.status
        candidate.status = "approved_for_training"
        candidate.approved_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(candidate)

        changes = {
            "action": "approved",
            "old_status": previous_status,
            "new_status": candidate.status,
        }
        return candidate, changes, None

    def apply_rejection(
        self,
        candidate_id: str,
    ) -> Tuple[Optional[ReviewCandidateModel], Optional[dict], Optional[str]]:
        """
        Reject a candidate.
        State transitions: reviewed -> new, or new -> new (allows relabeling without prior label step)
        """
        candidate = self.get_by_id(candidate_id)
        if not candidate:
            return None, None, "not_found"

        if candidate.status not in {"reviewed", "new"}:
            return None, None, "invalid_state"

        previous_status = candidate.status
        candidate.status = "new"
        candidate.operator_label = None  # Clear label to allow relabeling
        candidate.reviewed_at = None
        self.db.commit()
        self.db.refresh(candidate)

        changes = {
            "action": "rejected",
            "old_status": previous_status,
            "new_status": candidate.status,
        }
        return candidate, changes, None
