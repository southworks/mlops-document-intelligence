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
from app.services.modeladmin_port import ExternalModelAdminPort, build_candidate_created_payload
from modeladmin_service.config import get_modeladmin_service_settings
from modeladmin_service.main import create_modeladmin_service_app
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
def test_phase4_cutover_smoke_backend_boundary_to_modeladmin_lifecycle() -> None:
    os.environ["BOUNDARY_API_KEY"] = "cutover-shared-secret"
    get_modeladmin_service_settings.cache_clear()
    app = create_modeladmin_service_app()
    with TestClient(app) as modeladmin_client:
        boundary_client = _TestClientBoundaryAdapter(modeladmin_client, "cutover-shared-secret")
        port = ExternalModelAdminPort(
            endpoint="http://modeladmin-service:8100",
            timeout_seconds=2,
            retry_attempts=0,
        )
