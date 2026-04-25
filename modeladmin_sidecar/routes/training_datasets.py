"""ModelAdmin training dataset API handlers."""

from datetime import datetime, timezone
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.modeladmin_core.service_api_contracts import (
    ListTrainingDatasetsResponse,
    RecheckResponse,
    TrainingDatasetCreateRequest,
    TrainingDatasetDetailResponse,
    TrainingDatasetMarkReadyRequest,
    TrainingDatasetMutationResponse,
    DatasetClassCountsResponse,
)
from modeladmin_sidecar.repositories.review_candidate_store import ReviewCandidateStore
from modeladmin_sidecar.repositories.training_dataset_store import TrainingDatasetStore

from modeladmin_sidecar.modeladmin_core.service_api_contracts import RetrainJobMutationResponse
from modeladmin_sidecar.repositories.retrain_job_store import RetrainJobStore
from modeladmin_sidecar.repositories.training_dataset_repository import TrainingDatasetRepository
from modeladmin_sidecar.services.azure_blob_storage_service import AzureBlobStorageService
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService
from modeladmin_sidecar.config import get_modeladmin_sidecar_settings

router = APIRouter(prefix="/modeladmin/training-datasets", tags=["modeladmin"])


def _to_dataset_name(base_name: str) -> str:
    timestamp_suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{base_name}-{timestamp_suffix}"


def _serialize_dataset(dataset, membership_count: int):
    return {
        "id": dataset.id,
        "name": dataset.name,
        "status": dataset.status,
        "created_by": dataset.created_by,
        "label_verification_status": dataset.label_verification_status,
        "ready_at": dataset.ready_at.isoformat() if dataset.ready_at else None,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
        "membership_count": membership_count,
    }


@router.post("")
@router.post("/")
def create_training_dataset(
    request: TrainingDatasetCreateRequest,
    db: Session = Depends(get_db),
) -> TrainingDatasetMutationResponse:
    created_by = request.created_by.strip()
    if not created_by:
        raise HTTPException(status_code=400, detail="created_by is required")

    base_name = request.name.strip()
    if not base_name:
        raise HTTPException(status_code=400, detail="name is required")

    if not request.candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids must contain at least one item")

    candidate_ids = [candidate_id.strip() for candidate_id in request.candidate_ids if candidate_id.strip()]
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids must contain at least one item")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise HTTPException(status_code=400, detail="candidate_ids must not contain duplicates")

    candidate_store = ReviewCandidateStore(db)
    memberships = []
    for candidate_id in candidate_ids:
        candidate = candidate_store.get_by_id(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail=f"Review candidate not found: {candidate_id}")
        if candidate.status != "approved_for_training":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only candidates in approved_for_training status can be added to a dataset"
                ),
            )
        memberships.append((candidate.id, candidate.compose_model_id))

    dataset_store = TrainingDatasetStore(db)

    if request.parent_dataset_id:
        parent = dataset_store.get_dataset_by_id(request.parent_dataset_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent dataset not found: {request.parent_dataset_id}")

    dataset = dataset_store.create_dataset(
        name=_to_dataset_name(base_name),
        created_by=created_by,
        memberships=memberships,
        parent_dataset_id=request.parent_dataset_id or None,
    )

    return {
        "success": True,
        "item": _serialize_dataset(dataset, membership_count=len(memberships)),
    }


@router.get("")
@router.get("/")
def list_training_datasets(
    status: Optional[str] = Query(None, description="Filter by dataset lifecycle status"),
    page: int = Query(1, ge=1, description="Result page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
) -> ListTrainingDatasetsResponse:
    dataset_store = TrainingDatasetStore(db)
    items, total = dataset_store.list_datasets(page=page, limit=limit, status=status)

    serialized_items = []
    for dataset in items:
        membership_count = len(dataset_store.list_memberships(dataset.id))
        serialized_items.append(_serialize_dataset(dataset, membership_count=membership_count))

    return {
        "items": serialized_items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": ceil(total / limit) if total > 0 else 0,
        },
    }


@router.get("/{dataset_id}")
def get_training_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> TrainingDatasetDetailResponse:
    dataset_store = TrainingDatasetStore(db)
    dataset = dataset_store.get_dataset_by_id(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")

    enriched = dataset_store.list_enriched_memberships(dataset_id)
    return {
        "item": _serialize_dataset(dataset, membership_count=len(enriched)),
        "membership": enriched,
    }


@router.delete("/{dataset_id}/members/{candidate_id}")
def remove_dataset_member(
    dataset_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
):
    dataset_store = TrainingDatasetStore(db)
    dataset = dataset_store.get_dataset_by_id(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")

    if dataset.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Cannot remove members from a non-draft dataset",
        )

    removed = dataset_store.remove_member(dataset_id=dataset_id, candidate_id=candidate_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Member not found in dataset: {candidate_id}")

    enriched = dataset_store.list_enriched_memberships(dataset_id)
    return {
        "success": True,
        "item": _serialize_dataset(dataset_store.get_dataset_by_id(dataset_id), membership_count=len(enriched)),
        "membership": enriched,
    }


@router.post("/{dataset_id}/stage")
def stage_training_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> TrainingDatasetMutationResponse:
    settings = get_modeladmin_sidecar_settings()
    blob_service = AzureBlobStorageService(settings.azure_storage_connection_string)
    dataset_store = TrainingDatasetStore(db)
    dataset, error = dataset_store.stage_dataset(
        dataset_id=dataset_id,
        blob_service=blob_service,
        training_data_container=settings.training_data_container,
    )

    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")
    if error == "invalid_state":
        raise HTTPException(status_code=409, detail="Dataset must be in draft state to stage")
    if error == "invalid_blob_path":
        raise HTTPException(status_code=409, detail="One or more candidate blobs have invalid blob_path")
    if error == "copy_failed":
        raise HTTPException(status_code=500, detail="Failed to copy selected blobs into training-data container")

    membership_count = len(dataset_store.list_memberships(dataset_id))
    return {
        "success": True,
        "item": _serialize_dataset(dataset, membership_count=membership_count),
    }


@router.post("/{dataset_id}/mark-ready")
def mark_training_dataset_ready(
    dataset_id: str,
    request: TrainingDatasetMarkReadyRequest,
    db: Session = Depends(get_db),
) -> TrainingDatasetMutationResponse:
    if request.min_items_per_class < 1:
        raise HTTPException(status_code=400, detail="min_items_per_class must be >= 1")

    dataset_store = TrainingDatasetStore(db)
    settings = get_modeladmin_sidecar_settings()
    blob_service = AzureBlobStorageService(settings.azure_storage_connection_string)
    dataset, error = dataset_store.mark_ready_for_retrain(
        dataset_id=dataset_id,
        min_items_per_class=request.min_items_per_class,
        blob_service=blob_service,
        training_data_container=settings.training_data_container,
    )

    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")
    if error == "invalid_state":
        raise HTTPException(status_code=409, detail="Dataset must be in staged state")
    if error == "empty_membership":
        raise HTTPException(status_code=409, detail="Dataset membership cannot be empty")
    if error == "class_minimum_not_met":
        raise HTTPException(
            status_code=409,
            detail="Per-class minimum requirement is not met for mark-ready transition",
        )
    if error == "missing_sidecars":
        raise HTTPException(
            status_code=409,
            detail="OCR/labels sidecars and fields.json schema match are required for every staged file before mark-ready",
        )
    if error == "verification_failed":
        raise HTTPException(
            status_code=500,
            detail="Failed to verify OCR and labels sidecars",
        )

    membership_count = len(dataset_store.list_memberships(dataset_id))
    return {
        "success": True,
        "item": _serialize_dataset(dataset, membership_count=membership_count),
    }


@router.post("/{dataset_id}/recheck")
def recheck_training_dataset_labels(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> RecheckResponse:
    dataset_store = TrainingDatasetStore(db)
    dataset = dataset_store.get_dataset_by_id(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")

    settings = get_modeladmin_sidecar_settings()
    blob_service = AzureBlobStorageService(settings.azure_storage_connection_string)

    result, error = dataset_store.recheck_labels(
        dataset_id=dataset_id,
        blob_service=blob_service,
        training_data_container=settings.training_data_container,
    )

    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")
    if error == "invalid_state":
        raise HTTPException(status_code=409, detail="Recheck failed: dataset must be in staged state")

    return result


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


@router.post("/{dataset_id}/retrain", status_code=201)
def start_retrain_job(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> RetrainJobMutationResponse:
    dataset_store = TrainingDatasetStore(db)
    dataset = dataset_store.get_dataset_by_id(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")
    if dataset.status != "ready_for_retrain":
        raise HTTPException(
            status_code=409,
            detail="Dataset must be in ready_for_retrain status to start retraining",
        )

    repo = TrainingDatasetRepository(db)
    compose_model_ids = repo.list_compose_component_model_ids(dataset_id)
    if not compose_model_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                "No usable component models found for compose retrain. "
                "Ensure dataset members have non-null compose_model_id."
            ),
        )

    compose_model_id = compose_model_ids[0]
    classifier_model_id, doc_type_model_map = repo.get_compose_retrain_inputs(compose_model_id)

    job_store = RetrainJobStore(db)
    job = job_store.create_job(training_dataset_id=dataset_id)

    try:
        if classifier_model_id and doc_type_model_map:
            document_intelligence_service = DocumentIntelligenceService()
            operation_id = document_intelligence_service.begin_compose_model(
                classifier_model_id=classifier_model_id,
                doc_type_model_map=doc_type_model_map,
                model_name=f"retrain-{dataset.id[:8]}",
            )
            job = job_store.update_job_running(job.id, adi_operation_id=operation_id)
    except ValueError:
        # Missing ADI configuration in current environment; keep job queued.
        pass
    except Exception as exc:  # pylint: disable=broad-except
        job = job_store.update_job_failed(job.id, error_message=str(exc))

    return {"success": True, "item": _serialize_job(job)}


@router.get("/{dataset_id}/class-counts")
def get_dataset_class_counts(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> DatasetClassCountsResponse:
    dataset_store = TrainingDatasetStore(db)
    dataset = dataset_store.get_dataset_by_id(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")

    # Build ancestry chain for response transparency
    chain_ids: list[str] = []
    current_id = dataset_id
    visited: set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        chain_ids.append(current_id)
        d = dataset_store.get_dataset_by_id(current_id)
        current_id = d.parent_dataset_id if d else None

    per_class_counts = dataset_store.get_cumulative_class_counts(dataset_id)
    return {
        "dataset_id": dataset_id,
        "chain_ids": chain_ids,
        "per_class_counts": per_class_counts,
    }
