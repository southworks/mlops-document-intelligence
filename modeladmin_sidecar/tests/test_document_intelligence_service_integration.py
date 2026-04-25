# pylint: disable=wrong-import-position

import os
import uuid

import pytest

from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService


def _component_model_ids_from_env() -> list[str]:
    raw = os.getenv("ADI_COMPONENT_MODEL_IDS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("ADI_ENDPOINT") or not os.getenv("ADI_KEY") or len(_component_model_ids_from_env()) < 2,
    reason="Requires ADI_ENDPOINT, ADI_KEY and at least two ADI_COMPONENT_MODEL_IDS",
)
def test_begin_compose_model_returns_operation_id() -> None:
    service = DocumentIntelligenceService()
    component_model_ids = _component_model_ids_from_env()[:2]

    operation_id = service.begin_compose_model(
        component_model_ids=component_model_ids,
        model_name=f"ci-compose-{str(uuid.uuid4())[:8]}",
    )

    assert isinstance(operation_id, str)
    assert operation_id.strip() != ""
