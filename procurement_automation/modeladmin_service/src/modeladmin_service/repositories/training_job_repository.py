"""Repository for training job and training job operation persistence."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_service.database.models import TrainingJobModel, TrainingJobOperationModel


class TrainingJobRepository:
    """Data access layer for TrainingJob and TrainingJobOperation entities."""

    def __init__(self, db: Session):
        self.db = db

    # ── TrainingJobModel ────────────────────────────────────────────────────

    def create_job(self, *, dataset_version_id: str) -> TrainingJobModel:
        job = TrainingJobModel(
            dataset_version_id=dataset_version_id,
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job_by_id(self, job_id: str) -> Optional[TrainingJobModel]:
        return self.db.query(TrainingJobModel).filter(TrainingJobModel.id == job_id).first()

    def list_jobs(self) -> list[TrainingJobModel]:
        return (
            self.db.query(TrainingJobModel)
            .order_by(TrainingJobModel.created_at.desc())
            .all()
        )

    def update_job_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> TrainingJobModel:
        job = self.get_job_by_id(job_id)
        if not job:
            raise ValueError(f"Training job not found: {job_id}")
        job.status = status
        if error_message is not None:
            job.error_message = error_message
        if completed_at is not None:
            job.completed_at = completed_at
        self.db.commit()
        self.db.refresh(job)
        return job

    # ── TrainingJobOperationModel ───────────────────────────────────────────

    def create_operation(
        self,
        *,
        job_id: str,
        operation_type: str,
        doc_type: Optional[str] = None,
    ) -> TrainingJobOperationModel:
        op = TrainingJobOperationModel(
            job_id=job_id,
            operation_type=operation_type,
            doc_type=doc_type,
            status="pending",
        )
        self.db.add(op)
        self.db.commit()
        self.db.refresh(op)
        return op

    def get_operation_by_id(self, operation_id: str) -> Optional[TrainingJobOperationModel]:
        return (
            self.db.query(TrainingJobOperationModel)
            .filter(TrainingJobOperationModel.id == operation_id)
            .first()
        )

    def list_operations_by_job(self, job_id: str) -> list[TrainingJobOperationModel]:
        return (
            self.db.query(TrainingJobOperationModel)
            .filter(TrainingJobOperationModel.job_id == job_id)
            .order_by(TrainingJobOperationModel.created_at)
            .all()
        )

    def update_operation_running(
        self,
        operation_id: str,
        *,
        adi_operation_id: str,
    ) -> Optional[TrainingJobOperationModel]:
        op = self.get_operation_by_id(operation_id)
        if not op:
            return None
        op.status = "running"
        op.adi_operation_id = adi_operation_id
        self.db.commit()
        self.db.refresh(op)
        return op

    def update_operation_completed(
        self,
        operation_id: str,
        *,
        adi_model_id: str,
    ) -> Optional[TrainingJobOperationModel]:
        op = self.get_operation_by_id(operation_id)
        if not op:
            return None
        op.status = "completed"
        op.adi_model_id = adi_model_id
        self.db.commit()
        self.db.refresh(op)
        return op

    def update_operation_failed(
        self,
        operation_id: str,
        *,
        error_message: str,
    ) -> Optional[TrainingJobOperationModel]:
        op = self.get_operation_by_id(operation_id)
        if not op:
            return None
        op.status = "failed"
        op.error_message = error_message
        self.db.commit()
        self.db.refresh(op)
        return op
