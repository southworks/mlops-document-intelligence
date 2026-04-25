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
    database_path = tmp_path / f"modeladmin-ui-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    return TestClient(app)


def _create_approved_candidate(client: TestClient, *, label: str, suffix: str) -> str:
    document_id = f"ui-dataset-{suffix}-{uuid.uuid4()}"
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


def test_retrain_ui_routes_and_assets_are_available(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        retrain_page = client.get("/modeladmin/ui/retrain-candidates")
        assert retrain_page.status_code == 200
        assert "Approved for Retrain" in retrain_page.text
        assert "selectAllCheckbox" in retrain_page.text
        assert "actionBar" in retrain_page.text
        assert "createDatasetBtn" in retrain_page.text
        assert "/modeladmin/ui/datasets" in retrain_page.text

        datasets_page = client.get("/modeladmin/ui/datasets")
        assert datasets_page.status_code == 200
        assert "Training Datasets" in datasets_page.text
        assert "tableBody" in datasets_page.text

        datasets_script = client.get("/modeladmin/ui/static/datasets.js")
        assert datasets_script.status_code == 200
        assert "/modeladmin/training-datasets" in datasets_script.text
        assert "loadDatasets" in datasets_script.text

        curation_page = client.get("/modeladmin/ui/datasets/test-id")
        assert curation_page.status_code == 200
        assert "Dataset Curation" in curation_page.text
        assert "memberTableBody" in curation_page.text
        assert "markReadyBtn" in curation_page.text

        curation_script = client.get("/modeladmin/ui/static/dataset_curation.js")
        assert curation_script.status_code == 200
        assert "removeMember" in curation_script.text
        assert "markReadyBtn" in curation_script.text
        assert "/members/" in curation_script.text

        retrain_script = client.get("/modeladmin/ui/static/retrain.js")
        assert retrain_script.status_code == 200
        assert "selectedCandidateIds" in retrain_script.text
        assert "createDatasetBtn" in retrain_script.text
        assert "/modeladmin/training-datasets" in retrain_script.text
        assert "/modeladmin/ui/datasets/" in retrain_script.text

        retrain_jobs_page = client.get("/modeladmin/ui/retrain-jobs")
        assert retrain_jobs_page.status_code == 200
        assert "Compose Models" in retrain_jobs_page.text
        assert "tableBody" in retrain_jobs_page.text

        retrain_jobs_script = client.get("/modeladmin/ui/static/retrain_jobs.js")
        assert retrain_jobs_script.status_code == 200
        assert "/modeladmin/models/compose" in retrain_jobs_script.text
        assert "/modeladmin/models/" in retrain_jobs_script.text
        assert "/activate" in retrain_jobs_script.text


def test_retrain_selection_flow_create_dataset_and_fetch_detail(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        candidate_ids = [
            _create_approved_candidate(client, label="invoice", suffix=str(index))
            for index in range(3)
        ]

        create_response = client.post(
            "/modeladmin/training-datasets",
            json={
                "name": "ui-selected-candidates",
                "created_by": "operator@southworks.com",
                "candidate_ids": candidate_ids,
            },
        )
        assert create_response.status_code == 200

        create_body = create_response.json()
        assert create_body["success"] is True
        dataset_id = create_body["item"]["id"]
        assert create_body["item"]["membership_count"] == 3

        detail_response = client.get(f"/modeladmin/training-datasets/{dataset_id}")
        assert detail_response.status_code == 200
        detail_body = detail_response.json()
        assert detail_body["item"]["id"] == dataset_id
        assert len(detail_body["membership"]) == 3
        assert {member["candidate_id"] for member in detail_body["membership"]} == set(candidate_ids)
