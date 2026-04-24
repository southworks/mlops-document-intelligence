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


def test_external_port_uses_response_contract_shape() -> None:
    port = ExternalModelAdminPort(
        endpoint="http://modeladmin.local",
        timeout_seconds=2,
        client=_StubClientSuccess(),
    )

    result = port.intake_candidate_created(_sample_payload())

    assert result.accepted is True
    assert result.candidate_id == "cand-123"
    assert result.transport == "external"
    assert result.fallback_used is False


def test_external_port_timeout_does_not_fallback_to_backend_write() -> None:
    port = ExternalModelAdminPort(
        endpoint="http://modeladmin.local",
        timeout_seconds=1,
        client=_StubClientTimeout(),
    )

    result = port.intake_candidate_created(_sample_payload())

    assert result.accepted is False
    assert result.candidate_id is None
    assert result.transport == "external"
    assert result.fallback_used is False


def test_external_port_retries_and_succeeds_before_fallback() -> None:
    flaky_client = _StubClientFlaky()

    port = ExternalModelAdminPort(
        endpoint="http://modeladmin.local",
        timeout_seconds=1,
        retry_attempts=1,
        retry_backoff_ms=0,
        client=flaky_client,
    )

    result = port.intake_candidate_created(_sample_payload())

    assert flaky_client.calls == 2
    assert result.accepted is True
    assert result.candidate_id == "cand-456"
    assert result.transport == "external"
    assert result.fallback_used is False


def test_feature_flag_external_without_endpoint_returns_disabled_port() -> None:
    settings = Settings(
        modeladmin_external_endpoint=None,
    )

    port = _resolve_port_from_settings(settings)

    assert isinstance(port, DisabledModelAdminPort)

def test_feature_flag_external_mode_builds_external_port() -> None:
    settings = Settings(
        modeladmin_external_endpoint="http://modeladmin-service:8100",
    )

    port = _resolve_port_from_settings(settings)

    assert isinstance(port, ExternalModelAdminPort)


def test_httpx_external_client_sends_service_auth_header_when_api_key_is_configured() -> None:
    client = HttpxExternalBoundaryClient(
        endpoint="http://modeladmin-service:8100",
        timeout_seconds=2,
        api_key="shared-secret",
    )

    fake_response = Mock()
    fake_response.content = b'{"accepted": true, "contract_version": "1.0.0"}'
    fake_response.json.return_value = {"accepted": True, "contract_version": "1.0.0"}
    fake_response.raise_for_status.return_value = None

    with patch("app.services.modeladmin_port.httpx.post", return_value=fake_response) as mock_post:
        client.post_candidate_created(
            payload=_sample_payload(),
            correlation_id="corr-123",
        )

    headers = mock_post.call_args.kwargs["headers"]
    assert headers["X-Service-Auth"] == "shared-secret"
    assert headers["X-Correlation-Id"] == "corr-123"


def test_resolve_active_model_id_returns_active_model_from_modeladmin_response() -> None:
    settings = Settings(
        modeladmin_external_endpoint="http://modeladmin-service:8100",
        modeladmin_external_timeout_seconds=3,
        modeladmin_external_api_key="shared-secret",
    )

    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.content = b'{"item": {"active_model_id": "compose-live-v3"}}'
    fake_response.json.return_value = {"item": {"active_model_id": "compose-live-v3"}}
    fake_response.raise_for_status.return_value = None

    with patch("app.services.modeladmin_port.httpx.get", return_value=fake_response) as mock_get:
        model_id = resolve_active_model_id(settings_override=settings)

    assert model_id == "compose-live-v3"
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["X-Service-Auth"] == "shared-secret"


def test_resolve_active_model_id_returns_none_on_modeladmin_404() -> None:
    settings = Settings(
        modeladmin_external_endpoint="http://modeladmin-service:8100",
    )

    fake_response = Mock()
    fake_response.status_code = 404
    fake_response.content = b""

    with patch("app.services.modeladmin_port.httpx.get", return_value=fake_response):
        model_id = resolve_active_model_id(settings_override=settings)

    assert model_id is None


def test_resolve_active_model_id_supports_compose_centric_active_payload() -> None:
    settings = Settings(
        modeladmin_external_endpoint="http://modeladmin-service:8100",
        modeladmin_external_timeout_seconds=3,
    )

    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.content = b'{"item": {"active_model_id": "compose-live-v4", "activated_at": "2026-03-20T10:00:00Z"}}'
    fake_response.json.return_value = {
        "item": {
            "active_model_id": "compose-live-v4",
            "activated_at": "2026-03-20T10:00:00Z",
        }
    }
    fake_response.raise_for_status.return_value = None

    with patch("app.services.modeladmin_port.httpx.get", return_value=fake_response):
        model_id = resolve_active_model_id(settings_override=settings)

    assert model_id == "compose-live-v4"
