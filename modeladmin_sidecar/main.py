"""Standalone ModelAdmin service runtime entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database.connection import init_db
from modeladmin_sidecar.routes.admin import router as admin_router
from modeladmin_sidecar.routes.boundary_intake import router as boundary_intake_router
from modeladmin_sidecar.routes.health import router as health_router
from modeladmin_sidecar.routes.models import router as models_router
from modeladmin_sidecar.routes.review_candidates import router as review_candidates_router
from modeladmin_sidecar.routes.training_datasets import router as training_datasets_router
from modeladmin_sidecar.routes.ui import router as ui_router
from modeladmin_sidecar.routes.retrain_jobs import router as retrain_jobs_router
from modeladmin_sidecar.routes.training_jobs import router as training_jobs_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_modeladmin_sidecar_app() -> FastAPI:
    settings = get_modeladmin_sidecar_settings()

    application = FastAPI(
        title="ModelAdmin Service",
        version=settings.service_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    application.include_router(admin_router)
    application.include_router(health_router)
    application.include_router(boundary_intake_router)
    application.include_router(review_candidates_router)
    application.include_router(training_datasets_router)
    application.include_router(retrain_jobs_router)
    application.include_router(training_jobs_router)
    application.include_router(models_router)
    application.include_router(ui_router)

    return application


app = create_modeladmin_sidecar_app()
