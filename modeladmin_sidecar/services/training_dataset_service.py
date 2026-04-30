"""Service layer for training dataset lifecycle operations.

Combines database persistence (via TrainingDatasetRepository) with blob
storage operations and ADI orchestration.  The repository is kept to
pure DB I/O; everything that touches external services lives here.
"""

__all__ = ["TrainingDatasetService"]

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from azure.core.exceptions import AzureError
from sqlalchemy.orm import Session

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database.models import (
    ReviewCandidateModel,
    TrainingDatasetMembershipModel,
    TrainingDatasetModel,
)
from modeladmin_sidecar.modeladmin_core.doc_types import normalize_training_document_type
from modeladmin_sidecar.repositories.retrain_job_repository import RetrainJobRepository
from modeladmin_sidecar.repositories.training_dataset_repository import TrainingDatasetRepository
from modeladmin_sidecar.services.azure_blob_storage_service import AzureBlobStorageService
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService

logger = logging.getLogger(__name__)


class TrainingDatasetService:
    """Lifecycle operations for training datasets.

    Combines database persistence with blob storage and ADI orchestration.
    """

    def __init__(self, db: Session):
        self._db = db
        self._repo = TrainingDatasetRepository(db)
        settings = get_modeladmin_sidecar_settings()
        self._blob_service = AzureBlobStorageService(settings.azure_storage_connection_string)
        self._training_container = settings.training_data_container

    # ------------------------------------------------------------------
    # Blob lifecycle operations (moved from TrainingDatasetRepository)
    # ------------------------------------------------------------------

    def stage_dataset(
        self, dataset_id: str
    ) -> tuple[Optional[TrainingDatasetModel], Optional[str]]:
        """Copy selected blobs to training-data and transition dataset from draft to staged."""
        dataset = self._repo.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "draft":
            return None, "invalid_state"

        members = (
            self._db.query(ReviewCandidateModel)
            .join(
                TrainingDatasetMembershipModel,
                TrainingDatasetMembershipModel.candidate_id == ReviewCandidateModel.id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .all()
        )

        container_name = self._training_container

        try:
            self._blob_service.ensure_container(container_name)
            for candidate in members:
                source_container, source_blob = self._split_blob_path(candidate.blob_path)
                if not source_container or not source_blob:
                    return None, "invalid_blob_path"

                folder = self._resolve_training_folder(
                    candidate.operator_label or candidate.predicted_document_type
                )
                filename = source_blob.split("/")[-1]
                destination_blob = f"{folder}/{filename}"

                self._blob_service.copy_blob(
                    source_container=source_container,
                    source_blob=source_blob,
                    destination_container=container_name,
                    destination_blob=destination_blob,
                    overwrite=True,
                )
        except AzureError:
            return None, "copy_failed"

        dataset.status = "staged"
        dataset.staged_at = datetime.now(timezone.utc)

        self._db.commit()
        self._db.refresh(dataset)
        return dataset, None

    def recheck_labels(
        self, dataset_id: str
    ) -> tuple[Optional[dict], Optional[str]]:
        """Scan blob sidecars for all docs in the dataset and return verification results."""
        dataset = self._repo.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "staged":
            return None, "invalid_state"

        operator_label_rows = (
            self._db.query(ReviewCandidateModel.operator_label)
            .select_from(TrainingDatasetMembershipModel)
            .join(
                ReviewCandidateModel,
                ReviewCandidateModel.id == TrainingDatasetMembershipModel.candidate_id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .distinct()
            .all()
        )
        doc_types = {
            self._resolve_training_folder(row[0])
            for row in operator_label_rows
            if row[0]
        }

        container_name = self._training_container

        results = []
        allowed_field_keys_by_doc_type: dict[str, tuple[set[str], Optional[str]]] = {}
        for doc_type in sorted(doc_types):
            prefix = f"{doc_type}/"
            blob_names = self._blob_service.list_blobs_by_prefix(container_name, prefix)
            pdf_blobs = [b for b in blob_names if b.lower().endswith(".pdf")]

            if doc_type not in allowed_field_keys_by_doc_type:
                fields_blob = f"{doc_type}/fields.json"
                try:
                    fields_payload = self._blob_service.download_blob_text(container_name, fields_blob)
                    allowed_keys = self._extract_allowed_field_keys(fields_payload)
                    allowed_field_keys_by_doc_type[doc_type] = (allowed_keys, None)
                except (AzureError, json.JSONDecodeError, TypeError, ValueError):
                    allowed_field_keys_by_doc_type[doc_type] = (set(), "fields.json missing or invalid")

            for blob_name in pdf_blobs:
                # ADI Studio generates sidecars: file.pdf.ocr.json and file.pdf.labels.json
                has_ocr = self._blob_service.blob_exists(container_name, f"{blob_name}.ocr.json")
                has_labels = self._blob_service.blob_exists(container_name, f"{blob_name}.labels.json")
                filename = blob_name.split("/")[-1]

                has_schema_match = True
                missing_field_keys: list[str] = []
                unexpected_field_keys: list[str] = []

                if has_labels:
                    allowed_keys, fields_error = allowed_field_keys_by_doc_type.get(doc_type, (set(), None))
                    if fields_error:
                        has_schema_match = False
                        missing_field_keys = [fields_error]
                    else:
                        labels_blob = f"{blob_name}.labels.json"
                        try:
                            labels_payload = self._blob_service.download_blob_text(container_name, labels_blob)
                            provided_keys = self._extract_labeled_field_keys(labels_payload)
                        except (AzureError, json.JSONDecodeError, TypeError, ValueError):
                            has_schema_match = False
                            missing_field_keys = ["labels.json missing or invalid"]
                            provided_keys = set()

                        if has_schema_match:
                            missing_field_keys = sorted(allowed_keys - provided_keys)
                            unexpected_field_keys = sorted(provided_keys - allowed_keys)
                            has_schema_match = not missing_field_keys and not unexpected_field_keys

                results.append(
                    {
                        "doc_type": doc_type,
                        "filename": filename,
                        "has_ocr": has_ocr,
                        "has_labels": has_labels,
                        "has_schema_match": has_schema_match,
                        "missing_field_keys": missing_field_keys,
                        "unexpected_field_keys": unexpected_field_keys,
                    }
                )

        # Empty scans must never be considered verified; they indicate missing training content.
        all_verified = bool(results) and all(
            r["has_ocr"] and r["has_labels"] and r["has_schema_match"]
            for r in results
        )

        dataset.label_verification_status = json.dumps(results)
        self._db.commit()
        self._db.refresh(dataset)

        return {
            "all_verified": all_verified,
            "new_status": dataset.status,
            "results": results,
        }, None

    def mark_ready_for_retrain(
        self,
        *,
        dataset_id: str,
        min_items_per_class: int,
    ) -> tuple[Optional[TrainingDatasetModel], Optional[str]]:
        """Verify sidecars and class minimums, then transition dataset to ready_for_retrain."""
        dataset = self._repo.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "staged":
            return None, "invalid_state"

        membership_count = (
            self._db.query(TrainingDatasetMembershipModel)
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .count()
        )
        if membership_count == 0:
            return None, "empty_membership"

        recheck_result, recheck_error = self.recheck_labels(dataset_id)
        if recheck_error:
            return None, "verification_failed"
        if not recheck_result or not recheck_result.get("all_verified", False):
            return None, "missing_sidecars"

        per_class_counts = self._repo.get_cumulative_class_counts(dataset_id)

        if not per_class_counts:
            return None, "empty_membership"

        if any(
            (label is None) or (count < min_items_per_class)
            for label, count in per_class_counts.items()
        ):
            return None, "class_minimum_not_met"

        dataset.status = "ready_for_retrain"
        dataset.ready_at = datetime.now(timezone.utc)
        dataset.ready_min_items_per_class = min_items_per_class

        self._db.commit()
        self._db.refresh(dataset)
        return dataset, None

    # ------------------------------------------------------------------
    # Orchestration operations (moved from training_datasets.py route)
    # ------------------------------------------------------------------

    def start_retrain_job(self, dataset_id: str):
        """Submit a retrain job for a ready_for_retrain dataset."""
        dataset = self._repo.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "ready_for_retrain":
            return None, "invalid_state"

        compose_model_ids = self._repo.list_compose_component_model_ids(dataset_id)
        if not compose_model_ids:
            return None, "no_compose_models"

        compose_model_id = compose_model_ids[0]
        classifier_model_id, doc_type_model_map = self._repo.get_compose_retrain_inputs(compose_model_id)

        job_repo = RetrainJobRepository(self._db)
        job = job_repo.create_job(training_dataset_id=dataset_id)

        try:
            if classifier_model_id and doc_type_model_map:
                document_intelligence_service = DocumentIntelligenceService()
                operation_id = document_intelligence_service.begin_compose_model(
                    classifier_model_id=classifier_model_id,
                    doc_type_model_map=doc_type_model_map,
                    model_name=f"retrain-{dataset.id[:8]}",
                )
                job = job_repo.update_job_running(job.id, adi_operation_id=operation_id)
        except ValueError:
            # Missing ADI configuration in current environment; keep job queued.
            pass
        except Exception as exc:  # pylint: disable=broad-except
            job = job_repo.update_job_failed(job.id, error_message=str(exc))

        return job, None

    def get_class_counts_with_chain(
        self, dataset_id: str
    ) -> tuple[list[str], dict[str, int]]:
        """Return the parent-chain IDs and per-class document counts for a dataset."""
        chain_ids: list[str] = []
        current_id: Optional[str] = dataset_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            chain_ids.append(current_id)
            d = self._repo.get_dataset_by_id(current_id)
            current_id = d.parent_dataset_id if d else None

        per_class_counts = self._repo.get_cumulative_class_counts(dataset_id)
        return chain_ids, per_class_counts

    # ------------------------------------------------------------------
    # Static helpers (moved from TrainingDatasetRepository)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_training_folder(label: Optional[str]) -> str:
        return normalize_training_document_type(label)

    @staticmethod
    def _split_blob_path(blob_path: str) -> tuple[Optional[str], Optional[str]]:
        cleaned = (blob_path or "").strip().lstrip("/")
        parts = cleaned.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None, None
        return parts[0], parts[1]

    @staticmethod
    def _extract_allowed_field_keys(fields_payload_text: str) -> set[str]:
        payload = json.loads(fields_payload_text)
        fields = payload.get("fields", [])
        if not isinstance(fields, list):
            return set()

        keys = set()
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_key = field.get("fieldKey")
            if isinstance(field_key, str) and field_key.strip():
                keys.add(field_key.strip())
        return keys

    @staticmethod
    def _extract_labeled_field_keys(labels_payload_text: str) -> set[str]:
        payload = json.loads(labels_payload_text)
        labels = payload.get("labels", [])
        if not isinstance(labels, list):
            return set()

        keys = set()
        for label_item in labels:
            if not isinstance(label_item, dict):
                continue
            label_key = label_item.get("label")
            if isinstance(label_key, str) and label_key.strip():
                keys.add(label_key.strip())
        return keys
