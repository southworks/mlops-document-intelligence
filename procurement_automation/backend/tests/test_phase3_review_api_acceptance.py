# pylint: disable=wrong-import-position,import-outside-toplevel,line-too-long,unnecessary-lambda,unused-argument,ungrouped-imports

import os

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
)
os.environ.setdefault("DATABASE_URL", "sqlite:///./invoice_ocr.db")

from fastapi.testclient import TestClient

from app.main import app
from modeladmin_service.main import create_modeladmin_service_app
from app.services import document_processor


class _FakeBlobProperties:
    size = 128


class _FakeBlobDownload:
    def readall(self):
        return b"%PDF-1.4 fake-bytes"


class _FakeBlobClient:
    def get_blob_properties(self):
        return _FakeBlobProperties()


class _FakeUploadsContainer:
    def get_blob_client(self, blob_name: str):
        return _FakeBlobClient()

    def download_blob(self, blob_name: str):
        return _FakeBlobDownload()


class _FakeModelRegistry:
    def get_active_model_id(self, model_key: str):
        return "compose-v1"


class _FakeIntakeResult:
    candidate_id = "cand-acc-1"
    fallback_used = False


def test_phase3_acceptance_process_new_keeps_result_storage_and_intake_notification(monkeypatch):
    document_processor.settings.azure_document_intelligence_endpoint = "https://example.cognitiveservices.azure.com"
    document_processor.settings.azure_document_intelligence_key = "fake-key"
    document_processor.settings.azure_compose_model_id = "compose-v1"

    captured = {}

    monkeypatch.setattr(document_processor, "get_blob_client", lambda: object())
    monkeypatch.setattr(document_processor.upload_location, "get_container_client", lambda _blob_client: _FakeUploadsContainer())
    monkeypatch.setattr(document_processor.upload_location, "extract_blob_name", lambda _blob_path: "documents/job_123_invoice.pdf")
    monkeypatch.setattr(document_processor, "build_upload_blob_sas_url", lambda _blob_path: "https://storage.example.com/blob.pdf")
    monkeypatch.setattr(document_processor, "is_publicly_fetchable_url", lambda _url: True)

    monkeypatch.setattr(document_processor, "get_model_registry", lambda: _FakeModelRegistry())
    monkeypatch.setattr(
        document_processor,
        "extract_with_compose_from_url",
        lambda _client, _url, _model_id, **_kw: {"documents": []},
    )
    monkeypatch.setattr(
        document_processor,
        "parse_compose_result",
        lambda _raw: {
            "document_type": "unknown",
            "confidence": 0.31,
            "structured_data": {"invoice_number": {"value": None, "confidence": 0.0}},
        },
    )
    monkeypatch.setattr(document_processor, "save_raw_adi_to_blob", lambda **_kw: None)
    monkeypatch.setattr(document_processor, "generate_thumbnail", lambda *_args, **_kwargs: "https://thumb.example.com/preview.png")
    monkeypatch.setattr(document_processor, "evaluate_candidate_trigger", lambda **_kwargs: (True, "unknown_classification", {}))

    monkeypatch.setattr(document_processor, "save_parsed_compose_to_blob", lambda **_kw: "documents/job-123_parsed.json")
    monkeypatch.setattr(document_processor, "save_to_azure_tables", lambda *_args, **_kwargs: captured.setdefault("table_saved", True))

    def _build_payload(**kwargs):
        captured["payload"] = kwargs
        return {"candidate": "created"}

    monkeypatch.setattr(document_processor, "build_candidate_created_payload", _build_payload)
    monkeypatch.setattr(document_processor, "intake_candidate_created", lambda _payload: _FakeIntakeResult())

    client = TestClient(app)
    response = client.post(
        "/documents/process-new",
        json={
            "blob_path": "documents/job_123_invoice.pdf",
            "job_id": "job-123",
            "original_filename": "invoice.pdf",
        },
    )

    assert response.status_code == 200
    response_body = response.json()
    assert response_body["success"] is True
    assert response_body["document_type"] == "unknown"
    assert response_body["output_path"] == "documents/job-123_parsed.json"

    assert captured["table_saved"] is True
    assert captured["payload"]["document_id"] == "job-123"
    assert captured["payload"]["compose_model_id"] == "compose-v1"
    assert captured["payload"]["source_channel"] == "process-new-api"


def test_phase3_acceptance_review_ownership_and_out_of_scope_reprocess():
    backend_paths = {route.path for route in app.routes}
    modeladmin_app = create_modeladmin_service_app()
    modeladmin_paths = {route.path for route in modeladmin_app.routes}

    assert "/documents/process-new" in backend_paths
    assert "/modeladmin/review-candidates" not in backend_paths
    assert "/modeladmin/review-candidates/" not in backend_paths

    assert "/modeladmin/review-candidates/" in modeladmin_paths
    assert "/modeladmin/review-candidates/{candidate_id}" in modeladmin_paths
    assert "/modeladmin/review-candidates/{candidate_id}/label" in modeladmin_paths
    assert "/modeladmin/review-candidates/{candidate_id}/approve" in modeladmin_paths
    assert "/modeladmin/review-candidates/{candidate_id}/reject" in modeladmin_paths

    assert "/modeladmin/retrain" not in modeladmin_paths
    assert "/modeladmin/reprocess" not in modeladmin_paths


def test_process_new_prefers_modeladmin_active_model_for_compose(monkeypatch):
    document_processor.settings.azure_document_intelligence_endpoint = "https://example.cognitiveservices.azure.com"
    document_processor.settings.azure_document_intelligence_key = "fake-key"
    document_processor.settings.azure_compose_model_id = "compose-fallback-v1"

    captured = {}

    monkeypatch.setattr(document_processor, "get_blob_client", lambda: object())
    monkeypatch.setattr(document_processor.upload_location, "get_container_client", lambda _blob_client: _FakeUploadsContainer())
    monkeypatch.setattr(document_processor.upload_location, "extract_blob_name", lambda _blob_path: "documents/job_999_invoice.pdf")
    monkeypatch.setattr(document_processor, "build_upload_blob_sas_url", lambda _blob_path: "https://storage.example.com/blob.pdf")
    monkeypatch.setattr(document_processor, "is_publicly_fetchable_url", lambda _url: True)

    monkeypatch.setattr(document_processor, "get_model_registry", lambda: _FakeModelRegistry())

    captured_raw = {}

    def _extract_with_model_id(_client, _url, model_id, **_kw):
        captured["used_model_id"] = model_id
        return {"documents": [{"docType": "invoice", "confidence": 0.91}]}

    def _parse_compose_result(_raw):
        return {
            "document_type": "invoice",
            "confidence": 0.91,
            "structured_data": {"invoice_number": {"value": "INV-999", "confidence": 0.99}},
        }

    monkeypatch.setattr(document_processor, "extract_with_compose_from_url", _extract_with_model_id)
    monkeypatch.setattr(document_processor, "parse_compose_result", _parse_compose_result)
    monkeypatch.setattr(document_processor, "save_raw_adi_to_blob", lambda **_kw: None)
    monkeypatch.setattr(document_processor, "generate_thumbnail", lambda *_args, **_kwargs: "https://thumb.example.com/preview.png")
    monkeypatch.setattr(document_processor, "evaluate_candidate_trigger", lambda **_kwargs: (False, None, {}))
    monkeypatch.setattr(document_processor, "save_parsed_compose_to_blob", lambda **_kw: "documents/invoice/job-999_parsed.json")
    monkeypatch.setattr(document_processor, "save_to_azure_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(document_processor, "resolve_active_model_id", lambda **_kwargs: "compose-active-v7")

    client = TestClient(app)
    response = client.post(
        "/documents/process-new",
        json={
            "blob_path": "documents/job_999_invoice.pdf",
            "job_id": "job-999",
            "original_filename": "invoice-999.pdf",
        },
    )

    assert response.status_code == 200
    assert captured["used_model_id"] == "compose-active-v7"
