"""Health endpoints for ModelAdmin dedicated service runtime."""

from fastapi import APIRouter

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.telemetry import snapshot_counters

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
def health_check() -> dict:
    settings = get_modeladmin_sidecar_settings()
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "environment": settings.environment,
    }


@router.get("/metrics")
def health_metrics() -> dict:
    return {
        "counters": snapshot_counters(),
    }
