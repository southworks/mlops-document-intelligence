"""Compose model cache repository used by training job orchestration (PBI 4)."""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from modeladmin_service.database.models import ComposeModelCacheModel


class ComposeModelCacheRepository:
    """Upserts compose model cache entries produced by the training job pipeline."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_compose_model(
        self,
        *,
        model_id: str,
        adi_created_at: datetime,
        classifier_model_id: Optional[str],
        extractor_models: list[str],
        is_available: bool = True,
    ) -> ComposeModelCacheModel:
        """Insert or update a compose model cache record."""
        cache = (
            self.db.query(ComposeModelCacheModel)
            .filter(ComposeModelCacheModel.model_id == model_id)
            .first()
        )

        if cache is None:
            cache = ComposeModelCacheModel(
                model_id=model_id,
                classifier_model_id=classifier_model_id,
                is_available=is_available,
            )
            self.db.add(cache)
        else:
            cache.classifier_model_id = classifier_model_id
            cache.is_available = is_available

        self.db.commit()
        self.db.refresh(cache)
        return cache
