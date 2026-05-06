"""ModelAdmin active model and compose catalog endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.modeladmin_core.service_api_contracts import (
    ActiveModelConfigResponse,
    ComposeModelListResponse,
)
from modeladmin_sidecar.repositories.active_model_config_repository import ActiveModelConfigRepository
from modeladmin_sidecar.repositories.compose_model_repository import ComposeModelRepository

router = APIRouter(prefix="/modeladmin/models", tags=["modeladmin"])


def _serialize_active_model(config) -> dict:
    return {
        "active_model_id": config.active_model_id,
        "activated_at": config.activated_at.isoformat() if config.activated_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


@router.get("/active")
def get_active_model(db: Session = Depends(get_db)) -> ActiveModelConfigResponse:
    repo = ActiveModelConfigRepository(db)
    active_config = repo.get_active_model_config()
    if not active_config:
        raise HTTPException(status_code=404, detail="active model is not configured")
    return {"item": _serialize_active_model(active_config)}


@router.post("/{model_id}/activate")
def activate_compose_model(model_id: str, db: Session = Depends(get_db)):
    compose_repo = ComposeModelRepository(db)
    active_repo = ActiveModelConfigRepository(db)

    compose_model = compose_repo.get_by_id(model_id)
    if not compose_model:
        raise HTTPException(status_code=404, detail=f"compose model not found: {model_id}")
    if not compose_model.status == "ready":
        raise HTTPException(status_code=409, detail="compose model is not ready for activation")

    # Activate in repository
    compose_repo.activate(model_id)

    # Update active config
    active_config = active_repo.upsert_active_model_config(active_model_id=model_id)
    return {"success": True, "item": _serialize_active_model(active_config)}


@router.get("/compose")
def list_compose_models(db: Session = Depends(get_db)) -> ComposeModelListResponse:
    compose_repo = ComposeModelRepository(db)
    items = compose_repo.list_all()

    return {
        "items": [
            {
                "model_id": item.compose_model_id,
                "model_kind": "compose",
                "version_number": item.version_number,
                "adi_created_at": item.created_at.isoformat() if item.created_at else None,
                "classifier_model_id": item.classifier_model_id,
                "extractor_models": compose_repo.get_extractors(item.compose_model_id),
                "is_available": item.status == "ready",
                "is_active": item.is_active,
            }
            for item in items
        ]
    }
