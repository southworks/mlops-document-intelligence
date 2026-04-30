import os
import httpx
from unittest.mock import patch

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
from app.services.confidence_gate import (
    DisabledAdapter,
    ExternalAdapter,
    HttpxClient,
    _resolve_adapter,
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


def test_disabled_adapter_returns_not_accepted() -> None:
    adapter = DisabledAdapter("no endpoint configured")
    result = adapter.intake(_sample_payload())
    assert result.accepted is False
    assert result.transport == "disabled"


def test_external_adapter_succeeds() -> None:
    adapter = ExternalAdapter(
        endpoint="http://modeladmin-service:8100",
        timeout_seconds=2,
        retry_attempts=0,
        client=_StubClientSuccess(),
    )
    result = adapter.intake(_sample_payload())
    assert result.accepted is True
    assert result.candidate_id == "cand-123"
    assert result.transport == "external"


def test_external_adapter_times_out_returns_not_accepted() -> None:
    adapter = ExternalAdapter(
        endpoint="http://modeladmin-service:8100",
        timeout_seconds=2,
        retry_attempts=0,
        client=_StubClientTimeout(),
    )
    result = adapter.intake(_sample_payload())
    assert result.accepted is False
    assert result.transport == "external"


def test_external_adapter_retries_on_flaky_client() -> None:
    stub = _StubClientFlaky()
    adapter = ExternalAdapter(
        endpoint="http://modeladmin-service:8100",
        timeout_seconds=2,
        retry_attempts=1,
        retry_backoff_ms=0,
        client=stub,
    )
    result = adapter.intake(_sample_payload())
    assert result.accepted is True
    assert result.candidate_id == "cand-456"
    assert stub.calls == 2


def test_resolve_adapter_returns_disabled_when_no_endpoint() -> None:
    settings = Settings(
        modeladmin_external_endpoint="",
        azure_storage_connection_string="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=fake;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;",
    )
    adapter = _resolve_adapter(settings)
    assert isinstance(adapter, DisabledAdapter)


def test_resolve_adapter_returns_external_when_endpoint_set() -> None:
    settings = Settings(
        modeladmin_external_endpoint="http://modeladmin-service:8100",
        azure_storage_connection_string="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=fake;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;",
    )
    adapter = _resolve_adapter(settings)
    assert isinstance(adapter, ExternalAdapter)


def test_resolve_active_model_id_returns_none_when_no_endpoint() -> None:
    settings = Settings(
        modeladmin_external_endpoint="",
        azure_storage_connection_string="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=fake;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;",
    )
    result = resolve_active_model_id(settings_override=settings)
    assert result is None
