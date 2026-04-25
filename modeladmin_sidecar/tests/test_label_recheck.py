# pylint: disable=wrong-import-position

import json
import os
import uuid
from unittest.mock import MagicMock
from unittest.mock import patch

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


FIELDS_JSON_INVOICE = json.dumps(
    {
        "fields": [
            {"fieldKey": "InvoiceDate"},
            {"fieldKey": "VendorName"},
        ]
    }
)


def _labels_json(*field_keys: str) -> str:
    return json.dumps({"labels": [{"label": key} for key in field_keys]})


def _create_client(tmp_path) -> TestClient:
    database_path = tmp_path / f"modeladmin-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    return TestClient(app)


def _create_candidate(client: TestClient, *, label: str, suffix: str) -> str:
    document_id = f"recheck-{suffix}-{uuid.uuid4()}"
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


def _create_staged_dataset(client: TestClient, *, label: str = "invoice", count: int = 5) -> str:
    candidate_ids = [
        _create_candidate(client, label=label, suffix=str(i))
        for i in range(count)
    ]
    create_response = client.post(
        "/modeladmin/training-datasets",
        json={
            "name": "recheck-test-dataset",
            "created_by": "trainer@southworks.com",
            "candidate_ids": candidate_ids,
        },
    )
    assert create_response.status_code == 200
    dataset_id = create_response.json()["item"]["id"]

    stage_blob_service = MagicMock(spec=AzureBlobStorageService)
    stage_blob_service.ensure_container.return_value = None
    stage_blob_service.copy_blob.return_value = None

    import modeladmin_sidecar.routes.training_datasets as route_module

    with patch.object(route_module, "AzureBlobStorageService", lambda conn_str: stage_blob_service):
        stage_response = client.post(f"/modeladmin/training-datasets/{dataset_id}/stage")
    assert stage_response.status_code == 200
    assert stage_response.json()["item"]["status"] == "staged"

    return dataset_id


# ---------------------------------------------------------------------------
# Happy path: all sidecars present → verification succeeds, dataset stays staged
# ---------------------------------------------------------------------------

def test_recheck_happy_path_all_verified(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = [
            "invoices/INV-001.pdf",
            "invoices/INV-002.pdf",
        ]
        mock_blob_service.blob_exists.return_value = True

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate", "VendorName")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200

        body = response.json()
        assert body["all_verified"] is True
        assert body["new_status"] == "staged"
        assert len(body["results"]) == 2
        assert all(r["has_ocr"] and r["has_labels"] for r in body["results"])
        assert all(r["has_schema_match"] for r in body["results"])
        assert body["results"][0]["doc_type"] == "invoice"

        # Dataset should remain staged until mark-ready
        detail = client.get(f"/modeladmin/training-datasets/{dataset_id}").json()
        assert detail["item"]["status"] == "staged"

        # label_verification_status should be persisted
        saved = json.loads(detail["item"]["label_verification_status"])
        assert len(saved) == 2
        assert all(r["has_ocr"] and r["has_labels"] for r in saved)
        assert all(r["has_schema_match"] for r in saved)


# ---------------------------------------------------------------------------
# Failure path: missing sidecars → stays staged, returns failure table
# ---------------------------------------------------------------------------

def test_recheck_failure_path_missing_sidecars(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = [
            "invoices/INV-001.pdf",
            "invoices/INV-002.pdf",
        ]

        # INV-001 is fully labeled; INV-002 is missing its labels sidecar
        def blob_exists_side_effect(_container, blob_name):
            if "INV-002" in blob_name and blob_name.endswith(".labels.json"):
                return False
            return True

        mock_blob_service.blob_exists.side_effect = blob_exists_side_effect

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate", "VendorName")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200

        body = response.json()
        assert body["all_verified"] is False
        assert body["new_status"] == "staged"

        inv002 = next(r for r in body["results"] if r["filename"] == "INV-002.pdf")
        assert inv002["has_ocr"] is True
        assert inv002["has_labels"] is False

        # Dataset should still be staged
        detail = client.get(f"/modeladmin/training-datasets/{dataset_id}").json()
        assert detail["item"]["status"] == "staged"

        # label_verification_status persisted even on failure
        saved = json.loads(detail["item"]["label_verification_status"])
        assert any(not r["has_labels"] for r in saved)


def test_recheck_failure_path_missing_required_fields(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = [
            "invoice/INV-001.pdf",
        ]
        mock_blob_service.blob_exists.return_value = True

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200

        body = response.json()
        assert body["all_verified"] is False
        row = body["results"][0]
        assert row["has_schema_match"] is False
        assert row["missing_field_keys"] == ["VendorName"]
        assert row["unexpected_field_keys"] == []


def test_recheck_failure_path_unexpected_fields(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = [
            "invoice/INV-001.pdf",
        ]
        mock_blob_service.blob_exists.return_value = True

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate", "VendorName", "UnexpectedField")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200

        body = response.json()
        assert body["all_verified"] is False
        row = body["results"][0]
        assert row["has_schema_match"] is False
        assert row["missing_field_keys"] == []
        assert row["unexpected_field_keys"] == ["UnexpectedField"]


def test_recheck_failure_path_mixed_sidecar_and_schema(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = [
            "invoice/INV-001.pdf",
            "invoice/INV-002.pdf",
        ]

        def blob_exists_side_effect(_container, blob_name):
            if "INV-002" in blob_name and blob_name.endswith(".labels.json"):
                return False
            return True

        mock_blob_service.blob_exists.side_effect = blob_exists_side_effect

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200

        body = response.json()
        assert body["all_verified"] is False

        inv001 = next(r for r in body["results"] if r["filename"] == "INV-001.pdf")
        assert inv001["has_labels"] is True
        assert inv001["has_schema_match"] is False
        assert inv001["missing_field_keys"] == ["VendorName"]

        inv002 = next(r for r in body["results"] if r["filename"] == "INV-002.pdf")
        assert inv002["has_labels"] is False


# ---------------------------------------------------------------------------
# State guard: recheck on draft returns 409
# ---------------------------------------------------------------------------

def test_recheck_returns_409_for_draft(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_ids = [
            _create_candidate(client, label="invoice", suffix=str(i))
            for i in range(5)
        ]
        create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "draft-recheck-guard",
                "created_by": "trainer@southworks.com",
                "candidate_ids": candidate_ids,
            },
        )
        assert create_response.status_code == 200
        dataset_id = create_response.json()["item"]["id"]

        # Dataset is in draft — recheck should be rejected
        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 409
        assert "staged" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# State guard: recheck on ready_for_retrain returns 409
# ---------------------------------------------------------------------------

def test_recheck_returns_409_for_ready_for_retrain(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = ["invoices/INV-001.pdf"]
        mock_blob_service.blob_exists.return_value = True

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate", "VendorName")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        # First recheck succeeds but remains staged.
        first = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert first.status_code == 200
        assert first.json()["new_status"] == "staged"

        # mark-ready enforces sidecar verification and transitions state
        ready = client.post(
            f"/modeladmin/training-datasets/{dataset_id}/mark-ready",
            json={"min_items_per_class": 5},
        )
        assert ready.status_code == 200
        assert ready.json()["item"]["status"] == "ready_for_retrain"

        # Second recheck on ready_for_retrain should return 409
        second = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert second.status_code == 409
        assert "staged" in second.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET response includes label_verification_status (null if never rechecked)
# ---------------------------------------------------------------------------

def test_get_dataset_includes_label_verification_status_null_initially(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        detail = client.get(f"/modeladmin/training-datasets/{dataset_id}").json()
        assert "label_verification_status" in detail["item"]
        assert detail["item"]["label_verification_status"] is None


def test_recheck_uses_configurable_training_data_container(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRAINING_DATA_CONTAINER", "custom-training-container")

    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = ["invoices/INV-001.pdf"]
        mock_blob_service.blob_exists.return_value = True

        def download_blob_text_side_effect(_container, blob_name):
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_INVOICE
            return _labels_json("InvoiceDate", "VendorName")

        mock_blob_service.download_blob_text.side_effect = download_blob_text_side_effect

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200

        mock_blob_service.list_blobs_by_prefix.assert_called_with(
            "custom-training-container",
            "invoice/",
        )


def test_recheck_empty_scan_is_not_verified(tmp_path, monkeypatch) -> None:
    with _create_client(tmp_path) as client:
        dataset_id = _create_staged_dataset(client, label="invoice", count=5)

        mock_blob_service = MagicMock(spec=AzureBlobStorageService)
        mock_blob_service.list_blobs_by_prefix.return_value = []

        import modeladmin_sidecar.routes.training_datasets as route_module

        monkeypatch.setattr(
            route_module,
            "AzureBlobStorageService",
            lambda conn_str: mock_blob_service,
        )

        response = client.post(f"/modeladmin/training-datasets/{dataset_id}/recheck")
        assert response.status_code == 200
        body = response.json()
        assert body["all_verified"] is False
        assert body["new_status"] == "staged"

        mark_ready = client.post(
            f"/modeladmin/training-datasets/{dataset_id}/mark-ready",
            json={"min_items_per_class": 5},
        )
        assert mark_ready.status_code == 409
        assert "sidecars" in mark_ready.json()["detail"].lower()
