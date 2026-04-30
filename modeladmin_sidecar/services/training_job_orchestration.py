"""Training job orchestration: ADI build, polling, and compose lifecycle.

Extracted from routes/training_jobs.py so that route handlers stay thin and
this logic is independently testable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database.models import TrainedModelModel
from modeladmin_sidecar.modeladmin_core.doc_types import normalize_training_document_type
from modeladmin_sidecar.repositories.compose_model_repository import ComposeModelRepository
from modeladmin_sidecar.repositories.compose_model_cache_repository import ComposeModelCacheRepository
from modeladmin_sidecar.repositories.training_dataset_repository import TrainingDatasetRepository
from modeladmin_sidecar.repositories.training_job_repository import TrainingJobRepository
from modeladmin_sidecar.services.azure_blob_storage_service import AzureBlobStorageService
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService
from shared.logging_helpers import audit_log

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def serialize_operation(op) -> dict:
    return {
        "id": op.id,
        "job_id": op.job_id,
        "operation_type": op.operation_type,
        "doc_type": op.doc_type,
        "adi_operation_id": op.adi_operation_id,
        "adi_model_id": op.adi_model_id,
        "status": op.status,
        "error_message": op.error_message,
        "created_at": op.created_at.isoformat() if op.created_at else None,
        "updated_at": op.updated_at.isoformat() if op.updated_at else None,
    }


def serialize_job(job, operations) -> dict:
    return {
        "id": job.id,
        "dataset_version_id": job.dataset_version_id,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "operations": [serialize_operation(op) for op in operations],
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TrainingJobOrchestration:
    """Coordinates ADI training builds and job state transitions.

    Inject a SQLAlchemy ``Session`` — all DB access goes through repositories.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._job_repo = TrainingJobRepository(db)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start_training(self, dataset_id: str) -> dict:
        """Start a new training job for a ready_for_retrain dataset.

        Launches ADI build operations for each extractor (one per doc_type) and
        a classifier, persists the async operation poll URLs, and returns the
        created job object with its per-operation rows.
        """
        dataset_store = TrainingDatasetRepository(self._db)
        dataset = dataset_store.get_dataset_by_id(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail=f"Training dataset not found: {dataset_id}")
        if str(dataset.status) != "ready_for_retrain":
            raise HTTPException(
                status_code=409,
                detail="Dataset must be in ready_for_retrain status to start training",
            )

        enriched = dataset_store.list_enriched_memberships(dataset_id)
        doc_types = sorted(
            {
                normalize_training_document_type(m.get("operator_label"))
                for m in enriched
                if m.get("operator_label")
            }
            - {"unknown"}
        )
        if not doc_types:
            raise HTTPException(
                status_code=409,
                detail="No operator_label values found in dataset memberships",
            )

        version = dataset.version_number
        job = self._job_repo.create_job(dataset_version_id=dataset_id)
        audit_log(
            logger,
            "start_training",
            dataset_id=dataset_id,
            status=dataset.status,
            version=version,
            doc_types=doc_types,
            job_id=job.id,
        )

        # Pre-create all operation rows before any ADI calls
        extractor_ops = {
            doc_type: self._job_repo.create_operation(
                job_id=job.id,
                operation_type="extractor",
                doc_type=doc_type,
            )
            for doc_type in doc_types
        }
        classifier_op = self._job_repo.create_operation(
            job_id=job.id,
            operation_type="classifier",
        )

        try:
            settings = get_modeladmin_sidecar_settings()
            blob_service = AzureBlobStorageService(settings.azure_storage_connection_string)
            sas_url = blob_service.get_container_sas_url(settings.training_data_container)
            adi_service = DocumentIntelligenceService()

            # Query all ready trained models (from bootstrap or previous training).
            # Exclude classifiers and compose models — only extractors go into the map.
            ready_trained_models = (
                self._db.query(TrainedModelModel.trained_model_id, TrainedModelModel.model_type)
                .filter(
                    TrainedModelModel.status == "ready",
                    TrainedModelModel.model_type.notin_(["classifier", "compose"]),
                )
                .all()
            )
            ready_by_type = {
                model_type: model_id for model_id, model_type in ready_trained_models
            }
            logger.warning(
                "Ready trained models from database: %s job_id=%s",
                ready_by_type,
                job.id,
            )

            # Get ALL available doc types from training-data container for the classifier
            all_doc_types = blob_service.list_available_doc_type_folders(settings.training_data_container)
            all_doc_types = [
                dt for dt in all_doc_types if normalize_training_document_type(dt) != "unknown"
            ]
            if not all_doc_types:
                all_doc_types = doc_types  # fallback when container is empty

            logger.warning(
                "Extractors using dataset doc_types: %s; Classifier using all available doc_types: %s job_id=%s",
                sorted(doc_types),
                sorted(all_doc_types),
                job.id,
            )

            self._launch_extractor_builds(
                adi_service, extractor_ops, sas_url, version, job
            )
            self._launch_classifier_build(
                adi_service, classifier_op, all_doc_types, sas_url, version, job
            )

            job = self._job_repo.update_job_status(job.id, "building_components")
        except ValueError:
            # ADI/storage not configured in this environment; leave job pending.
            pass
        except Exception as exc:  # pylint: disable=broad-except
            job = self._job_repo.update_job_status(job.id, "failed", error_message=str(exc))

        operations = self._job_repo.list_operations_by_job(job.id)
        return {"success": True, "item": serialize_job(job, operations)}

    def get_job(self, job_id: str) -> dict:
        """Return a training job with on-demand ADI status polling.

        While the job is building_components, polls every running
        extractor/classifier operation.  When all components are complete,
        automatically kicks off the ADI compose step and transitions the job to
        building_compose.  When compose succeeds, upserts the ComposeModelCache
        and marks the job completed.
        """
        job = self._job_repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Training job not found: {job_id}")

        operations = self._job_repo.list_operations_by_job(job.id)

        if job.status not in ("building_components", "building_compose"):
            return serialize_job(job, operations)

        try:
            adi_service = DocumentIntelligenceService()
        except ValueError:
            # ADI not configured; return current persisted state.
            return serialize_job(job, operations)

        if job.status == "building_components":
            job = self._poll_component_operations(job, operations, adi_service)
            operations = self._job_repo.list_operations_by_job(job.id)

            if job.status == "failed":
                return serialize_job(job, operations)

            # All components done → launch compose
            if job.status == "building_components":
                component_ops = [
                    op for op in operations if op.operation_type in ("extractor", "classifier")
                ]
                if all(op.status == "completed" for op in component_ops):
                    job = self._launch_compose_step(job, operations, adi_service)
                    operations = self._job_repo.list_operations_by_job(job.id)

        if job.status == "building_compose":
            operations = self._job_repo.list_operations_by_job(job.id)
            job = self._poll_compose_operation(job, operations, adi_service)

        operations = self._job_repo.list_operations_by_job(job.id)
        return serialize_job(job, operations)

    def list_jobs(self) -> dict:
        """Return all training jobs ordered by most recent first."""
        jobs = self._job_repo.list_jobs()
        items = [
            serialize_job(job, self._job_repo.list_operations_by_job(job.id)) for job in jobs
        ]
        return {"items": items}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _launch_extractor_builds(self, adi_service, extractor_ops, sas_url, version, job):
        for doc_type, op in extractor_ops.items():
            model_id = f"procurement-{doc_type}-extractor.v{version}"

            if adi_service.document_model_exists(model_id):
                logger.warning(
                    "Model already exists in ADI, skipping build: job_id=%s op_id=%s doc_type=%s model_id=%s",
                    job.id,
                    op.id,
                    doc_type,
                    model_id,
                )
                self._job_repo.update_operation_running(
                    op.id, adi_operation_id=f"model-exists://{model_id}"
                )
                continue

            try:
                operation_url = adi_service.begin_build_document_model(
                    sas_url, model_id, prefix=f"{doc_type}/"
                )
                self._job_repo.update_operation_running(op.id, adi_operation_id=operation_url)
                audit_log(
                    logger,
                    "extractor_submitted",
                    job_id=job.id,
                    op_id=op.id,
                    doc_type=doc_type,
                    model_id=model_id,
                )
            except RuntimeError as exc:
                if "409" in str(exc) or "ModelExists" in str(exc):
                    logger.warning(
                        "Model created concurrently, marking as existing: job_id=%s op_id=%s "
                        "doc_type=%s model_id=%s",
                        job.id,
                        op.id,
                        doc_type,
                        model_id,
                    )
                    self._job_repo.update_operation_running(
                        op.id, adi_operation_id=f"model-exists://{model_id}"
                    )
                else:
                    raise

    def _launch_classifier_build(
        self, adi_service, classifier_op, all_doc_types, sas_url, version, job
    ):
        classifier_model_id = f"procurement-classifier.v{version}"

        if adi_service.classifier_exists(classifier_model_id):
            logger.warning(
                "Classifier already exists in ADI, skipping build: job_id=%s op_id=%s classifier_id=%s",
                job.id,
                classifier_op.id,
                classifier_model_id,
            )
            self._job_repo.update_operation_running(
                classifier_op.id, adi_operation_id=f"model-exists://{classifier_model_id}"
            )
            return

        try:
            sas_urls_by_doc_type = {dt: sas_url for dt in all_doc_types}
            prefixes_by_doc_type = {dt: f"{dt}/" for dt in all_doc_types}
            classifier_url = adi_service.begin_build_classifier(
                sas_urls_by_doc_type,
                classifier_model_id,
                prefixes=prefixes_by_doc_type,
            )
            self._job_repo.update_operation_running(
                classifier_op.id, adi_operation_id=classifier_url
            )
            audit_log(
                logger,
                "classifier_submitted",
                job_id=job.id,
                op_id=classifier_op.id,
                classifier_id=classifier_model_id,
                doc_types=sorted(all_doc_types),
            )
        except RuntimeError as exc:
            if "409" in str(exc) or "ClassifierExists" in str(exc):
                logger.warning(
                    "Classifier created concurrently, marking as existing: job_id=%s op_id=%s classifier_id=%s",
                    job.id,
                    classifier_op.id,
                    classifier_model_id,
                )
                self._job_repo.update_operation_running(
                    classifier_op.id, adi_operation_id=f"model-exists://{classifier_model_id}"
                )
            else:
                raise

    def _poll_component_operations(self, job, operations, adi_service):
        """Poll running extractor/classifier operations and update their status."""
        for op in operations:
            if op.operation_type not in ("extractor", "classifier") or op.status != "running":
                continue
            if op.adi_operation_id is None:
                continue

            if op.adi_operation_id.startswith("model-exists://"):
                model_id = op.adi_operation_id.replace("model-exists://", "")
                logger.warning(
                    "Polling existing model: job_id=%s op_id=%s operation_type=%s model_id=%s",
                    job.id,
                    op.id,
                    op.operation_type,
                    model_id,
                )
                try:
                    if op.operation_type == "extractor":
                        model_exists = adi_service.document_model_exists(model_id)
                    else:
                        model_exists = adi_service.classifier_exists(model_id)

                    if model_exists:
                        self._job_repo.update_operation_completed(op.id, adi_model_id=model_id)
                        logger.warning(
                            "Existing model confirmed ready: job_id=%s op_id=%s model_id=%s",
                            job.id,
                            op.id,
                            model_id,
                        )
                    else:
                        self._job_repo.update_operation_failed(
                            op.id,
                            error_message=f"Model {model_id} marked as existing but not found in ADI",
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    self._job_repo.update_operation_failed(
                        op.id,
                        error_message=f"Failed to verify existing model {model_id}: {str(exc)}",
                    )
                continue

            result = adi_service.get_operation_status(op.adi_operation_id)
            if result["status"] == "succeeded":
                self._job_repo.update_operation_completed(op.id, adi_model_id=result["model_id"])
            elif result["status"] == "failed":
                self._job_repo.update_operation_failed(
                    op.id,
                    error_message=result.get("error") or "ADI operation failed",
                )

        operations = self._job_repo.list_operations_by_job(job.id)
        component_ops = [
            op for op in operations if op.operation_type in ("extractor", "classifier")
        ]

        if any(op.status == "failed" for op in component_ops):
            failed_details = []
            for failed_op in component_ops:
                if failed_op.status != "failed":
                    continue
                op_name = failed_op.operation_type
                if failed_op.doc_type:
                    op_name = f"{op_name}:{failed_op.doc_type}"
                msg = (failed_op.error_message or "ADI operation failed").strip()
                failed_details.append(f"{op_name} -> {msg}")

            summary = "One or more ADI component operations failed"
            if failed_details:
                summary = f"{summary}: {'; '.join(failed_details)}"

            return self._job_repo.update_job_status(job.id, "failed", error_message=summary)

        return job

    def _launch_compose_step(self, job, operations, adi_service):
        """Build the compose model once all extractor + classifier ops have completed."""
        # Merge bootstrap ready models with newly trained extractors
        ready_trained_models = (
            self._db.query(TrainedModelModel.trained_model_id, TrainedModelModel.model_type)
            .filter(
                TrainedModelModel.status == "ready",
                TrainedModelModel.model_type.notin_(["classifier", "compose"]),
            )
            .all()
        )
        ready_by_type = {
            model_type: model_id for model_id, model_type in ready_trained_models
        }
        logger.warning(
            "Ready trained models from database during compose build: %s job_id=%s",
            ready_by_type,
            job.id,
        )

        doc_type_model_map = dict(ready_by_type)
        for op in operations:
            if op.operation_type == "extractor" and op.doc_type and op.adi_model_id:
                doc_type_model_map[op.doc_type] = op.adi_model_id

        logger.warning(
            "Final doc_type_model_map for compose (bootstrap+newly trained): %s job_id=%s",
            doc_type_model_map,
            job.id,
        )

        if not doc_type_model_map:
            error_msg = (
                "No extractor model IDs available for compose "
                "(no ready models and no newly trained extractors)"
            )
            logger.error(error_msg + " job_id=%s", job.id)
            return self._job_repo.update_job_status(job.id, "failed", error_message=error_msg)

        if len(doc_type_model_map) < 2:
            error_msg = (
                f"Need at least 2 extractor models for compose, but found only "
                f"{len(doc_type_model_map)}: {sorted(doc_type_model_map.keys())}"
            )
            logger.error(error_msg + " job_id=%s", job.id)
            return self._job_repo.update_job_status(job.id, "failed", error_message=error_msg)

        classifier_model_id = next(
            (
                op.adi_model_id
                for op in operations
                if op.operation_type == "classifier" and op.adi_model_id
            ),
            None,
        )
        if not classifier_model_id:
            return self._job_repo.update_job_status(
                job.id,
                "failed",
                error_message="No classifier model ID available for compose",
            )

        dataset = TrainingDatasetRepository(self._db).get_dataset_by_id(job.dataset_version_id)
        version = dataset.version_number if dataset else 1
        compose_model_name = f"procurement-compose.v{version}"

        try:
            continuation_token = adi_service.begin_compose_model(
                classifier_model_id=classifier_model_id,
                doc_type_model_map=doc_type_model_map,
                model_name=compose_model_name,
            )
            compose_op = self._job_repo.create_operation(job_id=job.id, operation_type="compose")
            self._job_repo.update_operation_running(
                compose_op.id, adi_operation_id=continuation_token
            )
            job = self._job_repo.update_job_status(job.id, "building_compose")
            audit_log(
                logger,
                "compose_submitted",
                job_id=job.id,
                op_id=compose_op.id,
                compose_model_name=compose_model_name,
                classifier_id=classifier_model_id,
                doc_types=sorted(doc_type_model_map.keys()),
            )
        except Exception as exc:  # pylint: disable=broad-except
            job = self._job_repo.update_job_status(job.id, "failed", error_message=str(exc))

        return job

    def _poll_compose_operation(self, job, operations, adi_service):
        """Poll the running compose operation and finalise the job on success."""
        compose_op = next(
            (
                op
                for op in operations
                if op.operation_type == "compose" and op.status == "running"
            ),
            None,
        )
        if not compose_op or compose_op.adi_operation_id is None:
            return job

        adi_status, adi_model_id, error_message = adi_service.get_compose_status(
            compose_op.adi_operation_id
        )

        if adi_status == "succeeded" and adi_model_id:
            self._job_repo.update_operation_completed(compose_op.id, adi_model_id=adi_model_id)

            extractor_model_ids = [
                op.adi_model_id
                for op in operations
                if op.operation_type == "extractor" and op.adi_model_id
            ]
            classifier_model_id = next(
                (
                    op.adi_model_id
                    for op in operations
                    if op.operation_type == "classifier" and op.adi_model_id
                ),
                None,
            )
            ComposeModelCacheRepository(self._db).upsert_compose_model(
                model_id=adi_model_id,
                adi_created_at=datetime.now(timezone.utc),
                classifier_model_id=classifier_model_id,
                extractor_models=extractor_model_ids,
                is_available=True,
            )

            compose_repo = ComposeModelRepository(self._db)
            existing_compose = compose_repo.get_by_id(adi_model_id)
            dataset = TrainingDatasetRepository(self._db).get_dataset_by_id(job.dataset_version_id)
            version_number = dataset.version_number if dataset else 1

            if existing_compose is None:
                compose_repo.create(
                    compose_model_id=adi_model_id,
                    version_number=version_number,
                    status="ready",
                    dataset_version_id=job.dataset_version_id,
                    classifier_model_id=classifier_model_id,
                    adi_model_name=adi_model_id,
                )
            else:
                existing_compose.status = "ready"
                if classifier_model_id:
                    existing_compose.classifier_model_id = classifier_model_id
                if not existing_compose.dataset_version_id:
                    existing_compose.dataset_version_id = job.dataset_version_id
                self._db.commit()

            existing_extractors = set(compose_repo.get_extractors(adi_model_id))
            for extractor_model_id in extractor_model_ids:
                if extractor_model_id not in existing_extractors:
                    compose_repo.add_extractor(adi_model_id, extractor_model_id)

            job = self._job_repo.update_job_status(
                job.id,
                "completed",
                completed_at=datetime.now(timezone.utc),
            )

        elif adi_status == "failed":
            self._job_repo.update_operation_failed(
                compose_op.id,
                error_message=error_message or "ADI compose operation failed",
            )
            job = self._job_repo.update_job_status(
                job.id,
                "failed",
                error_message=error_message or "ADI compose operation failed",
            )

        return job
