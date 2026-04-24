import os
import httpx
from unittest.mock import Mock, patch
os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
)
os.environ.setdefault("DATABASE_URL", "sqlite:///./invoice_ocr.db")
from app.modeladmin_core.boundary_contracts import CandidateCreatedV1Payload, CandidateCreatedV1Response
from app.config import Settings
from app.services.modeladmin_port import (
    DisabledModelAdminPort,
    ExternalModelAdminPort,
    HttpxExternalBoundaryClient,
    _resolve_port_from_settings,
    resolve_active_model_id,
)
class _StubClientSuccess:
    def post_candidate_created(self, payload: CandidateCreatedV1Payload, correlation_id: str):
        return CandidateCreatedV1Response(
            contract_version="1.0.0",
            accepted=True,
            candidate_id="cand-123",
        )
class _StubClientTimeout:
    def post_candidate_created(self, payload: CandidateCreatedV1Payload, correlation_id: str):
        raise httpx.TimeoutException("timeout")
class _StubClientFlaky:
    def __init__(self) -> None:
        self.calls = 0
    def post_candidate_created(self, payload: CandidateCreatedV1Payload, correlation_id: str):
        self.calls += 1
        if self.calls == 1:
            raise httpx.TimeoutException("first attempt timeout")
        return CandidateCreatedV1Response(
            contract_version="1.0.0",
            accepted=True,
            candidate_id="cand-456",
        )
def _sample_payload() -> CandidateCreatedV1Payload:
    return CandidateCreatedV1Payload(
        document_id="job-001",
        compose_model_id="procurement-compose-model.v2",
        idempotency_key="job-001:procurement-compose-model.v2",
        blob_path="documents/job-001.pdf",
        processed_blob_path="documents/invoice/job-001.json",
        source_channel="process-new-api",
        predicted_document_type="invoice",
        classification_confidence=0.61,
        has_low_confidence=True,
        trigger_reason="low_confidence",
    )
