"""Admin utility endpoints (non-production, demo reset)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.database import models as _models  # noqa: F401 — ensures all tables are registered
from modeladmin_sidecar.database.connection import Base, engine, get_db
from modeladmin_sidecar.modeladmin_core.service_api_contracts import (
    BootstrapImportApplyResponse,
    BootstrapImportRequest,
)
from modeladmin_sidecar.services.bootstrap_import_service import BootstrapImportService, BootstrapValidationError
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


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
        service = BootstrapImportService(db=fresh_db, adi_service=DocumentIntelligenceService())
        try:
            result = service.apply(payload)
        except BootstrapValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.warning("reset-demo: complete compose_model_id=%s", payload.compose_model_id)
        return result
    finally:
        fresh_db.close()
