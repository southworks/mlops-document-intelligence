"""Bootstrap import service for externally created ADI models."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from modeladmin_service.database.models import (
    ActiveModelConfigModel,
    ComposeModelExtractorModel,
    ComposeModelModel,
    TrainedModelModel,
)
from modeladmin_service.modeladmin_core.service_api_contracts import BootstrapImportRequest
from modeladmin_service.services.azure_blob_storage_service import AzureBlobStorageService
from modeladmin_service.services.document_intelligence_service import DocumentIntelligenceService
from modeladmin_service.config import get_modeladmin_service_settings


logger = logging.getLogger(__name__)


class BootstrapValidationError(ValueError):
    """Raised when bootstrap payload fails ADI existence validation."""


class BootstrapImportService:
    """Shared bootstrap import flow used by API and CLI."""

    def __init__(self, db: Session | None, adi_service: DocumentIntelligenceService, bootstrap_file_dir: str | None = None):
        self.db = db
        self.adi_service = adi_service
        self.bootstrap_file_dir = bootstrap_file_dir  # Directory where bootstrap.json is located

    def validate_against_adi(self, payload: BootstrapImportRequest) -> dict:
        """Check every model ID in the payload against ADI. Returns a validation result dict."""
        missing_model_ids: list[str] = []

        if not self.adi_service.document_model_exists(payload.compose_model_id):
            missing_model_ids.append(payload.compose_model_id)

        if not self.adi_service.classifier_exists(payload.classifier_model_id):
            missing_model_ids.append(payload.classifier_model_id)

        for model_id in payload.extractors.values():
            if not self.adi_service.document_model_exists(model_id):
                missing_model_ids.append(model_id)

        return {
            "success": len(missing_model_ids) == 0,
            "compose_model_id": payload.compose_model_id,
            "classifier_model_id": payload.classifier_model_id,
            "extractor_count": len(payload.extractors),
            "activate": payload.activate,
            "missing_model_ids": missing_model_ids,
        }

    def apply(self, payload: BootstrapImportRequest) -> dict:
        if self.db is None:
            raise ValueError("Database session is required for apply")

        validation = self.validate_against_adi(payload)
        if not validation["success"]:
            raise BootstrapValidationError("One or more model IDs were not found in ADI")

        # Upload training data files if specified
        upload_result = {"uploaded": 0, "skipped": 0}
        if payload.training_data and self.bootstrap_file_dir:
            upload_result = self._upload_training_files(payload.training_data)

        with self.db.begin():
            self._upsert_trained_model(
                trained_model_id=payload.classifier_model_id,
                model_type="classifier",
            )

            for model_type, model_id in payload.extractors.items():
                self._upsert_trained_model(
                    trained_model_id=model_id,
                    model_type=model_type,
                )

            compose_model = self._upsert_compose_model(
                compose_model_id=payload.compose_model_id,
                classifier_model_id=payload.classifier_model_id,
            )

            for model_id in payload.extractors.values():
                self._upsert_compose_extractor_mapping(
                    compose_model_id=compose_model.compose_model_id,
                    trained_model_id=model_id,
                )

            if payload.activate:
                self._activate_compose_model(payload.compose_model_id)

        return {
            "success": True,
            "compose_model_id": payload.compose_model_id,
            "classifier_model_id": payload.classifier_model_id,
            "extractor_count": len(payload.extractors),
            "activated": payload.activate,
            "training_data_files_uploaded": upload_result["uploaded"],
            "training_data_files_skipped": upload_result["skipped"],
        }

    def _upsert_trained_model(
        self,
        *,
        trained_model_id: str,
        model_type: str,
    ) -> TrainedModelModel:
        model = (
            self.db.query(TrainedModelModel)
            .filter(TrainedModelModel.trained_model_id == trained_model_id)
            .first()
        )
        if model:
            model.model_type = model_type
            model.status = "ready"
            model.adi_model_name = model.adi_model_name or trained_model_id
            return model

        model = TrainedModelModel(
            trained_model_id=trained_model_id,
            model_type=model_type,
            version_number=1,
            dataset_version_id=None,
            status="ready",
            adi_model_name=trained_model_id,
        )
        self.db.add(model)
        return model

    def _upsert_compose_model(
        self,
        *,
        compose_model_id: str,
        classifier_model_id: str,
    ) -> ComposeModelModel:
        model = (
            self.db.query(ComposeModelModel)
            .filter(ComposeModelModel.compose_model_id == compose_model_id)
            .first()
        )
        if model:
            model.classifier_model_id = classifier_model_id
            model.status = "ready"
            model.adi_model_name = model.adi_model_name or compose_model_id
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
        self.db.add(model)
        return model

    def _upsert_compose_extractor_mapping(self, *, compose_model_id: str, trained_model_id: str) -> None:
        existing = (
            self.db.query(ComposeModelExtractorModel)
            .filter(
                ComposeModelExtractorModel.compose_model_id == compose_model_id,
                ComposeModelExtractorModel.trained_model_id == trained_model_id,
            )
            .first()
        )
        if existing:
            return

        self.db.add(
            ComposeModelExtractorModel(
                compose_model_id=compose_model_id,
                trained_model_id=trained_model_id,
            )
        )

    def _activate_compose_model(self, compose_model_id: str) -> None:
        self.db.query(ComposeModelModel).filter(ComposeModelModel.is_active.is_(True)).update(
            {"is_active": False, "activated_at": None},
            synchronize_session=False,
        )
        self.db.query(ComposeModelModel).filter(
            ComposeModelModel.compose_model_id == compose_model_id
        ).update(
            {
                "is_active": True,
                "activated_at": datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )

        active_config = (
            self.db.query(ActiveModelConfigModel)
            .filter(ActiveModelConfigModel.id == 1)
            .first()
        )
        if active_config:
            active_config.active_model_id = compose_model_id
            active_config.activated_at = datetime.now(timezone.utc)
        else:
            self.db.add(
                ActiveModelConfigModel(
                    id=1,
                    active_model_id=compose_model_id,
                    activated_at=datetime.now(timezone.utc),
                )
            )

    def _upload_training_files(self, training_data: dict) -> dict:
        """Upload training data files from local filesystem to blob storage.

        Returns: {"uploaded": N, "skipped": N}
        """
        dataset_path = training_data.get("dataset_path", "")
        if not dataset_path:
            logger.warning("training_data.dataset_path not specified, skipping file upload")
            return {"uploaded": 0, "skipped": 0}

        # Resolve dataset path relative to bootstrap.json directory
        if self.bootstrap_file_dir:
            dataset_dir = Path(self.bootstrap_file_dir) / dataset_path
        else:
            dataset_dir = Path(dataset_path)

        if not dataset_dir.exists():
            logger.warning("Dataset directory not found: %s", dataset_dir)
            return {"uploaded": 0, "skipped": 0}

        settings = get_modeladmin_service_settings()
        blob_service = AzureBlobStorageService(settings.azure_storage_connection_string)
        blob_service.ensure_container(settings.training_data_container)

        uploaded = 0
        skipped = 0

        # Upload all files recursively, preserving directory structure
        for file_path in dataset_dir.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip hidden files
            if any(part.startswith(".") for part in file_path.parts):
                continue

            # Construct blob name: preserve relative path from dataset_dir
            relative_path = file_path.relative_to(dataset_dir)
            blob_name = str(relative_path).replace("\\", "/")

            # Check if blob already exists (idempotent)
            if blob_service.blob_exists(settings.training_data_container, blob_name):
                logger.debug("Blob already exists, skipping: %s", blob_name)
                skipped += 1
            else:
                try:
                    blob_service.upload_blob(
                        container=settings.training_data_container,
                        blob_name=blob_name,
                        local_file_path=str(file_path),
                        overwrite=False,
                    )
                    logger.debug("Uploaded blob: %s", blob_name)
                    uploaded += 1
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Failed to upload blob %s: %s", blob_name, str(exc))

        logger.warning(
            "Training data upload complete: uploaded=%d skipped=%d dataset_path=%s",
            uploaded,
            skipped,
            dataset_dir,
        )
        return {"uploaded": uploaded, "skipped": skipped}
