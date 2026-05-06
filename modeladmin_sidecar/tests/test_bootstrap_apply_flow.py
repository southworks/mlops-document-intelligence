# pylint: disable=wrong-import-position

import os
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
)

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database.connection import get_db
from modeladmin_sidecar.database.models import (
    ActiveModelConfigModel,
    Base,
    ComposeModelExtractorModel,
    ComposeModelModel,
    TrainedModelModel,
)
from modeladmin_sidecar.main import create_modeladmin_sidecar_app


def _create_test_setup(tmp_path):
    os.environ["ADI_ENDPOINT"] = "https://test-adi.cognitiveservices.azure.com/"
    os.environ["ADI_KEY"] = "test-key-12345"

    database_path = tmp_path / f"modeladmin-bootstrap-{uuid.uuid4()}.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    os.environ["MODELADMIN_DATABASE_URL"] = database_url
    get_modeladmin_sidecar_settings.cache_clear()

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    app = create_modeladmin_sidecar_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, SessionLocal


def _payload() -> dict:
    return {
        "compose_model_id": "compose-v1",
        "classifier_model_id": "classifier-v1",
        "extractors": {
            "invoice": "invoice-extractor-v1",
            "purchase-order": "po-extractor-v1",
        },
        "activate": True,
    }


def test_reset_demo_happy_path_creates_records_and_activates(tmp_path):
    client, SessionLocal = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_sidecar.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=True,
        ),
        patch(
            "modeladmin_sidecar.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=True,
        ),
    ):
        response = client.post("/admin/reset-demo", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["compose_model_id"] == "compose-v1"
    assert body["activated"] is True
    assert body["extractor_count"] == 2


def test_reset_demo_is_stable_on_rerun(tmp_path):
    """Calling reset-demo twice produces the same seeded state (tables are dropped and recreated each time)."""
    client, SessionLocal = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_sidecar.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=True,
        ),
        patch(
            "modeladmin_sidecar.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=True,
        ),
    ):
        response_1 = client.post("/admin/reset-demo", json=_payload())
        response_2 = client.post("/admin/reset-demo", json=_payload())

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert response_1.json()["compose_model_id"] == response_2.json()["compose_model_id"]


def test_reset_demo_validation_failure_returns_409_and_writes_nothing(tmp_path):
    client, SessionLocal = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_sidecar.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=False,
        ),
        patch(
            "modeladmin_sidecar.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=False,
        ),
    ):
        response = client.post("/admin/reset-demo", json=_payload())

    assert response.status_code == 409

    session = SessionLocal()
    try:
        assert session.query(ComposeModelModel).count() == 0
        assert session.query(ActiveModelConfigModel).count() == 0
        assert session.query(ComposeModelExtractorModel).count() == 0
        assert session.query(TrainedModelModel).count() == 0
    finally:
        session.close()
