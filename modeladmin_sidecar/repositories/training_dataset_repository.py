"""Repository for training dataset persistence — pure DB access only."""
from typing import Optional, Sequence, Tuple

__all__ = ["TrainingDatasetRepository"]

from sqlalchemy import desc
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import (
    ComposeModelExtractorModel,
    ComposeModelModel,
    ReviewCandidateModel,
    TrainedModelModel,
    TrainingDatasetMembershipModel,
    TrainingDatasetModel,
)


class TrainingDatasetRepository:
    """Data access layer for training datasets and snapshot membership."""

    def __init__(self, db: Session):
        self.db = db

    def create_dataset(
        self,
        *,
        name: str,
        created_by: str,
        memberships: Sequence[Tuple[str, str]],
        parent_dataset_id: Optional[str] = None,
    ) -> TrainingDatasetModel:
        dataset = TrainingDatasetModel(
            name=name,
            status="draft",
            created_by=created_by,
            parent_dataset_id=parent_dataset_id,
        )
        self.db.add(dataset)
        self.db.flush()

        self.append_memberships(
            dataset_id=dataset.id,
            memberships=memberships,
        )

        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def append_memberships(
        self,
        *,
        dataset_id: str,
        memberships: Sequence[Tuple[str, str]],
    ) -> list[TrainingDatasetMembershipModel]:
        dataset = self.get_dataset_by_id(dataset_id)
        if not dataset or dataset.status != "draft":
            raise ValueError("membership_immutable")

        membership_rows = [
            TrainingDatasetMembershipModel(
                dataset_id=dataset_id,
                candidate_id=candidate_id,
                compose_model_id=compose_model_id,
            )
            for candidate_id, compose_model_id in memberships
        ]
        if membership_rows:
            self.db.add_all(membership_rows)

        return membership_rows

    def list_datasets(
        self,
        *,
        page: int,
        limit: int,
        status: Optional[str] = None,
    ) -> tuple[list[TrainingDatasetModel], int]:
        query = self.db.query(TrainingDatasetModel)
        if status:
            query = query.filter(TrainingDatasetModel.status == status)

        total = query.count()
        items = (
            query
            .order_by(desc(TrainingDatasetModel.created_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def get_dataset_by_id(self, dataset_id: str) -> Optional[TrainingDatasetModel]:
        return (
            self.db.query(TrainingDatasetModel)
            .filter(TrainingDatasetModel.id == dataset_id)
            .first()
        )

    def list_memberships(self, dataset_id: str) -> list[TrainingDatasetMembershipModel]:
        return (
            self.db.query(TrainingDatasetMembershipModel)
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .order_by(TrainingDatasetMembershipModel.created_at.asc())
            .all()
        )

    def list_compose_component_model_ids(self, dataset_id: str) -> list[str]:
        rows = (
            self.db.query(ReviewCandidateModel.compose_model_id)
            .join(
                TrainingDatasetMembershipModel,
                TrainingDatasetMembershipModel.candidate_id == ReviewCandidateModel.id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .filter(ReviewCandidateModel.compose_model_id.isnot(None))
            .order_by(TrainingDatasetMembershipModel.created_at.asc())
            .all()
        )

        unique_ids: list[str] = []
        seen: set[str] = set()
        for (compose_model_id,) in rows:
            if not compose_model_id:
                continue
            if compose_model_id in seen:
                continue
            seen.add(compose_model_id)
            unique_ids.append(compose_model_id)

        return unique_ids

    def get_compose_retrain_inputs(self, compose_model_id: str) -> tuple[Optional[str], dict[str, str]]:
        compose_model = (
            self.db.query(ComposeModelModel)
            .filter(ComposeModelModel.compose_model_id == compose_model_id)
            .first()
        )
        if not compose_model:
            return None, {}

        rows = (
            self.db.query(ComposeModelExtractorModel.trained_model_id, TrainedModelModel.model_type)
            .join(
                TrainedModelModel,
                TrainedModelModel.trained_model_id == ComposeModelExtractorModel.trained_model_id,
            )
            .filter(ComposeModelExtractorModel.compose_model_id == compose_model_id)
            .all()
        )

        doc_type_model_map: dict[str, str] = {}
        for trained_model_id, model_type in rows:
            if not model_type or model_type == "classifier":
                continue
            doc_type_model_map[model_type] = trained_model_id

        return compose_model.classifier_model_id, doc_type_model_map

    def list_enriched_memberships(self, dataset_id: str) -> list[dict]:
        """Return membership rows joined with candidate metadata for the curation table."""
        rows = (
            self.db.query(TrainingDatasetMembershipModel, ReviewCandidateModel)
            .join(
                ReviewCandidateModel,
                ReviewCandidateModel.id == TrainingDatasetMembershipModel.candidate_id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .order_by(TrainingDatasetMembershipModel.created_at.asc())
            .all()
        )
        return [
            {
                "candidate_id": membership.candidate_id,
                "document_id": candidate.document_id,
                "original_filename": candidate.original_filename,
                "operator_label": candidate.operator_label,
                "compose_model_id": membership.compose_model_id,
                "approved_at": candidate.approved_at.isoformat() if candidate.approved_at else None,
            }
            for membership, candidate in rows
        ]

    def remove_member(self, *, dataset_id: str, candidate_id: str) -> bool:
        """Remove a single member from a draft dataset. Returns True if a row was deleted."""
        deleted = (
            self.db.query(TrainingDatasetMembershipModel)
            .filter(
                TrainingDatasetMembershipModel.dataset_id == dataset_id,
                TrainingDatasetMembershipModel.candidate_id == candidate_id,
            )
            .first()
        )
        if not deleted:
            return False
        self.db.delete(deleted)
        self.db.commit()
        return True

    def get_cumulative_class_counts(self, dataset_id: str) -> dict[str, int]:
        """Walk the parent_dataset_id chain and return per-class item counts.

        Candidates appearing in multiple datasets in the ancestry chain are
        deduplicated so each document is counted exactly once.
        """
        chain: list[str] = []
        current_id: Optional[str] = dataset_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            chain.append(current_id)
            row = self.get_dataset_by_id(current_id)
            current_id = row.parent_dataset_id if row else None

        if not chain:
            return {}

        rows = (
            self.db.query(TrainingDatasetMembershipModel, ReviewCandidateModel)
            .join(
                ReviewCandidateModel,
                ReviewCandidateModel.id == TrainingDatasetMembershipModel.candidate_id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id.in_(chain))
            .all()
        )

        counts: dict[str, int] = {}
        seen: set[str] = set()
        for membership, candidate in rows:
            if membership.candidate_id in seen:
                continue
            seen.add(membership.candidate_id)
            if candidate.operator_label:
                counts[candidate.operator_label] = counts.get(candidate.operator_label, 0) + 1
        return counts
