"""Admin utility endpoints (non-production, demo reset)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.database import models as _models  # noqa: F401 — ensures all tables are registered
from modeladmin_sidecar.database.connection import Base, engine, get_db
from modeladmin_sidecar.database.models import (
    ActiveModelConfigModel,
    ComposeModelExtractorModel,
    ComposeModelModel,
    TrainedModelModel,
)
from modeladmin_sidecar.modeladmin_core.service_api_contracts import (
    BootstrapImportApplyResponse,
    BootstrapImportRequest,
)
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

class BootstrapValidationError(ValueError):
    """Raised when bootstrap payload references model IDs not found in ADI."""


def _validate_against_adi(payload: BootstrapImportRequest, adi_service: DocumentIntelligenceService) -> list[str]:
    """Return list of model IDs missing from ADI (empty list means all valid)."""
    missing: list[str] = []
    if not adi_service.document_model_exists(payload.compose_model_id):
        missing.append(payload.compose_model_id)
    if not adi_service.classifier_exists(payload.classifier_model_id):
        missing.append(payload.classifier_model_id)
    for model_id in payload.extractors.values():
        if not adi_service.document_model_exists(model_id):
            missing.append(model_id)
    return missing


def _upsert_trained_model(db: Session, *, trained_model_id: str, model_type: str) -> TrainedModelModel:
    model = db.query(TrainedModelModel).filter(TrainedModelModel.trained_model_id == trained_model_id).first()
    if model:
        model.model_type = model_type
        model.status = "ready"
        return model
    model = TrainedModelModel(
        trained_model_id=trained_model_id,
        model_type=model_type,
        version_number=1,
        dataset_version_id=None,
        status="ready",
        adi_model_name=trained_model_id,
    )
    db.add(model)
    return model


def _upsert_compose_model(db: Session, *, compose_model_id: str, classifier_model_id: str) -> ComposeModelModel:
    model = db.query(ComposeModelModel).filter(ComposeModelModel.compose_model_id == compose_model_id).first()
    if model:
        model.classifier_model_id = classifier_model_id
        model.status = "ready"
        return model
    model = ComposeModelModel(
        compose_model_id=compose_model_id,
        version_number=1,
        dataset_version_id=None,
        classifier_model_id=classifier_model_id,
        status="ready",
        adi_model_name=compose_model_id,
        is_active=False,
        activated_at=None,
    )
    db.add(model)
    return model


def _upsert_compose_extractor_mapping(db: Session, *, compose_model_id: str, trained_model_id: str) -> None:
    existing = (
        db.query(ComposeModelExtractorModel)
        .filter(
            ComposeModelExtractorModel.compose_model_id == compose_model_id,
            ComposeModelExtractorModel.trained_model_id == trained_model_id,
        )
        .first()
    )
    if not existing:
        db.add(ComposeModelExtractorModel(compose_model_id=compose_model_id, trained_model_id=trained_model_id))


def _activate_compose_model(db: Session, compose_model_id: str) -> None:
    db.query(ComposeModelModel).filter(ComposeModelModel.is_active.is_(True)).update(
        {"is_active": False, "activated_at": None}, synchronize_session=False
    )
    db.query(ComposeModelModel).filter(ComposeModelModel.compose_model_id == compose_model_id).update(
        {"is_active": True, "activated_at": datetime.now(timezone.utc)}, synchronize_session=False
    )
    now = datetime.now(timezone.utc)
    active_config = db.query(ActiveModelConfigModel).filter(ActiveModelConfigModel.id == 1).first()
    if active_config:
        active_config.active_model_id = compose_model_id
        active_config.activated_at = now
    else:
        db.add(ActiveModelConfigModel(id=1, active_model_id=compose_model_id, activated_at=now))


def _apply_bootstrap(db: Session, payload: BootstrapImportRequest, adi_service: DocumentIntelligenceService) -> dict:
    missing = _validate_against_adi(payload, adi_service)
    if missing:
        raise BootstrapValidationError("One or more model IDs were not found in ADI")

    with db.begin():
        _upsert_trained_model(db, trained_model_id=payload.classifier_model_id, model_type="classifier")
        for model_type, model_id in payload.extractors.items():
            _upsert_trained_model(db, trained_model_id=model_id, model_type=model_type)
        compose = _upsert_compose_model(
            db, compose_model_id=payload.compose_model_id, classifier_model_id=payload.classifier_model_id
        )
        for model_id in payload.extractors.values():
            _upsert_compose_extractor_mapping(db, compose_model_id=compose.compose_model_id, trained_model_id=model_id)
        if payload.activate:
            _activate_compose_model(db, payload.compose_model_id)

    return {
        "success": True,
        "compose_model_id": payload.compose_model_id,
        "classifier_model_id": payload.classifier_model_id,
        "extractor_count": len(payload.extractors),
        "activated": payload.activate,
        "training_data_files_uploaded": 0,
        "training_data_files_skipped": 0,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/reset-demo", response_model=BootstrapImportApplyResponse)
def reset_demo(
    payload: BootstrapImportRequest,
    db: Session = Depends(get_db),
) -> BootstrapImportApplyResponse:
    """Drop and recreate all tables, then seed from the bootstrap payload.

    Intended for local demo resets only — not safe for production use.
    """
    logger.warning("reset-demo: dropping and recreating all tables")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # The session bound to the dropped DB is now stale — expire and reopen.
    db.close()
    from modeladmin_sidecar.database.connection import SESSION_LOCAL  # noqa: PLC0415

    fresh_db = SESSION_LOCAL()
    try:
        try:
            result = _apply_bootstrap(fresh_db, payload, DocumentIntelligenceService())
        except BootstrapValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.warning("reset-demo: complete compose_model_id=%s", payload.compose_model_id)
        return result
    finally:
        fresh_db.close()
