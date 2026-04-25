"""Service-owned persistence adapter for retrain jobs."""

from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import RetrainJobModel
from modeladmin_sidecar.repositories.retrain_job_repository import RetrainJobRepository


class RetrainJobStore:
    """ModelAdmin service persistence boundary for retrain jobs."""

    def __init__(self, db: Session):
        self._repo = RetrainJobRepository(db)

    def create_job(self, *, training_dataset_id: str) -> RetrainJobModel:
        return self._repo.create_job(training_dataset_id=training_dataset_id)

    def get_job_by_id(self, job_id: str) -> Optional[RetrainJobModel]:
        return self._repo.get_job_by_id(job_id)

    def list_jobs(self) -> list[RetrainJobModel]:
        return self._repo.list_jobs()

    def update_job_running(self, job_id: str, *, adi_operation_id: str) -> Optional[RetrainJobModel]:
        return self._repo.update_job_running(job_id, adi_operation_id=adi_operation_id)

    def update_job_failed(self, job_id: str, *, error_message: str) -> Optional[RetrainJobModel]:
        return self._repo.update_job_failed(job_id, error_message=error_message)

    def update_job_succeeded(self, job_id: str, *, adi_model_id: str) -> Optional[RetrainJobModel]:
        return self._repo.update_job_succeeded(job_id, adi_model_id=adi_model_id)
