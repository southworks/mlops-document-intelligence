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

from modeladmin_service.config import get_modeladmin_service_settings
from modeladmin_service.database.connection import get_db
from modeladmin_service.database.models import (
    ActiveModelConfigModel,
    Base,
    ComposeModelExtractorModel,
    ComposeModelModel,
    TrainedModelModel,
)
from modeladmin_service.main import create_modeladmin_service_app


def _create_test_setup(tmp_path):
    os.environ["ADI_ENDPOINT"] = "https://test-adi.cognitiveservices.azure.com/"
    os.environ["ADI_KEY"] = "test-key-12345"

    database_path = tmp_path / f"modeladmin-bootstrap-{uuid.uuid4()}.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    os.environ["MODELADMIN_DATABASE_URL"] = database_url
    get_modeladmin_service_settings.cache_clear()

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    app = create_modeladmin_service_app()

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


def test_bootstrap_validate_endpoint_returns_missing_ids(tmp_path):
    client, _ = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=False,
        ),
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=False,
        ),
    ):
        response = client.post("/modeladmin/models/bootstrap/validate", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert len(body["missing_model_ids"]) > 0


def test_bootstrap_apply_happy_path_creates_records_and_activates(tmp_path):
    client, SessionLocal = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=True,
        ),
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=True,
        ),
    ):
        response = client.post("/modeladmin/models/bootstrap/apply", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["compose_model_id"] == "compose-v1"
    assert body["activated"] is True

    session = SessionLocal()
    try:
        compose = session.query(ComposeModelModel).filter_by(compose_model_id="compose-v1").first()
        assert compose is not None
        assert compose.status == "ready"
        assert compose.is_active is True

        active = session.query(ActiveModelConfigModel).first()
        assert active is not None
        assert active.active_model_id == "compose-v1"

        trained_ids = {
            row.trained_model_id
            for row in session.query(TrainedModelModel).all()
        }
        assert trained_ids == {"classifier-v1", "invoice-extractor-v1", "po-extractor-v1"}

        mappings = session.query(ComposeModelExtractorModel).all()
        assert len(mappings) == 2
    finally:
        session.close()


def test_bootstrap_apply_is_idempotent_on_rerun(tmp_path):
    client, SessionLocal = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=True,
        ),
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=True,
        ),
    ):
        response_1 = client.post("/modeladmin/models/bootstrap/apply", json=_payload())
        response_2 = client.post("/modeladmin/models/bootstrap/apply", json=_payload())

    assert response_1.status_code == 200
    assert response_2.status_code == 200

    session = SessionLocal()
    try:
        assert session.query(ComposeModelModel).count() == 1
        assert session.query(ActiveModelConfigModel).count() == 1
        assert session.query(ComposeModelExtractorModel).count() == 2
        assert session.query(TrainedModelModel).count() == 3
    finally:
        session.close()


def test_bootstrap_apply_validation_failure_writes_nothing(tmp_path):
    client, SessionLocal = _create_test_setup(tmp_path)

    with (
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.document_model_exists",
            return_value=False,
        ),
        patch(
            "modeladmin_service.services.document_intelligence_service.DocumentIntelligenceService.classifier_exists",
            return_value=False,
        ),
    ):
        response = client.post("/modeladmin/models/bootstrap/apply", json=_payload())

    assert response.status_code == 409

    session = SessionLocal()
    try:
        assert session.query(ComposeModelModel).count() == 0
        assert session.query(ActiveModelConfigModel).count() == 0
        assert session.query(ComposeModelExtractorModel).count() == 0
        assert session.query(TrainedModelModel).count() == 0
    finally:
        session.close()
