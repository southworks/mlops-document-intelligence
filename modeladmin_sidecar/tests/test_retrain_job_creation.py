# pylint: disable=wrong-import-position

import os
import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
)

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.main import create_modeladmin_sidecar_app
from modeladmin_sidecar.services.azure_blob_storage_service import AzureBlobStorageService


FIELDS_JSON_INVOICE = '{"fields": [{"fieldKey": "InvoiceDate"}, {"fieldKey": "VendorName"}]}'
LABELS_JSON_INVOICE = '{"labels": [{"label": "InvoiceDate"}, {"label": "VendorName"}]}'


def _create_client(tmp_path) -> TestClient:
    database_path = tmp_path / f"modeladmin-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    return TestClient(app)


def _create_candidate(client: TestClient, *, label: str, suffix: str) -> str:
    document_id = f"retrain-{suffix}-{uuid.uuid4()}"
    payload = {
        "document_id": document_id,
        "compose_model_id": "procurement-compose-model.v2",
        "idempotency_key": f"{document_id}:procurement-compose-model.v2",
        "blob_path": f"documents/{document_id}.pdf",
        "processed_blob_path": f"documents/{label}/{document_id}.json",
        "source_channel": "process-new-api",
        "predicted_document_type": label,
        "classification_confidence": 0.77,
        "has_low_confidence": False,
        "trigger_reason": "manual_review",
    }

    intake_response = client.post("/boundary/modeladmin/candidate-created", json=payload)
    assert intake_response.status_code == 200
    candidate_id = intake_response.json()["candidate_id"]

    label_response = client.post(
        f"/modeladmin/review-candidates/{candidate_id}/label",
        json={"label": label},
    )
    assert label_response.status_code == 200

    approve_response = client.post(
        f"/modeladmin/review-candidates/{candidate_id}/approve",
        json={},
    )
    assert approve_response.status_code == 200
    return candidate_id


def _create_dataset(client: TestClient, *, name: str, members: int = 5) -> str:
    candidate_ids = [
        _create_candidate(client, label="invoice", suffix=f"{name}-{index}")
        for index in range(members)
    ]

    create_response = client.post(
        "/modeladmin/training-datasets",
        json={
            "name": name,
            "created_by": "trainer@southworks.com",
            "candidate_ids": candidate_ids,
        },
    )
    assert create_response.status_code == 200
    return create_response.json()["item"]["id"]


def _stage_dataset_with_mocked_storage(client: TestClient, dataset_id: str) -> None:
    stage_blob_service = MagicMock(spec=AzureBlobStorageService)
    stage_blob_service.ensure_container.return_value = None
    stage_blob_service.copy_blob.return_value = None

    import modeladmin_sidecar.routes.training_datasets as route_module

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: stage_blob_service):
        stage_response = client.post(f"/modeladmin/training-datasets/{dataset_id}/stage")
    assert stage_response.status_code == 200


def _mark_ready_with_mocked_sidecars(client: TestClient, dataset_id: str) -> None:
    verify_blob_service = MagicMock(spec=AzureBlobStorageService)
    verify_blob_service.list_blobs_by_prefix.return_value = ["invoice/INV-001.pdf"]
    verify_blob_service.blob_exists.return_value = True

    def _download_blob_text(_container: str, blob_name: str) -> str:
        if blob_name.endswith("fields.json"):
            return FIELDS_JSON_INVOICE
        return LABELS_JSON_INVOICE

    verify_blob_service.download_blob_text.side_effect = _download_blob_text

    import modeladmin_sidecar.routes.training_datasets as route_module

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: verify_blob_service):
        ready_response = client.post(
            f"/modeladmin/training-datasets/{dataset_id}/mark-ready",
            json={},
        )
    assert ready_response.status_code == 200


def _mark_ready(client: TestClient, dataset_id: str) -> None:
    _stage_dataset_with_mocked_storage(client, dataset_id)
    _mark_ready_with_mocked_sidecars(client, dataset_id)


def test_create_retrain_job_from_ready_dataset_returns_201(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_dataset(client, name="ready-dataset")
        _mark_ready(client, dataset_id)

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/retrain", json={})
        assert response.status_code == 201

        body = response.json()
        assert body["success"] is True
        assert body["item"]["id"]
        assert body["item"]["training_dataset_id"] == dataset_id
        assert body["item"]["status"] in {"queued", "running", "failed"}


def test_create_retrain_job_from_draft_dataset_returns_409(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_dataset(client, name="draft-dataset")

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/retrain", json={})
        assert response.status_code == 409
        assert "ready_for_retrain" in response.json()["detail"]


def test_list_retrain_jobs_returns_all_jobs(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        dataset_id_1 = _create_dataset(client, name="jobs-a")
        _mark_ready(client, dataset_id_1)
        create_1 = client.post(f"/modeladmin/training-datasets/{dataset_id_1}/retrain", json={})
        assert create_1.status_code == 201
        job_id_1 = create_1.json()["item"]["id"]

        dataset_id_2 = _create_dataset(client, name="jobs-b")
        _mark_ready(client, dataset_id_2)
        create_2 = client.post(f"/modeladmin/training-datasets/{dataset_id_2}/retrain", json={})
        assert create_2.status_code == 201
        job_id_2 = create_2.json()["item"]["id"]

        response = client.get("/modeladmin/retrain-jobs")
        assert response.status_code == 200
        items = response.json()["items"]
        ids = {item["id"] for item in items}
        assert job_id_1 in ids
        assert job_id_2 in ids


def test_get_retrain_job_detail(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_dataset(client, name="job-detail")
        _mark_ready(client, dataset_id)
        create_response = client.post(f"/modeladmin/training-datasets/{dataset_id}/retrain", json={})
        assert create_response.status_code == 201
        job = create_response.json()["item"]

        detail_response = client.get(f"/modeladmin/retrain-jobs/{job['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["id"] == job["id"]
        assert detail["training_dataset_id"] == dataset_id
