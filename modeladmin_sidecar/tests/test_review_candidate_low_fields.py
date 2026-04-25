# pylint: disable=wrong-import-position

import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
)

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.database import connection
from modeladmin_sidecar.main import create_modeladmin_sidecar_app


def _create_client(tmp_path) -> TestClient:
    database_path = tmp_path / f"modeladmin-low-fields-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    return TestClient(app)


def test_boundary_intake_persists_low_confidence_field_snapshot(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        document_id = f"low-fields-{uuid.uuid4()}"
        payload = {
            "document_id": document_id,
            "compose_model_id": "procurement-compose-model.v3",
            "idempotency_key": f"{document_id}:procurement-compose-model.v3",
            "blob_path": f"documents/{document_id}.pdf",
            "processed_blob_path": f"documents/goods-receipt-note/{document_id}.json",
            "source_channel": "process-new-api",
            "predicted_document_type": "goods-receipt-note",
            "classification_confidence": 0.84,
            "has_low_confidence": True,
            "trigger_reason": "low_field_confidence",
            "structured_data": {
                "ReceiptDate": {"value": "2026-04-02", "confidence": 0.91},
                "VendorName": {"value": "Contoso", "confidence": 0.54},
                "Items": [
                    {
                        "Description": {"value": "Widgets", "confidence": 0.87},
                        "Quantity": {"value": 5, "confidence": 0.62},
                    }
                ],
            },
        }

        intake_response = client.post("/boundary/modeladmin/candidate-created", json=payload)
        assert intake_response.status_code == 200
        candidate_id = intake_response.json()["candidate_id"]

        detail_response = client.get(f"/modeladmin/review-candidates/{candidate_id}")
        assert detail_response.status_code == 200
        item = detail_response.json()["item"]
        assert item["low_confidence_field_count"] == 2
        assert item["low_confidence_fields"] == ["VendorName", "Items.Quantity"]

        list_response = client.get("/modeladmin/review-candidates")
        assert list_response.status_code == 200
        listed = next((row for row in list_response.json()["items"] if row["id"] == candidate_id), None)
        assert listed is not None
        assert listed["low_confidence_field_count"] == 2
        assert listed["low_confidence_fields"] == ["VendorName", "Items.Quantity"]


def test_boundary_intake_keeps_empty_low_field_snapshot_for_other_triggers(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        document_id = f"other-trigger-{uuid.uuid4()}"
        payload = {
            "document_id": document_id,
            "compose_model_id": "procurement-compose-model.v3",
            "idempotency_key": f"{document_id}:procurement-compose-model.v3",
            "blob_path": f"documents/{document_id}.pdf",
            "processed_blob_path": f"documents/invoice/{document_id}.json",
            "source_channel": "process-new-api",
            "predicted_document_type": "invoice",
            "classification_confidence": 0.49,
            "has_low_confidence": False,
            "trigger_reason": "low_confidence",
        }

        intake_response = client.post("/boundary/modeladmin/candidate-created", json=payload)
        assert intake_response.status_code == 200
        candidate_id = intake_response.json()["candidate_id"]

        detail_response = client.get(f"/modeladmin/review-candidates/{candidate_id}")
        assert detail_response.status_code == 200
        item = detail_response.json()["item"]
        assert item["low_confidence_field_count"] is None
        assert item["low_confidence_fields"] == []


def test_init_db_adds_low_confidence_snapshot_columns_for_existing_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy-review-candidates.db"
    legacy_engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    with legacy_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE review_candidates (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    blob_path TEXT NOT NULL,
                    processed_blob_path TEXT,
                    predicted_document_type TEXT,
                    classification_confidence FLOAT,
                    compose_model_id TEXT NOT NULL,
                    has_low_confidence BOOLEAN NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    source_channel TEXT,
                    original_filename TEXT,
                    operator_label TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    approved_by TEXT,
                    approved_at TEXT,
                    rejection_reason TEXT,
                    error_details TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
        )

    monkeypatch.setattr(connection, "engine", legacy_engine)
    connection._ensure_review_candidate_columns()  # pylint: disable=protected-access

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("review_candidates")}
    assert "low_confidence_field_names" in columns
    assert "low_confidence_field_count" in columns
