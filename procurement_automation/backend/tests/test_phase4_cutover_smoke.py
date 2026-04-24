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
            client=boundary_client,
        )

        document_id = f"cutover-{uuid4()}"
        payload = build_candidate_created_payload(
            document_id=document_id,
            blob_path=f"documents/{document_id}.pdf",
            processed_blob_path=f"documents/unknown/{document_id}.json",
            document_type="unknown",
            classification_confidence=0.42,
            compose_model_id="procurement-compose-model.v2",
            source_channel="phase4-cutover-smoke",
            trigger_reason="unknown_classification",
            has_low_confidence=False,
            original_filename=f"{document_id}.pdf",
            structured_data={"test": True},
            error_details=None,
        )

        intake_result = port.intake_candidate_created(payload)

        assert intake_result.accepted is True
        assert intake_result.transport == "external"
        assert intake_result.candidate_id

        candidate_id = intake_result.candidate_id

        get_response = modeladmin_client.get(f"/modeladmin/review-candidates/{candidate_id}")
        assert get_response.status_code == 200
        assert get_response.json()["item"]["status"] in {"new", "reviewed"}

        list_response = modeladmin_client.get("/modeladmin/review-candidates?limit=20")
        assert list_response.status_code == 200
        listed_ids = {item["id"] for item in list_response.json()["items"]}
        assert candidate_id in listed_ids

        label_response = modeladmin_client.post(
            f"/modeladmin/review-candidates/{candidate_id}/label",
            json={"label": "invoice", "actor": "phase4-smoke@local"},
        )
        assert label_response.status_code == 200
        assert label_response.json()["item"]["status"] == "reviewed"

        approve_response = modeladmin_client.post(
            f"/modeladmin/review-candidates/{candidate_id}/approve",
            json={"actor": "phase4-smoke@local"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["item"]["status"] == "approved_for_training"

    del os.environ["BOUNDARY_API_KEY"]
    get_modeladmin_service_settings.cache_clear()
