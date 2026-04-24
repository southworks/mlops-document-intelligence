# pylint: disable=wrong-import-position
import os
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

def _sample_payload() -> dict:
    return {
        "document_id": "job-auth-001",
        "compose_model_id": "procurement-compose-model.v2",
        "idempotency_key": "job-auth-001:procurement-compose-model.v2",
        "blob_path": "documents/job-auth-001.pdf",
        "processed_blob_path": "documents/invoice/job-auth-001.json",
        "source_channel": "process-new-api",
        "predicted_document_type": "invoice",
        "classification_confidence": 0.61,
        "has_low_confidence": True,
        "trigger_reason": "low_confidence",
    }

def test_boundary_intake_rejects_when_api_key_is_configured_and_header_missing() -> None:
    os.environ["BOUNDARY_API_KEY"] = "service-secret"
    get_modeladmin_service_settings.cache_clear()
    app = create_modeladmin_service_app()
    client = TestClient(app)
    response = client.post(
        "/boundary/modeladmin/candidate-created",
        json=_sample_payload(),
    )
    assert response.status_code == 401
    assert "Unauthorized" in response.json()["detail"]
    del os.environ["BOUNDARY_API_KEY"]
    get_modeladmin_service_settings.cache_clear()
