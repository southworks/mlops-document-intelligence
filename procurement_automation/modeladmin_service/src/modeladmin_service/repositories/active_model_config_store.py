"""Service-owned persistence adapter for active model configuration."""

from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_service.database.models import ActiveModelConfigModel
from modeladmin_service.repositories.active_model_config_repository import ActiveModelConfigRepository


class ActiveModelConfigStore:
    """ModelAdmin service persistence boundary for active model configuration."""

    def __init__(self, db: Session):
        self._repo = ActiveModelConfigRepository(db)

    def get_active_model_config(self) -> Optional[ActiveModelConfigModel]:
        return self._repo.get_active_model_config()

    def upsert_active_model_config(
        self,
        *,
        active_model_id: str,
    ) -> ActiveModelConfigModel:
        return self._repo.upsert_active_model_config(
            active_model_id=active_model_id,
        )
