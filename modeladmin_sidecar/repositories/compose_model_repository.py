"""Repository for compose model persistence."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import ComposeModelModel, ComposeModelExtractorModel


class ComposeModelRepository:
    """Data access layer for compose models (deployable model compositions)."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, compose_model_id: str) -> Optional[ComposeModelModel]:
        return self.db.query(ComposeModelModel).filter(ComposeModelModel.compose_model_id == compose_model_id).first()

    def get_active(self) -> Optional[ComposeModelModel]:
        return self.db.query(ComposeModelModel).filter(ComposeModelModel.is_active.is_(True)).first()

    def list_all(self) -> list[ComposeModelModel]:
        return (
            self.db.query(ComposeModelModel)
            .filter(ComposeModelModel.status.in_(["ready", "composing"]))
            .order_by(ComposeModelModel.created_at.desc(), ComposeModelModel.compose_model_id.desc())
            .all()
        )

    def list_by_dataset_version(self, dataset_version_id: str) -> list[ComposeModelModel]:
        return (
            self.db.query(ComposeModelModel)
            .filter(ComposeModelModel.dataset_version_id == dataset_version_id)
            .order_by(ComposeModelModel.created_at.desc())
            .all()
        )

    def create(
        self,
        *,
        compose_model_id: str,
        version_number: int,
        status: str = "composing",
        dataset_version_id: Optional[str] = None,
        classifier_model_id: Optional[str] = None,
        adi_model_name: Optional[str] = None,
    ) -> ComposeModelModel:
        model = ComposeModelModel(
            compose_model_id=compose_model_id,
            version_number=version_number,
            dataset_version_id=dataset_version_id,
            classifier_model_id=classifier_model_id,
            status=status,
            adi_model_name=adi_model_name,
            is_active=False,
            activated_at=None,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return model

    def activate(self, compose_model_id: str) -> Optional[ComposeModelModel]:
        """Activate a specific compose model and deactivate all others."""
        # Deactivate all currently active models
        active_models = self.db.query(ComposeModelModel).filter(ComposeModelModel.is_active.is_(True)).all()
        for model in active_models:
            model.is_active = False
            model.activated_at = None

        # Activate the specified model
        model = self.get_by_id(compose_model_id)
        if not model:
            return None
        model.is_active = True
        model.activated_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(model)
        return model

    def update_status(self, compose_model_id: str, status: str) -> Optional[ComposeModelModel]:
        model = self.get_by_id(compose_model_id)
        if not model:
            return None
        model.status = status
        self.db.commit()
        self.db.refresh(model)
        return model

    def add_extractor(self, compose_model_id: str, trained_model_id: str) -> ComposeModelExtractorModel:
        """Associate a trained model (extractor) with a compose model."""
        mapping = ComposeModelExtractorModel(compose_model_id=compose_model_id, trained_model_id=trained_model_id)
        self.db.add(mapping)
        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    def get_extractors(self, compose_model_id: str) -> list[str]:
        """Get list of trained_model_ids for extractors associated with a compose model."""
        mappings = (
            self.db.query(ComposeModelExtractorModel)
            .filter(ComposeModelExtractorModel.compose_model_id == compose_model_id)
            .all()
        )
        return [m.trained_model_id for m in mappings]
