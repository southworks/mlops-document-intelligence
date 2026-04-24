# pylint: disable=wrong-import-position

import os
import uuid
from datetime import datetime, timedelta, timezone
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
    RetrainJobModel,
)
from modeladmin_service.main import create_modeladmin_service_app


def _create_test_setup(tmp_path):
    """Create a test client with a shared database for setup and testing."""
    # Set ADI configuration so sync logic runs
    os.environ["ADI_ENDPOINT"] = "https://test-adi.cognitiveservices.azure.com/"
    os.environ["ADI_KEY"] = "test-key-12345"
    
    database_path = tmp_path / f"modeladmin-lifecycle-{uuid.uuid4()}.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    os.environ["MODELADMIN_DATABASE_URL"] = database_url
    get_modeladmin_service_settings.cache_clear()

    # Create engine and tables
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    app = create_modeladmin_service_app()

    # Override get_db to use our test session
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    return client, SessionLocal


def test_get_running_job_syncs_succeeded_from_adi(tmp_path) -> None:
    """Test that GET /retrain-jobs/{job_id} syncs succeeded status from ADI."""
    client, SessionLocal = _create_test_setup(tmp_path)

    # Create a job directly in running state
    session = SessionLocal()
    job = RetrainJobModel(
        id=str(uuid.uuid4()),
        training_dataset_id=str(uuid.uuid4()),
        status="running",
        adi_operation_id="test-operation-token-123",
    )
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    with patch(
        "modeladmin_service.routes.retrain_jobs.DocumentIntelligenceService.get_compose_status",
        return_value=("succeeded", "retrain-compose-model.v1", None),
    ):
        # GET the job
        response = client.get(f"/modeladmin/retrain-jobs/{job_id}")
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "succeeded"
        assert body["adi_model_id"] == "retrain-compose-model.v1"


def test_get_running_job_syncs_failed_from_adi(tmp_path) -> None:
    """Test that GET /retrain-jobs/{job_id} syncs failed status from ADI."""
    client, SessionLocal = _create_test_setup(tmp_path)

    # Create a job directly in running state
    session = SessionLocal()
    job = RetrainJobModel(
        id=str(uuid.uuid4()),
        training_dataset_id=str(uuid.uuid4()),
        status="running",
        adi_operation_id="test-operation-token-456",
    )
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    with patch(
        "modeladmin_service.routes.retrain_jobs.DocumentIntelligenceService.get_compose_status",
        return_value=("failed", None, "ADI operation failed"),
    ):
        # GET the job
        response = client.get(f"/modeladmin/retrain-jobs/{job_id}")
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "failed"
        assert body["error_message"] == "ADI operation failed"


def test_get_terminal_job_does_not_call_adi(tmp_path) -> None:
    """Test that GET /retrain-jobs/{job_id} does NOT call ADI for succeeded jobs."""
    client, SessionLocal = _create_test_setup(tmp_path)

    # Create a job already in succeeded state
    session = SessionLocal()
    job = RetrainJobModel(
        id=str(uuid.uuid4()),
        training_dataset_id=str(uuid.uuid4()),
        status="succeeded",
        adi_model_id="retrain-model.v1",
    )
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    with patch(
        "modeladmin_service.routes.retrain_jobs.DocumentIntelligenceService"
    ) as mock_adi_service:
        # GET the job
        response = client.get(f"/modeladmin/retrain-jobs/{job_id}")
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "succeeded"

        # Assert ADI service was NOT instantiated
        mock_adi_service.assert_not_called()


def test_get_queued_job_does_not_call_adi(tmp_path) -> None:
    """Test that GET /retrain-jobs/{job_id} does NOT call ADI for queued jobs."""
    client, SessionLocal = _create_test_setup(tmp_path)

    # Create a job in queued state (no adi_operation_id yet)
    session = SessionLocal()
    job = RetrainJobModel(
        id=str(uuid.uuid4()),
        training_dataset_id=str(uuid.uuid4()),
        status="queued",
    )
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    with patch(
        "modeladmin_service.routes.retrain_jobs.DocumentIntelligenceService"
    ) as mock_adi_service:
        # GET the job
        response = client.get(f"/modeladmin/retrain-jobs/{job_id}")
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "queued"

        # Assert ADI service was NOT instantiated
        mock_adi_service.assert_not_called()


def test_activate_model_id_sets_active_model_and_returns_200(tmp_path) -> None:
    client, SessionLocal = _create_test_setup(tmp_path)

    session = SessionLocal()
    session.add(
        ComposeModelModel(
            compose_model_id="compose-live-v3",
            version_number=3,
            status="ready",
            dataset_version_id=None,
            classifier_model_id="classifier-v3",
            is_active=False,
        )
    )
    session.commit()
    session.close()

    activate_response = client.post("/modeladmin/models/compose-live-v3/activate")
    assert activate_response.status_code == 200

    activate_body = activate_response.json()
    assert activate_body["success"] is True
    assert activate_body["item"]["active_model_id"] == "compose-live-v3"

    active_response = client.get("/modeladmin/models/active")
    assert active_response.status_code == 200
    active_body = active_response.json()
    assert active_body["item"]["active_model_id"] == "compose-live-v3"


def test_activate_model_id_not_found_returns_404(tmp_path) -> None:
    client, _ = _create_test_setup(tmp_path)

    response = client.post("/modeladmin/models/compose-missing/activate")
    assert response.status_code == 404
    assert response.json()["detail"] == "compose model not found: compose-missing"


def test_activate_model_id_unavailable_returns_409(tmp_path) -> None:
    client, SessionLocal = _create_test_setup(tmp_path)

    session = SessionLocal()
    session.add(
        ComposeModelModel(
            compose_model_id="compose-unavailable",
            version_number=1,
            status="failed",
            dataset_version_id=None,
            classifier_model_id="classifier-vx",
            is_active=False,
        )
    )
    session.commit()
    session.close()

    response = client.post("/modeladmin/models/compose-unavailable/activate")
    assert response.status_code == 409
    assert response.json()["detail"] == "compose model is not ready for activation"


def test_get_active_model_returns_404_when_not_configured(tmp_path) -> None:
    client, _ = _create_test_setup(tmp_path)

    response = client.get("/modeladmin/models/active")
    assert response.status_code == 404


def test_list_compose_models_returns_latest_first_with_active_flag(tmp_path) -> None:
    client, SessionLocal = _create_test_setup(tmp_path)

    session = SessionLocal()
    now = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)

    latest_job = RetrainJobModel(
        id=str(uuid.uuid4()),
        training_dataset_id=str(uuid.uuid4()),
        status="succeeded",
        adi_model_id="compose-latest",
    )
    session.add(latest_job)
    session.flush()

    session.add_all(
        [
            ComposeModelModel(
                compose_model_id="compose-old",
                version_number=1,
                status="ready",
                created_at=now - timedelta(days=2),
                classifier_model_id="classifier-old",
                is_active=False,
            ),
            ComposeModelModel(
                compose_model_id="compose-latest",
                version_number=2,
                status="ready",
                created_at=now,
                classifier_model_id="classifier-latest",
                is_active=True,
            ),
            ComposeModelModel(
                compose_model_id="compose-hidden",
                version_number=3,
                status="failed",
                created_at=now + timedelta(days=1),
                classifier_model_id="classifier-hidden",
                is_active=False,
            ),
        ]
    )

    session.add_all(
        [
            ComposeModelExtractorModel(
                compose_model_id="compose-old",
                trained_model_id="invoice-old",
            ),
            ComposeModelExtractorModel(
                compose_model_id="compose-latest",
                trained_model_id="invoice-latest",
            ),
            ComposeModelExtractorModel(
                compose_model_id="compose-latest",
                trained_model_id="po-latest",
            ),
        ]
    )

    session.add(
        ActiveModelConfigModel(
            id=1,
            active_model_id="compose-latest",
        )
    )
    session.commit()
    session.close()

    response = client.get("/modeladmin/models/compose")
    assert response.status_code == 200

    items = response.json()["items"]
    assert [item["model_id"] for item in items] == ["compose-latest", "compose-old"]
    assert items[0]["is_active"] is True
    assert items[0]["extractor_models"] == ["invoice-latest", "po-latest"]
    assert items[1]["is_active"] is False


def test_legacy_retrain_job_activation_endpoint_is_removed(tmp_path) -> None:
    client, _ = _create_test_setup(tmp_path)

    response = client.post(f"/modeladmin/retrain-jobs/{uuid.uuid4()}/activate")
    assert response.status_code == 404
