"""Health endpoints for ModelAdmin dedicated service runtime."""

from fastapi import APIRouter

from modeladmin_service.config import get_modeladmin_service_settings
from modeladmin_service.telemetry import snapshot_counters

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
def health_check() -> dict:
    settings = get_modeladmin_service_settings()
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
