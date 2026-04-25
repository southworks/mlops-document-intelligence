"""ModelAdmin retrain job GET endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.modeladmin_core.service_api_contracts import (
    ListRetrainJobsResponse,
    RetrainJobItemResponse,
)
from modeladmin_sidecar.repositories.retrain_job_store import RetrainJobStore
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService

router = APIRouter(prefix="/modeladmin/retrain-jobs", tags=["modeladmin"])

def _serialize_job(job) -> dict:
    return {
        "id": job.id,
        "training_dataset_id": job.training_dataset_id,
        "status": job.status,
        "adi_operation_id": job.adi_operation_id,
        "adi_model_id": job.adi_model_id,
        "error_message": job.error_message,
        "submitted_at": job.submitted_at.isoformat() if job.submitted_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.get("")
@router.get("/")
def list_retrain_jobs(db: Session = Depends(get_db)) -> ListRetrainJobsResponse:
    store = RetrainJobStore(db)
    return {"items": [_serialize_job(j) for j in store.list_jobs()]}


@router.get("/{job_id}")
def get_retrain_job(job_id: str, db: Session = Depends(get_db)) -> RetrainJobItemResponse:
    store = RetrainJobStore(db)
    job = store.get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Retrain job not found: {job_id}")

    # If job is running, attempt on-demand ADI sync
    if job.status == "running" and job.adi_operation_id:
        try:
            document_intelligence_service = DocumentIntelligenceService()
            adi_status, adi_model_id, error_message = document_intelligence_service.get_compose_status(
                job.adi_operation_id
            )

            if adi_status == "succeeded" and adi_model_id:
                job = store.update_job_succeeded(job.id, adi_model_id=adi_model_id)
            elif adi_status == "failed":
                job = store.update_job_failed(
                    job.id,
                    error_message=error_message or "ADI compose operation failed",
                )
        except ValueError:
            # Missing ADI configuration in current environment; skip sync.
            pass
        except Exception as exc:  # pylint: disable=broad-except
            job = store.update_job_failed(job.id, error_message=str(exc))

    return _serialize_job(job)
