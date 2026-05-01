"""SQLAlchemy models for ModelAdmin service."""

# pylint: disable=not-callable

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from modeladmin_sidecar.database.connection import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class ReviewCandidateModel(Base):
    __tablename__ = "review_candidates"
    __table_args__ = (
        UniqueConstraint("document_id", "compose_model_id", name="uq_review_candidates_doc_compose_model"),
        Index("idx_review_candidates_status", "status"),
        Index("idx_review_candidates_doc_type", "predicted_document_type"),
        Index("idx_review_candidates_created", "created_at"),
        Index("idx_review_candidates_compose_model_id", "compose_model_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="new")
    blob_path = Column(String(512), nullable=False)
    processed_blob_path = Column(String(512), nullable=True)
    predicted_document_type = Column(String(50), nullable=True)
    classification_confidence = Column(Float, nullable=True)
    compose_model_id = Column(String(255), nullable=False)
    has_low_confidence = Column(Boolean, nullable=False, default=False)
    trigger_reason = Column(String(100), nullable=False)
    low_confidence_field_names = Column(Text, nullable=True)
    low_confidence_field_count = Column(Integer, nullable=True)
    source_channel = Column(String(50), nullable=True)
    original_filename = Column(String(255), nullable=True)
    operator_label = Column(String(50), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    error_details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TrainingDatasetModel(Base):
    __tablename__ = "training_datasets"
    __table_args__ = (
        Index("idx_training_datasets_status", "status"),
        Index("idx_training_datasets_created", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="draft")
    created_by = Column(String(100), nullable=False)
    version_number = Column(Integer, nullable=False, default=1)
    parent_dataset_id = Column(String(36), ForeignKey("training_datasets.id"), nullable=True)
    staged_at = Column(DateTime(timezone=True), nullable=True)
    label_verification_status = Column(Text, nullable=True)
    ready_at = Column(DateTime(timezone=True), nullable=True)
    ready_min_items_per_class = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TrainingDatasetMembershipModel(Base):
    __tablename__ = "training_dataset_memberships"
    __table_args__ = (
        UniqueConstraint("dataset_id", "candidate_id", name="uq_dataset_membership_candidate"),
        Index("idx_training_dataset_membership_dataset", "dataset_id"),
        Index("idx_training_dataset_membership_candidate", "candidate_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    dataset_id = Column(String(36), ForeignKey("training_datasets.id"), nullable=False)
    candidate_id = Column(String(36), ForeignKey("review_candidates.id"), nullable=False)
    compose_model_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# NOTE: RetrainJobModel is superseded by TrainingJobModel (PBI 4).
# It is retained for backward compatibility until existing retrain_jobs rows
# are migrated. Do not add new features here.
class RetrainJobModel(Base):
    __tablename__ = "retrain_jobs"
    __table_args__ = (
        Index("idx_retrain_jobs_status", "status"),
        Index("idx_retrain_jobs_dataset", "training_dataset_id"),
        Index("idx_retrain_jobs_submitted", "submitted_at"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    training_dataset_id = Column(String(36), ForeignKey("training_datasets.id"), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    adi_operation_id = Column(String(512), nullable=True)
    adi_model_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TrainedModelModel(Base):
    __tablename__ = "trained_models"
    __table_args__ = (
        Index("idx_trained_models_dataset_version", "dataset_version_id"),
        Index("idx_trained_models_status", "status"),
        Index("idx_trained_models_type", "model_type"),
    )

    trained_model_id = Column(String(255), primary_key=True)
    model_type = Column(String(100), nullable=False)
    version_number = Column(Integer, nullable=False)
    dataset_version_id = Column(String(36), ForeignKey("training_datasets.id"), nullable=True)
    status = Column(String(20), nullable=False, default="building")
    adi_operation_id = Column(String(512), nullable=True)
    adi_model_name = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ComposeModelModel(Base):
    __tablename__ = "compose_models"
    __table_args__ = (
        Index("idx_compose_models_status", "status"),
        Index("idx_compose_models_active", "is_active"),
        Index("idx_compose_models_dataset_version", "dataset_version_id"),
    )

    compose_model_id = Column(String(255), primary_key=True)
    version_number = Column(Integer, nullable=False)
    dataset_version_id = Column(String(36), ForeignKey("training_datasets.id"), nullable=True)
    classifier_model_id = Column(String(255), ForeignKey("trained_models.trained_model_id"), nullable=True)
    status = Column(String(20), nullable=False, default="composing")
    adi_model_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ComposeModelExtractorModel(Base):
    __tablename__ = "compose_model_extractors"
    __table_args__ = (
        UniqueConstraint("compose_model_id", "trained_model_id", name="uq_compose_model_extractor"),
        Index("idx_compose_model_extractors_compose", "compose_model_id"),
        Index("idx_compose_model_extractors_trained", "trained_model_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    compose_model_id = Column(String(255), ForeignKey("compose_models.compose_model_id"), nullable=False)
    trained_model_id = Column(String(255), ForeignKey("trained_models.trained_model_id"), nullable=False)


class ActiveModelConfigModel(Base):
    __tablename__ = "active_model_config"
    __table_args__ = (Index("idx_active_model_config_updated", "updated_at"),)

    id = Column(Integer, primary_key=True, default=1)
    active_model_id = Column(String(255), nullable=False)
    activated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )



class TrainingJobModel(Base):
    __tablename__ = "training_jobs"
    __table_args__ = (
        Index("idx_training_jobs_status", "status"),
        Index("idx_training_jobs_dataset_version", "dataset_version_id"),
        Index("idx_training_jobs_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    dataset_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("training_datasets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TrainingJobOperationModel(Base):
    __tablename__ = "training_job_operations"
    __table_args__ = (
        Index("idx_training_job_operations_job", "job_id"),
        Index("idx_training_job_operations_status", "status"),
        Index("idx_training_job_operations_type", "operation_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("training_jobs.id"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    adi_operation_id: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    adi_model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
