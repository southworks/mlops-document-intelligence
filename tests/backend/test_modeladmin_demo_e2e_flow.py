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
os.environ.setdefault("DATABASE_URL", "sqlite:///./invoice_ocr.db")
from modeladmin_service.config import get_modeladmin_service_settings
from modeladmin_service.main import create_modeladmin_service_app
from modeladmin_service.database.connection import init_db

def test_demo_flow_candidate_marking_and_review_lifecycle() -> None:
    init_db()
    os.environ["BOUNDARY_API_KEY"] = "demo-shared-secret"
    get_modeladmin_service_settings.cache_clear()
    app = create_modeladmin_service_app()
    client = TestClient(app)
    document_id = f"demo-{uuid.uuid4()}"
    payload = {
        "document_id": document_id,
        "compose_model_id": "procurement-compose-model.v2",
        "idempotency_key": f"{document_id}:procurement-compose-model.v2",
        "blob_path": f"documents/{document_id}.pdf",
        "processed_blob_path": f"documents/invoice/{document_id}.json",
        "source_channel": "process-new-api",
        "predicted_document_type": "invoice",
        "classification_confidence": 0.62,
        "has_low_confidence": True,
        "trigger_reason": "low_confidence",
    }
    intake_response = client.post(
        "/boundary/modeladmin/candidate-created",
        json=payload,
        headers={"X-Service-Auth": "demo-shared-secret"},
    )
    assert intake_response.status_code == 200
    intake_body = intake_response.json()
    candidate_id = intake_body.get("candidate_id")
    assert intake_body.get("accepted") is True
    assert candidate_id
    get_response = client.get(f"/modeladmin/review-candidates/{candidate_id}")
    assert get_response.status_code == 200
    assert get_response.json()["item"]["status"] in {"new", "reviewed"}
