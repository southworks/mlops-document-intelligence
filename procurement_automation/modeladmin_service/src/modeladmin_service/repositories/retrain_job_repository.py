"""Repository for retrain job persistence."""

from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_service.database.models import RetrainJobModel


class RetrainJobRepository:
    """Data access layer for retrain jobs."""

    def __init__(self, db: Session):
        self.db = db

    def create_job(self, *, training_dataset_id: str) -> RetrainJobModel:
        job = RetrainJobModel(training_dataset_id=training_dataset_id, status="queued")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job_by_id(self, job_id: str) -> Optional[RetrainJobModel]:
        return (
            self.db.query(RetrainJobModel)
            .filter(RetrainJobModel.id == job_id)
            .first()
        )

    def list_jobs(self) -> list[RetrainJobModel]:
        return (
            self.db.query(RetrainJobModel)
            .order_by(RetrainJobModel.submitted_at.desc())
            .all()
        )

    def update_job_running(self, job_id: str, *, adi_operation_id: str) -> Optional[RetrainJobModel]:
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        job.status = "running"
        job.adi_operation_id = adi_operation_id
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_job_failed(self, job_id: str, *, error_message: str) -> Optional[RetrainJobModel]:
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        if job.status in {"succeeded", "failed"}:
            return job
        job.status = "failed"
        job.error_message = error_message
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_job_succeeded(self, job_id: str, *, adi_model_id: str) -> Optional[RetrainJobModel]:
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        if job.status in {"succeeded", "failed"}:
            return job
        job.status = "succeeded"
        job.adi_model_id = adi_model_id
        self.db.commit()
        self.db.refresh(job)
        return job
