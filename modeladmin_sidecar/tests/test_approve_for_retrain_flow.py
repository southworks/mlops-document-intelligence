# pylint: disable=wrong-import-position

import os
import uuid

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


def _create_client(tmp_path) -> TestClient:
    database_path = tmp_path / f"modeladmin-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    return TestClient(app)


def _create_candidate(client: TestClient, *, suffix: str) -> str:
    document_id = f"approve-flow-{suffix}-{uuid.uuid4()}"
    payload = {
        "document_id": document_id,
        "compose_model_id": "procurement-compose-model.v2",
        "idempotency_key": f"{document_id}:procurement-compose-model.v2",
        "blob_path": f"documents/{document_id}.pdf",
        "processed_blob_path": f"documents/invoice/{document_id}.json",
        "source_channel": "process-new-api",
        "predicted_document_type": "invoice",
        "classification_confidence": 0.72,
        "has_low_confidence": False,
        "trigger_reason": "manual_review",
    }

    intake_response = client.post("/boundary/modeladmin/candidate-created", json=payload)
    assert intake_response.status_code == 200
    return intake_response.json()["candidate_id"]


def test_save_label_transitions_new_to_reviewed(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_id = _create_candidate(client, suffix="label")

        label_response = client.post(
            f"/modeladmin/review-candidates/{candidate_id}/label",
            json={"label": "invoice"},
        )
        assert label_response.status_code == 200

        item = label_response.json()["item"]
        assert item["status"] == "reviewed"
        assert item["operator_label"] == "invoices"


def test_approve_rejects_candidate_not_in_reviewed_state(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_id = _create_candidate(client, suffix="invalid-state")

        approve_response = client.post(
            f"/modeladmin/review-candidates/{candidate_id}/approve",
            json={},
        )

        assert approve_response.status_code == 409
        assert "current state" in approve_response.json()["detail"]


def test_approve_rejects_reviewed_candidate_missing_label(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_id = _create_candidate(client, suffix="missing-label")

        from modeladmin_sidecar.database.connection import SESSION_LOCAL
        from modeladmin_sidecar.database.models import ReviewCandidateModel

        db = SESSION_LOCAL()
        try:
            candidate = (
                db.query(ReviewCandidateModel)
                .filter(ReviewCandidateModel.id == candidate_id)
                .first()
            )
            assert candidate is not None
            candidate.status = "reviewed"
            candidate.operator_label = None
            db.commit()
        finally:
            db.close()

        approve_response = client.post(
            f"/modeladmin/review-candidates/{candidate_id}/approve",
            json={},
        )

        assert approve_response.status_code == 409
        assert approve_response.json()["detail"] == "Candidate must be labeled before approval"


def test_reject_succeeds_without_reason_and_clears_label(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_id = _create_candidate(client, suffix="reject-no-reason")

        label_response = client.post(
            f"/modeladmin/review-candidates/{candidate_id}/label",
            json={"label": "invoice"},
        )
        assert label_response.status_code == 200

        reject_response = client.post(
            f"/modeladmin/review-candidates/{candidate_id}/reject",
            json={},
        )
        assert reject_response.status_code == 200

        item = reject_response.json()["item"]
        assert item["status"] == "new"
        assert item["operator_label"] is None
