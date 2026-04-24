"""Service-owned persistence adapter for training datasets."""

from typing import Optional, Sequence, Tuple
from sqlalchemy.orm import Session

from modeladmin_service.database.models import TrainingDatasetModel
from modeladmin_service.repositories.training_dataset_repository import TrainingDatasetRepository


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

    def mark_ready_for_retrain(
        self,
        *,
        dataset_id: str,
        min_items_per_class: int,
        blob_service,
        training_data_container: str,
    ):
        return self._repo.mark_ready_for_retrain(
            dataset_id=dataset_id,
            min_items_per_class=min_items_per_class,
            blob_service=blob_service,
            training_data_container=training_data_container,
        )

    def stage_dataset(self, *, dataset_id: str, blob_service, training_data_container: str):
        return self._repo.stage_dataset(
            dataset_id=dataset_id,
            blob_service=blob_service,
            training_data_container=training_data_container,
        )

    def recheck_labels(self, *, dataset_id: str, blob_service, training_data_container: str):
        return self._repo.recheck_labels(
            dataset_id=dataset_id,
            blob_service=blob_service,
            training_data_container=training_data_container,
        )

    def get_cumulative_class_counts(self, dataset_id: str) -> dict[str, int]:
        return self._repo.get_cumulative_class_counts(dataset_id)
