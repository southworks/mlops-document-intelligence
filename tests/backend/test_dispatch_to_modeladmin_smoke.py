# pylint: disable=wrong-import-position
import os
from uuid import uuid4
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

from app.modeladmin_core.boundary_contracts import CandidateCreatedV1Payload, CandidateCreatedV1Response
from app.services.confidence_gate import ExternalAdapter, build_candidate_payload
from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.main import create_modeladmin_sidecar_app


class _TestClientBoundaryAdapter:
    def __init__(self, client: TestClient, api_key: str) -> None:
        self.client = client
        self.api_key = api_key

    def post_candidate_created(
        self,
        payload: CandidateCreatedV1Payload,
        correlation_id: str,
    ) -> CandidateCreatedV1Response:
        response = self.client.post(
            "/boundary/modeladmin/candidate-created",
            json=payload.model_dump(mode="json"),
            headers={
                "Content-Type": "application/json",
                "X-Idempotency-Key": payload.idempotency_key,
                "X-Correlation-Id": correlation_id,
                "X-Service-Auth": self.api_key,
            },
        )
        response.raise_for_status()
        body = response.json() if response.content else {"accepted": True}
        return CandidateCreatedV1Response.model_validate(body)


def test_external_adapter_dispatches_candidate_to_modeladmin_boundary() -> None:
    os.environ["BOUNDARY_API_KEY"] = "cutover-shared-secret"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    with TestClient(app) as modeladmin_client:
        boundary_client = _TestClientBoundaryAdapter(modeladmin_client, "cutover-shared-secret")
        adapter = ExternalAdapter(
            endpoint="http://modeladmin-service:8100",
            timeout_seconds=2,
            retry_attempts=0,
            client=boundary_client,
        )
        payload = build_candidate_payload(
            document_id=f"smoke-{uuid4().hex[:8]}",
            blob_path="documents/smoke-test.pdf",
            processed_blob_path="documents/invoice/smoke-test.json",
            document_type="invoice",
            classification_confidence=0.61,
            compose_model_id="procurement-compose-model.v2",
            source_channel="smoke-test",
            trigger_reason="low_confidence",
            has_low_confidence=True,
            original_filename="smoke-test.pdf",
            structured_data=None,
            error_details=None,
        )
        result = adapter.intake(payload)
        assert result.accepted is True
        assert result.transport == "external"
