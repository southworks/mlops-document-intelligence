"""Service-owned persistence adapter for training datasets."""

__all__ = ["TrainingDatasetStore"]

from typing import Optional, Sequence, Tuple
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import TrainingDatasetModel
from modeladmin_sidecar.repositories.training_dataset_repository import TrainingDatasetRepository


class TrainingDatasetStore:
    """ModelAdmin service persistence boundary for training datasets."""

    def __init__(self, db: Session):
        self._repo = TrainingDatasetRepository(db)

    def create_dataset(
        self,
        *,
        name: str,
        created_by: str,
        memberships: Sequence[Tuple[str, str]],
        parent_dataset_id: Optional[str] = None,
    ) -> TrainingDatasetModel:
        return self._repo.create_dataset(
            name=name,
            created_by=created_by,
            memberships=memberships,
            parent_dataset_id=parent_dataset_id,
        )

    def list_datasets(
        self,
        *,
        page: int,
        limit: int,
        status: Optional[str],
    ) -> tuple[list[TrainingDatasetModel], int]:
        return self._repo.list_datasets(page=page, limit=limit, status=status)

    def get_dataset_by_id(self, dataset_id: str) -> Optional[TrainingDatasetModel]:
        return self._repo.get_dataset_by_id(dataset_id)

    def list_memberships(self, dataset_id: str):
        return self._repo.list_memberships(dataset_id)

    def list_enriched_memberships(self, dataset_id: str) -> list[dict]:
        return self._repo.list_enriched_memberships(dataset_id)

    def remove_member(self, *, dataset_id: str, candidate_id: str) -> bool:
        return self._repo.remove_member(dataset_id=dataset_id, candidate_id=candidate_id)

    def get_cumulative_class_counts(self, dataset_id: str) -> dict[str, int]:
        return self._repo.get_cumulative_class_counts(dataset_id)
