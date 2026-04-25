"""Repository for active model configuration persistence."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_sidecar.database.models import ActiveModelConfigModel


class ActiveModelConfigRepository:
    """Data access layer for active model configuration."""

    def __init__(self, db: Session):
        self.db = db

    def get_active_model_config(self) -> Optional[ActiveModelConfigModel]:
        return self.db.query(ActiveModelConfigModel).filter(ActiveModelConfigModel.id == 1).first()

    def upsert_active_model_config(
        self,
        *,
        active_model_id: str,
    ) -> ActiveModelConfigModel:
        config = self.get_active_model_config()
        if not config:
            config = ActiveModelConfigModel(
                id=1,
                active_model_id=active_model_id,
            )
            self.db.add(config)
        else:
            config.active_model_id = active_model_id
            config.activated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(config)
        return config
