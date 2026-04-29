"""ModelAdmin training job routes.

Route handlers are intentionally thin — all orchestration logic lives in
``modeladmin_sidecar.services.training_job_orchestration``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.services.training_job_orchestration import TrainingJobOrchestration

router = APIRouter(prefix="/modeladmin", tags=["modeladmin"])


@router.post("/training-datasets/{dataset_id}/start-training", status_code=201)
def start_training(dataset_id: str, db: Session = Depends(get_db)):
    """Start a new training job for a ready_for_retrain dataset."""
    return TrainingJobOrchestration(db).start_training(dataset_id)


@router.get("/training-jobs/{job_id}")
def get_training_job(job_id: str, db: Session = Depends(get_db)):
    """Return a training job with on-demand ADI status polling."""
    return TrainingJobOrchestration(db).get_job(job_id)


@router.get("/training-jobs")
@router.get("/training-jobs/")
def list_training_jobs(db: Session = Depends(get_db)):
    """Return all training jobs ordered by most recent first, with their operations."""
    return TrainingJobOrchestration(db).list_jobs()

