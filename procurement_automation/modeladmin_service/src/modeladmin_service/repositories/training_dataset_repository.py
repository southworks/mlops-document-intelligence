"""Repository for training dataset persistence and lifecycle transitions."""
import json
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from azure.core.exceptions import AzureError
from sqlalchemy import desc
from sqlalchemy.orm import Session

from modeladmin_service.database.models import (
    ComposeModelExtractorModel,
    ComposeModelModel,
    ReviewCandidateModel,
    TrainedModelModel,
    TrainingDatasetMembershipModel,
    TrainingDatasetModel,
)
from modeladmin_service.modeladmin_core.doc_types import normalize_training_document_type


class TrainingDatasetRepository:
    """Data access layer for training datasets and snapshot membership."""

    def __init__(self, db: Session):
        self.db = db

    def create_dataset(
        self,
        *,
        name: str,
        created_by: str,
        memberships: Sequence[Tuple[str, str]],
        parent_dataset_id: Optional[str] = None,
    ) -> TrainingDatasetModel:
        dataset = TrainingDatasetModel(
            name=name,
            status="draft",
            created_by=created_by,
            parent_dataset_id=parent_dataset_id,
        )
        self.db.add(dataset)
        self.db.flush()

        self.append_memberships(
            dataset_id=dataset.id,
            memberships=memberships,
        )

        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def append_memberships(
        self,
        *,
        dataset_id: str,
        memberships: Sequence[Tuple[str, str]],
    ) -> list[TrainingDatasetMembershipModel]:
        dataset = self.get_dataset_by_id(dataset_id)
        if not dataset or dataset.status != "draft":
            raise ValueError("membership_immutable")

        membership_rows = [
            TrainingDatasetMembershipModel(
                dataset_id=dataset_id,
                candidate_id=candidate_id,
                compose_model_id=compose_model_id,
            )
            for candidate_id, compose_model_id in memberships
        ]
        if membership_rows:
            self.db.add_all(membership_rows)

        return membership_rows

    def list_datasets(
        self,
        *,
        page: int,
        limit: int,
        status: Optional[str] = None,
    ) -> tuple[list[TrainingDatasetModel], int]:
        query = self.db.query(TrainingDatasetModel)
        if status:
            query = query.filter(TrainingDatasetModel.status == status)

        total = query.count()
        items = (
            query
            .order_by(desc(TrainingDatasetModel.created_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def get_dataset_by_id(self, dataset_id: str) -> Optional[TrainingDatasetModel]:
        return (
            self.db.query(TrainingDatasetModel)
            .filter(TrainingDatasetModel.id == dataset_id)
            .first()
        )

    def list_memberships(self, dataset_id: str) -> list[TrainingDatasetMembershipModel]:
        return (
            self.db.query(TrainingDatasetMembershipModel)
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .order_by(TrainingDatasetMembershipModel.created_at.asc())
            .all()
        )

    def list_compose_component_model_ids(self, dataset_id: str) -> list[str]:
        rows = (
            self.db.query(ReviewCandidateModel.compose_model_id)
            .join(
                TrainingDatasetMembershipModel,
                TrainingDatasetMembershipModel.candidate_id == ReviewCandidateModel.id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .filter(ReviewCandidateModel.compose_model_id.isnot(None))
            .order_by(TrainingDatasetMembershipModel.created_at.asc())
            .all()
        )

        unique_ids: list[str] = []
        seen: set[str] = set()
        for (compose_model_id,) in rows:
            if not compose_model_id:
                continue
            if compose_model_id in seen:
                continue
            seen.add(compose_model_id)
            unique_ids.append(compose_model_id)

        return unique_ids

    def get_compose_retrain_inputs(self, compose_model_id: str) -> tuple[Optional[str], dict[str, str]]:
        compose_model = (
            self.db.query(ComposeModelModel)
            .filter(ComposeModelModel.compose_model_id == compose_model_id)
            .first()
        )
        if not compose_model:
            return None, {}

        rows = (
            self.db.query(ComposeModelExtractorModel.trained_model_id, TrainedModelModel.model_type)
            .join(
                TrainedModelModel,
                TrainedModelModel.trained_model_id == ComposeModelExtractorModel.trained_model_id,
            )
            .filter(ComposeModelExtractorModel.compose_model_id == compose_model_id)
            .all()
        )

        doc_type_model_map: dict[str, str] = {}
        for trained_model_id, model_type in rows:
            if not model_type or model_type == "classifier":
                continue
            doc_type_model_map[model_type] = trained_model_id

        return compose_model.classifier_model_id, doc_type_model_map

    def list_enriched_memberships(self, dataset_id: str) -> list[dict]:
        """Return membership rows joined with candidate metadata for the curation table."""
        rows = (
            self.db.query(TrainingDatasetMembershipModel, ReviewCandidateModel)
            .join(
                ReviewCandidateModel,
                ReviewCandidateModel.id == TrainingDatasetMembershipModel.candidate_id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .order_by(TrainingDatasetMembershipModel.created_at.asc())
            .all()
        )
        return [
            {
                "candidate_id": membership.candidate_id,
                "document_id": candidate.document_id,
                "original_filename": candidate.original_filename,
                "operator_label": candidate.operator_label,
                "compose_model_id": membership.compose_model_id,
                "approved_at": candidate.approved_at.isoformat() if candidate.approved_at else None,
            }
            for membership, candidate in rows
        ]

    def remove_member(self, *, dataset_id: str, candidate_id: str) -> bool:
        """Remove a single member from a draft dataset. Returns True if a row was deleted."""
        deleted = (
            self.db.query(TrainingDatasetMembershipModel)
            .filter(
                TrainingDatasetMembershipModel.dataset_id == dataset_id,
                TrainingDatasetMembershipModel.candidate_id == candidate_id,
            )
            .first()
        )
        if not deleted:
            return False
        self.db.delete(deleted)
        self.db.commit()
        return True

    def get_cumulative_class_counts(self, dataset_id: str) -> dict[str, int]:
        """Walk the parent_dataset_id chain and return per-class item counts.

        Candidates appearing in multiple datasets in the ancestry chain are
        deduplicated so each document is counted exactly once.
        """
        chain: list[str] = []
        current_id: Optional[str] = dataset_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            chain.append(current_id)
            row = self.get_dataset_by_id(current_id)
            current_id = row.parent_dataset_id if row else None

        if not chain:
            return {}

        rows = (
            self.db.query(TrainingDatasetMembershipModel, ReviewCandidateModel)
            .join(
                ReviewCandidateModel,
                ReviewCandidateModel.id == TrainingDatasetMembershipModel.candidate_id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id.in_(chain))
            .all()
        )

        counts: dict[str, int] = {}
        seen: set[str] = set()
        for membership, candidate in rows:
            if membership.candidate_id in seen:
                continue
            seen.add(membership.candidate_id)
            if candidate.operator_label:
                counts[candidate.operator_label] = counts.get(candidate.operator_label, 0) + 1
        return counts

    def mark_ready_for_retrain(
        self,
        *,
        dataset_id: str,
        min_items_per_class: int,
        blob_service,
        training_data_container: str = "training-data",
    ) -> tuple[Optional[TrainingDatasetModel], Optional[str]]:
        dataset = self.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "staged":
            return None, "invalid_state"

        membership_count = (
            self.db.query(TrainingDatasetMembershipModel)
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .count()
        )
        if membership_count == 0:
            return None, "empty_membership"

        recheck_result, recheck_error = self.recheck_labels(
            dataset_id=dataset_id,
            blob_service=blob_service,
            training_data_container=training_data_container,
        )
        if recheck_error:
            return None, "verification_failed"
        if not recheck_result or not recheck_result.get("all_verified", False):
            return None, "missing_sidecars"

        per_class_counts = self.get_cumulative_class_counts(dataset_id)

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

        self.db.commit()
        self.db.refresh(dataset)
        return dataset, None

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

    def stage_dataset(
        self,
        *,
        dataset_id: str,
        blob_service,
        training_data_container: str = "training-data",
    ) -> tuple[Optional[TrainingDatasetModel], Optional[str]]:
        """Copy selected blobs to training-data and transition dataset from draft to staged."""
        dataset = self.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "draft":
            return None, "invalid_state"

        members = (
            self.db.query(ReviewCandidateModel)
            .join(
                TrainingDatasetMembershipModel,
                TrainingDatasetMembershipModel.candidate_id == ReviewCandidateModel.id,
            )
            .filter(TrainingDatasetMembershipModel.dataset_id == dataset_id)
            .all()
        )

        container_name = (training_data_container or "training-data").strip() or "training-data"

        try:
            blob_service.ensure_container(container_name)
            for candidate in members:
                source_container, source_blob = self._split_blob_path(candidate.blob_path)
                if not source_container or not source_blob:
                    return None, "invalid_blob_path"

                folder = self._resolve_training_folder(
                    candidate.operator_label or candidate.predicted_document_type
                )
                filename = source_blob.split("/")[-1]
                destination_blob = f"{folder}/{filename}"

                blob_service.copy_blob(
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

        self.db.commit()
        self.db.refresh(dataset)
        return dataset, None

    def recheck_labels(
        self,
        *,
        dataset_id: str,
        blob_service,
        training_data_container: str = "training-data",
    ) -> tuple[Optional[dict], Optional[str]]:
        """Scan blob sidecars for all docs in the dataset and transition to ready_for_retrain if all verified."""
        dataset = self.get_dataset_by_id(dataset_id)
        if not dataset:
            return None, "not_found"

        if dataset.status != "staged":
            return None, "invalid_state"

        operator_label_rows = (
            self.db.query(ReviewCandidateModel.operator_label)
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

        container_name = (training_data_container or "training-data").strip() or "training-data"

        results = []
        allowed_field_keys_by_doc_type: dict[str, tuple[set[str], Optional[str]]] = {}
        for doc_type in sorted(doc_types):
            prefix = f"{doc_type}/"
            blob_names = blob_service.list_blobs_by_prefix(container_name, prefix)
            pdf_blobs = [b for b in blob_names if b.lower().endswith(".pdf")]

            if doc_type not in allowed_field_keys_by_doc_type:
                fields_blob = f"{doc_type}/fields.json"
                try:
                    fields_payload = blob_service.download_blob_text(container_name, fields_blob)
                    allowed_keys = self._extract_allowed_field_keys(fields_payload)
                    allowed_field_keys_by_doc_type[doc_type] = (allowed_keys, None)
                except (AzureError, json.JSONDecodeError, TypeError, ValueError):
                    allowed_field_keys_by_doc_type[doc_type] = (set(), "fields.json missing or invalid")

            for blob_name in pdf_blobs:
                # ADI Studio generates sidecars with full filename: file.pdf.ocr.json and file.pdf.labels.json
                has_ocr = blob_service.blob_exists(container_name, f"{blob_name}.ocr.json")
                has_labels = blob_service.blob_exists(container_name, f"{blob_name}.labels.json")
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
                            labels_payload = blob_service.download_blob_text(container_name, labels_blob)
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
        self.db.commit()
        self.db.refresh(dataset)

        return {
            "all_verified": all_verified,
            "new_status": dataset.status,
            "results": results,
        }, None
