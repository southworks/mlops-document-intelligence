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
from modeladmin_sidecar.main import create_modeladmin_sidecar_app
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
