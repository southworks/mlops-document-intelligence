# pylint: disable=wrong-import-position

import os
import uuid
from unittest.mock import MagicMock, patch

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
    Base,
    ComposeModelCacheModel,
    TrainingJobModel,
    TrainingJobOperationModel,
)
from modeladmin_service.main import create_modeladmin_service_app
from modeladmin_service.services.azure_blob_storage_service import AzureBlobStorageService


FIELDS_JSON_INVOICE = '{"fields": [{"fieldKey": "InvoiceDate"}, {"fieldKey": "VendorName"}]}'
LABELS_JSON_INVOICE = '{"labels": [{"label": "InvoiceDate"}, {"label": "VendorName"}]}'


def _create_test_setup(tmp_path):
    """Create a TestClient with an isolated SQLite database."""
    os.environ["ADI_ENDPOINT"] = "https://test-adi.cognitiveservices.azure.com/"
    os.environ["ADI_KEY"] = "test-key-12345"

    database_path = tmp_path / f"modeladmin-trainjob-{uuid.uuid4()}.db"
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


def _create_candidate(client: TestClient, *, label: str, suffix: str) -> str:
    """Create a candidate through intake → label → approve."""
    document_id = f"train-{suffix}-{uuid.uuid4()}"
    payload = {
        "document_id": document_id,
        "compose_model_id": "procurement-compose-model.v1",
        "idempotency_key": f"{document_id}:procurement-compose-model.v1",
        "blob_path": f"documents/{document_id}.pdf",
        "processed_blob_path": f"documents/{label}/{document_id}.json",
        "source_channel": "process-new-api",
        "predicted_document_type": label,
        "classification_confidence": 0.85,
        "has_low_confidence": False,
        "trigger_reason": "manual_review",
    }
    intake = client.post("/boundary/modeladmin/candidate-created", json=payload)
    assert intake.status_code == 200
    candidate_id = intake.json()["candidate_id"]

    label_r = client.post(
        f"/modeladmin/review-candidates/{candidate_id}/label",
        json={"label": label},
    )
    assert label_r.status_code == 200

    approve_r = client.post(
        f"/modeladmin/review-candidates/{candidate_id}/approve",
        json={},
    )
    assert approve_r.status_code == 200
    return candidate_id


def _create_ready_dataset(client: TestClient, *, name: str, label: str = "invoice") -> str:
    """Create a dataset from 5 candidates and transition it to ready_for_retrain."""
    candidate_ids = [
        _create_candidate(client, label=label, suffix=f"{name}-{i}")
        for i in range(5)
    ]
    create_r = client.post(
        "/modeladmin/training-datasets",
        json={
            "name": name,
            "created_by": "trainer@southworks.com",
            "candidate_ids": candidate_ids,
        },
    )
    assert create_r.status_code == 200
    dataset_id = create_r.json()["item"]["id"]

    stage_blob_service = MagicMock(spec=AzureBlobStorageService)
    stage_blob_service.ensure_container.return_value = None
    stage_blob_service.copy_blob.return_value = None

    import modeladmin_service.routes.training_datasets as route_module

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: stage_blob_service):
        stage_r = client.post(f"/modeladmin/training-datasets/{dataset_id}/stage")
    assert stage_r.status_code == 200

    verify_blob_service = MagicMock(spec=AzureBlobStorageService)
    verify_blob_service.list_blobs_by_prefix.return_value = ["invoice/INV-001.pdf"]
    verify_blob_service.blob_exists.return_value = True

    def _download_blob_text(_container: str, blob_name: str) -> str:
        if blob_name.endswith("fields.json"):
            return FIELDS_JSON_INVOICE
        return LABELS_JSON_INVOICE

    verify_blob_service.download_blob_text.side_effect = _download_blob_text

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: verify_blob_service):
        ready_r = client.post(
            f"/modeladmin/training-datasets/{dataset_id}/mark-ready",
            json={},
        )
    assert ready_r.status_code == 200
    return dataset_id


# ---------------------------------------------------------------------------
# Test 1: POST start-training on ready dataset → 201 + job created
# ---------------------------------------------------------------------------

def test_start_training_on_ready_dataset_returns_201(tmp_path) -> None:
    client, _ = _create_test_setup(tmp_path)
    dataset_id = _create_ready_dataset(client, name="start-train-ready")

    with (
        patch(
            "modeladmin_service.routes.training_jobs.AzureBlobStorageService.get_container_sas_url",
            return_value="https://devstoreaccount1.blob.core.windows.net/training?sv=sas",
        ),
        patch(
            "modeladmin_service.routes.training_jobs.AzureBlobStorageService.list_available_doc_type_folders",
            return_value=["invoice"],
        ),
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.begin_build_document_model",
            return_value="https://adi.example.com/ops/ext-op-1",
        ),
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.begin_build_classifier",
            return_value="https://adi.example.com/ops/cls-op-1",
        ),
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.document_model_exists",
            return_value=False,
        ),
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.classifier_exists",
            return_value=False,
        ),
    ):
        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/start-training")

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["item"]["status"] == "building_components"
    ops = body["item"]["operations"]
    assert any(op["operation_type"] == "extractor" for op in ops)
    assert any(op["operation_type"] == "classifier" for op in ops)


# ---------------------------------------------------------------------------
# Test 2: POST start-training on non-ready dataset → 409
# ---------------------------------------------------------------------------

def test_start_training_on_non_ready_dataset_returns_409(tmp_path) -> None:
    client, _ = _create_test_setup(tmp_path)

    candidate_ids = [
        _create_candidate(client, label="invoice", suffix=f"draft-{i}")
        for i in range(5)
    ]
    create_r = client.post(
        "/modeladmin/training-datasets",
        json={
            "name": "draft-dataset",
            "created_by": "trainer@southworks.com",
            "candidate_ids": candidate_ids,
        },
    )
    assert create_r.status_code == 200
    dataset_id = create_r.json()["item"]["id"]

    response = client.post(f"/modeladmin/training-datasets/{dataset_id}/start-training")
    assert response.status_code == 409
    assert "ready_for_retrain" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test 3: GET job polls component ops; when all succeed, compose is triggered
# ---------------------------------------------------------------------------

def test_get_training_job_triggers_compose_when_components_complete(tmp_path) -> None:
    client, SessionLocal = _create_test_setup(tmp_path)
    dataset_id = _create_ready_dataset(client, name="poll-compose-ds")

    session = SessionLocal()
    job = TrainingJobModel(
        id=str(uuid.uuid4()),
        dataset_version_id=dataset_id,
        status="building_components",
    )
    session.add(job)
    extractor_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="extractor",
        doc_type="invoice",
        status="running",
        adi_operation_id="https://adi.example.com/ops/ext-poll-1",
    )
    extractor_po_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="extractor",
        doc_type="purchase-order",
        status="running",
        adi_operation_id="https://adi.example.com/ops/ext-poll-2",
    )
    classifier_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="classifier",
        status="running",
        adi_operation_id="https://adi.example.com/ops/cls-poll-1",
    )
    session.add_all([extractor_op, extractor_po_op, classifier_op])
    session.commit()
    job_id = job.id
    session.close()

    with (
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.get_operation_status",
            side_effect=lambda operation_id: (
                {"status": "succeeded", "model_id": "procurement-invoice-extractor.v1"}
                if operation_id.endswith("ext-poll-1")
                else (
                    {"status": "succeeded", "model_id": "procurement-purchase-order-extractor.v1"}
                    if operation_id.endswith("ext-poll-2")
                    else {"status": "succeeded", "model_id": "procurement-classifier.v1"}
                )
            ),
        ),
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.begin_compose_model",
            return_value="https://adi.example.com/ops/compose-poll-1",
        ),
        patch(
            "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.get_compose_status",
            return_value=("running", None, None),
        ),
    ):
        response = client.get(f"/modeladmin/training-jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "building_compose"
    assert any(op["operation_type"] == "compose" for op in body["operations"])


# ---------------------------------------------------------------------------
# Test 4: GET job completes compose; ComposeModelCacheModel row created
# ---------------------------------------------------------------------------

def test_get_training_job_completes_and_creates_compose_model_cache(tmp_path) -> None:
    client, SessionLocal = _create_test_setup(tmp_path)
    dataset_id = _create_ready_dataset(client, name="compose-complete-ds")

    session = SessionLocal()
    job = TrainingJobModel(
        id=str(uuid.uuid4()),
        dataset_version_id=dataset_id,
        status="building_compose",
    )
    session.add(job)
    extractor_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="extractor",
        doc_type="invoice",
        status="completed",
        adi_model_id="procurement-invoice-extractor.v1",
    )
    classifier_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="classifier",
        status="completed",
        adi_model_id="procurement-classifier.v1",
    )
    compose_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="compose",
        status="running",
        adi_operation_id="https://adi.example.com/ops/compose-complete-1",
    )
    session.add_all([extractor_op, classifier_op, compose_op])
    session.commit()
    job_id = job.id
    session.close()

    with patch(
        "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.get_compose_status",
        return_value=("succeeded", "procurement-compose.v1", None),
    ):
        response = client.get(f"/modeladmin/training-jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"

    # Verify ComposeModelCacheModel row was inserted
    verify_session = SessionLocal()
    cache_row = (
        verify_session.query(ComposeModelCacheModel)
        .filter(ComposeModelCacheModel.model_id == "procurement-compose.v1")
        .first()
    )
    verify_session.close()
    assert cache_row is not None


# ---------------------------------------------------------------------------
# Test 5: GET job marks failed when a component operation fails
# ---------------------------------------------------------------------------

def test_get_training_job_marks_failed_on_operation_error(tmp_path) -> None:
    client, SessionLocal = _create_test_setup(tmp_path)
    dataset_id = _create_ready_dataset(client, name="fail-op-ds")

    session = SessionLocal()
    job = TrainingJobModel(
        id=str(uuid.uuid4()),
        dataset_version_id=dataset_id,
        status="building_components",
    )
    session.add(job)
    extractor_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="extractor",
        doc_type="invoice",
        status="running",
        adi_operation_id="https://adi.example.com/ops/ext-fail-1",
    )
    classifier_op = TrainingJobOperationModel(
        id=str(uuid.uuid4()),
        job_id=job.id,
        operation_type="classifier",
        status="running",
        adi_operation_id="https://adi.example.com/ops/cls-fail-1",
    )
    session.add_all([extractor_op, classifier_op])
    session.commit()
    job_id = job.id
    session.close()

    with patch(
        "modeladmin_service.routes.training_jobs.DocumentIntelligenceService.get_operation_status",
        return_value={"status": "failed", "error": "ADI model build failed"},
    ):
        response = client.get(f"/modeladmin/training-jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]
