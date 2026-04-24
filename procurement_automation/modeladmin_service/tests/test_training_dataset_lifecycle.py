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

from modeladmin_service.config import get_modeladmin_service_settings
from modeladmin_service.main import create_modeladmin_service_app
from modeladmin_service.services.azure_blob_storage_service import AzureBlobStorageService


FIELDS_JSON_INVOICE = '{"fields": [{"fieldKey": "InvoiceDate"}, {"fieldKey": "VendorName"}]}'
LABELS_JSON_INVOICE = '{"labels": [{"label": "InvoiceDate"}, {"label": "VendorName"}]}'


def _create_client(tmp_path) -> TestClient:
    database_path = tmp_path / f"modeladmin-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_service_settings.cache_clear()
    app = create_modeladmin_service_app()
    return TestClient(app)


def _create_candidate(client: TestClient, *, label: str, suffix: str) -> str:
    document_id = f"dataset-{suffix}-{uuid.uuid4()}"
    payload = {
        "document_id": document_id,
        "compose_model_id": "procurement-compose-model.v2",
        "idempotency_key": f"{document_id}:procurement-compose-model.v2",
        "blob_path": f"documents/{document_id}.pdf",
        "processed_blob_path": f"documents/{label}/{document_id}.json",
        "source_channel": "process-new-api",
        "predicted_document_type": label,
        "classification_confidence": 0.75,
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


def _stage_dataset_with_mocked_storage(client: TestClient, dataset_id: str) -> None:
    stage_blob_service = MagicMock(spec=AzureBlobStorageService)
    stage_blob_service.ensure_container.return_value = None
    stage_blob_service.copy_blob.return_value = None

    import modeladmin_service.routes.training_datasets as route_module

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: stage_blob_service):
        stage_response = client.post(f"/modeladmin/training-datasets/{dataset_id}/stage")
    assert stage_response.status_code == 200


def _mark_ready_with_mocked_sidecars(client: TestClient, dataset_id: str, min_items_per_class: int = 1):
    verify_blob_service = MagicMock(spec=AzureBlobStorageService)
    verify_blob_service.list_blobs_by_prefix.return_value = ["invoice/INV-001.pdf"]
    verify_blob_service.blob_exists.return_value = True

    def _download_blob_text(_container: str, blob_name: str) -> str:
        if blob_name.endswith("fields.json"):
            return FIELDS_JSON_INVOICE
        return LABELS_JSON_INVOICE

    verify_blob_service.download_blob_text.side_effect = _download_blob_text

    import modeladmin_service.routes.training_datasets as route_module

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: verify_blob_service):
        return client.post(
            f"/modeladmin/training-datasets/{dataset_id}/mark-ready",
            json={"min_items_per_class": min_items_per_class},
        )


def test_training_dataset_lifecycle_create_list_get_and_mark_ready(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_ids = [
            _create_candidate(client, label="invoice", suffix=str(index))
            for index in range(5)
        ]

        create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "operator-curated-invoices",
                "created_by": "trainer@southworks.com",
                "candidate_ids": candidate_ids,
            },
        )
        assert create_response.status_code == 200
        create_body = create_response.json()
        dataset_id = create_body["item"]["id"]
        assert create_body["success"] is True
        assert create_body["item"]["status"] == "draft"
        assert create_body["item"]["membership_count"] == 5
        assert create_body["item"]["name"].startswith("operator-curated-invoices-")

        list_response = client.get("/modeladmin/training-datasets?limit=10")
        assert list_response.status_code == 200
        listed_ids = {item["id"] for item in list_response.json()["items"]}
        assert dataset_id in listed_ids

        detail_response = client.get(f"/modeladmin/training-datasets/{dataset_id}")
        assert detail_response.status_code == 200
        detail_body = detail_response.json()
        assert detail_body["item"]["id"] == dataset_id
        assert len(detail_body["membership"]) == 5
        assert {item["candidate_id"] for item in detail_body["membership"]} == set(candidate_ids)

        _stage_dataset_with_mocked_storage(client, dataset_id)

        ready_response = _mark_ready_with_mocked_sidecars(client, dataset_id)
        assert ready_response.status_code == 200
        ready_body = ready_response.json()
        assert ready_body["item"]["status"] == "ready_for_retrain"

        second_ready_response = _mark_ready_with_mocked_sidecars(client, dataset_id)
        assert second_ready_response.status_code == 409


def test_training_dataset_rejects_non_approved_candidates_and_class_minimum_failures(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        unapproved_document_id = f"dataset-unapproved-{uuid.uuid4()}"
        intake_response = client.post(
            "/boundary/modeladmin/candidate-created",
            json={
                "document_id": unapproved_document_id,
                "compose_model_id": "procurement-compose-model.v2",
                "idempotency_key": f"{unapproved_document_id}:procurement-compose-model.v2",
                "blob_path": f"documents/{unapproved_document_id}.pdf",
                "processed_blob_path": f"documents/invoice/{unapproved_document_id}.json",
                "source_channel": "process-new-api",
                "predicted_document_type": "invoice",
                "classification_confidence": 0.52,
                "has_low_confidence": True,
                "trigger_reason": "low_confidence",
            },
        )
        assert intake_response.status_code == 200
        unapproved_candidate_id = intake_response.json()["candidate_id"]

        invalid_create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "invalid-dataset",
                "created_by": "trainer@southworks.com",
                "candidate_ids": [unapproved_candidate_id],
            },
        )
        assert invalid_create_response.status_code == 409
        assert "approved_for_training" in invalid_create_response.json()["detail"]

        approved_candidate_ids = [
            _create_candidate(client, label="invoice", suffix=f"small-{index}")
            for index in range(2)
        ]
        create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "too-small-dataset",
                "created_by": "trainer@southworks.com",
                "candidate_ids": approved_candidate_ids,
            },
        )
        assert create_response.status_code == 200
        dataset_id = create_response.json()["item"]["id"]

        _stage_dataset_with_mocked_storage(client, dataset_id)

        ready_response = _mark_ready_with_mocked_sidecars(client, dataset_id, min_items_per_class=5)
        assert ready_response.status_code == 409
        assert "Per-class minimum" in ready_response.json()["detail"]


def test_training_dataset_member_removal_in_draft_and_mark_ready_gating(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_ids = [
            _create_candidate(client, label="invoice", suffix=f"remove-{index}")
            for index in range(2)
        ]

        create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "draft-removal-dataset",
                "created_by": "trainer@southworks.com",
                "candidate_ids": candidate_ids,
            },
        )
        assert create_response.status_code == 200
        dataset_id = create_response.json()["item"]["id"]

        remove_response = client.delete(
            f"/modeladmin/training-datasets/{dataset_id}/members/{candidate_ids[0]}"
        )
        assert remove_response.status_code == 200
        remove_body = remove_response.json()
        assert remove_body["success"] is True
        assert remove_body["item"]["membership_count"] == 1

        remove_last_response = client.delete(
            f"/modeladmin/training-datasets/{dataset_id}/members/{candidate_ids[1]}"
        )
        assert remove_last_response.status_code == 200
        assert remove_last_response.json()["item"]["membership_count"] == 0

        _stage_dataset_with_mocked_storage(client, dataset_id)

        mark_empty_response = client.post(
            f"/modeladmin/training-datasets/{dataset_id}/mark-ready",
            json={},
        )
        assert mark_empty_response.status_code == 409
        assert "cannot be empty" in mark_empty_response.json()["detail"]


def test_training_dataset_member_removal_is_blocked_after_ready(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_ids = [
            _create_candidate(client, label="invoice", suffix=f"ready-{index}")
            for index in range(5)
        ]

        create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "ready-removal-immutable",
                "created_by": "trainer@southworks.com",
                "candidate_ids": candidate_ids,
            },
        )
        assert create_response.status_code == 200
        dataset_id = create_response.json()["item"]["id"]

        _stage_dataset_with_mocked_storage(client, dataset_id)

        ready_response = _mark_ready_with_mocked_sidecars(client, dataset_id, min_items_per_class=1)
        assert ready_response.status_code == 200
        assert ready_response.json()["item"]["status"] == "ready_for_retrain"

        remove_after_ready = client.delete(
            f"/modeladmin/training-datasets/{dataset_id}/members/{candidate_ids[0]}"
        )
        assert remove_after_ready.status_code == 409
        assert "non-draft" in remove_after_ready.json()["detail"]

        detail_response = client.get(f"/modeladmin/training-datasets/{dataset_id}")
        assert detail_response.status_code == 200
        assert len(detail_response.json()["membership"]) == 5
