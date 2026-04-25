"""Repository for trained model persistence."""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import TrainedModelModel


class TrainedModelRepository:
    """Data access layer for trained models (individual model artifacts from retrain pipeline)."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, trained_model_id: str) -> Optional[TrainedModelModel]:
        return self.db.query(TrainedModelModel).filter(TrainedModelModel.trained_model_id == trained_model_id).first()

    def get_by_dataset_version(self, dataset_version_id: str) -> list[TrainedModelModel]:
        return (
            self.db.query(TrainedModelModel)
            .filter(TrainedModelModel.dataset_version_id == dataset_version_id)
            .order_by(TrainedModelModel.created_at.desc())
            .all()
        )

    def get_by_dataset_version_and_type(self, dataset_version_id: str, model_type: str) -> Optional[TrainedModelModel]:
        return (
            self.db.query(TrainedModelModel)
            .filter(
                TrainedModelModel.dataset_version_id == dataset_version_id,
                TrainedModelModel.model_type == model_type,
            )
            .first()
        )

    def create(
        self,
        *,
        trained_model_id: str,
        model_type: str,
        version_number: int,
        dataset_version_id: str,
        status: str = "building",
        adi_operation_id: Optional[str] = None,
        adi_model_name: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TrainedModelModel:
        model = TrainedModelModel(
            trained_model_id=trained_model_id,
            model_type=model_type,
            version_number=version_number,
            dataset_version_id=dataset_version_id,
            status=status,
            adi_operation_id=adi_operation_id,
            adi_model_name=adi_model_name,
            error_message=error_message,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return model

    def update_status(self, trained_model_id: str, status: str, error_message: Optional[str] = None) -> Optional[TrainedModelModel]:
        model = self.get_by_id(trained_model_id)
        if not model:
            return None
        model.status = status
        if error_message is not None:
            model.error_message = error_message
        self.db.commit()
        self.db.refresh(model)
        return model

    def update_adi_model_name(self, trained_model_id: str, adi_model_name: str) -> Optional[TrainedModelModel]:
        model = self.get_by_id(trained_model_id)
        if not model:
            return None
        model.adi_model_name = adi_model_name
        self.db.commit()
        self.db.refresh(model)
        return model
