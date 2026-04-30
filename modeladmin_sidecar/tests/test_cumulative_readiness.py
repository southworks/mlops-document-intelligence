# pylint: disable=wrong-import-position
"""
PBI5 tests: Cumulative dataset readiness, class-counts endpoint,
ghost activation endpoint removal, and regression guard.
"""

import os
import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;",
)

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from modeladmin_sidecar.main import create_modeladmin_sidecar_app
from modeladmin_sidecar.services.azure_blob_storage_service import AzureBlobStorageService


FIELDS_JSON_BY_DOC_TYPE = {
    "invoice/fields.json": '{"fields": [{"fieldKey": "InvoiceDate"}]}',
    "purchase-order/fields.json": '{"fields": [{"fieldKey": "PurchaseOrder"}]}',
}

LABELS_JSON_BY_DOC_TYPE = {
    "invoice": '{"labels": [{"label": "InvoiceDate"}]}',
    "purchase-order": '{"labels": [{"label": "PurchaseOrder"}]}',
}


def _create_client(tmp_path) -> TestClient:
    database_path = tmp_path / f"modeladmin-{uuid.uuid4()}.db"
    os.environ["MODELADMIN_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    get_modeladmin_sidecar_settings.cache_clear()
    app = create_modeladmin_sidecar_app()
    return TestClient(app)


def _create_approved_candidate(client: TestClient, *, label: str, suffix: str = "") -> str:
    """Create, label, and approve a review candidate; return its ID."""
    document_id = f"pbi5-{suffix}-{uuid.uuid4()}"
    intake = client.post(
        "/boundary/modeladmin/candidate-created",
        json={
            "document_id": document_id,
            "compose_model_id": "procurement-compose-model.v2",
            "idempotency_key": f"{document_id}:procurement-compose-model.v2",
            "blob_path": f"documents/{document_id}.pdf",
            "processed_blob_path": f"documents/{label}/{document_id}.json",
            "source_channel": "process-new-api",
            "predicted_document_type": label,
            "classification_confidence": 0.80,
            "has_low_confidence": False,
            "trigger_reason": "manual_review",
        },
    )
    assert intake.status_code == 200
    candidate_id = intake.json()["candidate_id"]

    assert client.post(
        f"/modeladmin/review-candidates/{candidate_id}/label",
        json={"label": label},
    ).status_code == 200

    assert client.post(
        f"/modeladmin/review-candidates/{candidate_id}/approve",
        json={},
    ).status_code == 200

    return candidate_id


def _create_and_stage_dataset(
    client: TestClient,
    candidate_ids: list[str],
    *,
    name: str = "test-dataset",
    parent_dataset_id: str | None = None,
) -> str:
    """Create a dataset, stage it, and return its ID."""
    body: dict = {
        "name": name,
        "created_by": "trainer@example.com",
        "candidate_ids": candidate_ids,
    }
    if parent_dataset_id:
        body["parent_dataset_id"] = parent_dataset_id

    resp = client.post("/modeladmin/training-datasets", json=body)
    assert resp.status_code == 200, resp.text
    dataset_id = resp.json()["item"]["id"]

    stage_blob_service = MagicMock(spec=AzureBlobStorageService)
    stage_blob_service.ensure_container.return_value = None
    stage_blob_service.copy_blob.return_value = None

    import modeladmin_sidecar.services.training_dataset_service as service_module

    with patch.object(service_module, "AzureBlobStorageService", lambda conn_str: stage_blob_service):
        stage_resp = client.post(f"/modeladmin/training-datasets/{dataset_id}/stage")
    assert stage_resp.status_code == 200
    return dataset_id


# ---------------------------------------------------------------------------
# Test 1 — class-counts on a standalone dataset (no parent)
# ---------------------------------------------------------------------------

def test_class_counts_single_dataset(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        invoices = [_create_approved_candidate(client, label="invoice", suffix=f"i{i}") for i in range(3)]
        pos = [_create_approved_candidate(client, label="purchase-order", suffix=f"p{i}") for i in range(2)]

        dataset_id = _create_and_stage_dataset(client, invoices + pos)

        resp = client.get(f"/modeladmin/training-datasets/{dataset_id}/class-counts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dataset_id"] == dataset_id
        assert body["chain_ids"] == [dataset_id]
        assert body["per_class_counts"]["invoices"] == 3
        assert body["per_class_counts"]["purchase-order"] == 2


# ---------------------------------------------------------------------------
# Test 2 — class-counts walks the parent chain and accumulates counts
# ---------------------------------------------------------------------------

def test_class_counts_cumulative_with_parent_chain(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        # Parent: 4 invoices + 3 purchase-orders
        parent_invoices = [_create_approved_candidate(client, label="invoice", suffix=f"pi{i}") for i in range(4)]
        parent_pos = [_create_approved_candidate(client, label="purchase-order", suffix=f"pp{i}") for i in range(3)]
        parent_id = _create_and_stage_dataset(client, parent_invoices + parent_pos, name="parent-ds")

        # Child: 2 more invoices, 1 more purchase-order (new candidates)
        child_invoices = [_create_approved_candidate(client, label="invoice", suffix=f"ci{i}") for i in range(2)]
        child_pos = [_create_approved_candidate(client, label="purchase-order", suffix=f"cp{i}") for i in range(1)]
        child_id = _create_and_stage_dataset(
            client, child_invoices + child_pos, name="child-ds", parent_dataset_id=parent_id
        )

        resp = client.get(f"/modeladmin/training-datasets/{child_id}/class-counts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dataset_id"] == child_id
        assert set(body["chain_ids"]) == {child_id, parent_id}
        # Cumulative: 4+2=6 invoices, 3+1=4 purchase-orders
        assert body["per_class_counts"]["invoices"] == 6
        assert body["per_class_counts"]["purchase-order"] == 4


# ---------------------------------------------------------------------------
# Test 3 — mark-ready uses cumulative counts to satisfy the threshold
# ---------------------------------------------------------------------------

def test_mark_ready_uses_cumulative_counts(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        # Parent has 5 invoices + 5 purchase-orders (already at threshold)
        parent_invoices = [_create_approved_candidate(client, label="invoice", suffix=f"mpi{i}") for i in range(5)]
        parent_pos = [_create_approved_candidate(client, label="purchase-order", suffix=f"mpp{i}") for i in range(5)]
        parent_id = _create_and_stage_dataset(client, parent_invoices + parent_pos, name="parent-mark")

        # Child adds only 1 of each — below the threshold of 5 if counted alone
        child_invoice = _create_approved_candidate(client, label="invoice", suffix="mci0")
        child_po = _create_approved_candidate(client, label="purchase-order", suffix="mcp0")
        child_id = _create_and_stage_dataset(
            client, [child_invoice, child_po], name="child-mark", parent_dataset_id=parent_id
        )

        # Without cumulation, 1 per class would fail min_items_per_class=5.
        # With cumulation (1 + 5 = 6 each), it must succeed.
        verify_blob_service = MagicMock(spec=AzureBlobStorageService)
        verify_blob_service.list_blobs_by_prefix.side_effect = lambda _container, prefix: (
            ["invoice/INV-001.pdf"] if prefix == "invoice/" else ["purchase-order/PO-001.pdf"]
        )
        verify_blob_service.blob_exists.return_value = True

        def _download_blob_text(_container: str, blob_name: str) -> str:
            if blob_name.endswith("fields.json"):
                return FIELDS_JSON_BY_DOC_TYPE.get(blob_name, '{"fields": []}')
            if blob_name.startswith("invoice/"):
                return LABELS_JSON_BY_DOC_TYPE["invoice"]
            return LABELS_JSON_BY_DOC_TYPE["purchase-order"]

        verify_blob_service.download_blob_text.side_effect = _download_blob_text

        import modeladmin_sidecar.services.training_dataset_service as service_module

        with patch.object(service_module, "AzureBlobStorageService", lambda conn_str: verify_blob_service):
            resp = client.post(
                f"/modeladmin/training-datasets/{child_id}/mark-ready",
                json={"min_items_per_class": 5},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["item"]["status"] == "ready_for_retrain"


# ---------------------------------------------------------------------------
# Test 4 — cumulative counts deduplicate candidates shared across datasets
# ---------------------------------------------------------------------------

def test_class_counts_deduplicates_shared_candidates(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        # Shared invoices: appear in both parent and child
        shared = [_create_approved_candidate(client, label="invoice", suffix=f"sh{i}") for i in range(3)]
        # Unique to parent
        parent_only = [_create_approved_candidate(client, label="invoice", suffix=f"pu{i}") for i in range(2)]
        parent_id = _create_and_stage_dataset(client, shared + parent_only, name="dedup-parent")

        # Child reuses the same 3 shared candidates + adds 1 new
        new_child = _create_approved_candidate(client, label="invoice", suffix="nc0")
        child_id = _create_and_stage_dataset(
            client, shared + [new_child], name="dedup-child", parent_dataset_id=parent_id
        )

        resp = client.get(f"/modeladmin/training-datasets/{child_id}/class-counts")
        assert resp.status_code == 200
        body = resp.json()
        # 3 (shared, counted once) + 2 (parent-only) + 1 (child-new) = 6, NOT 3+3+2+1=9
        assert body["per_class_counts"]["invoices"] == 6


# ---------------------------------------------------------------------------
# Test 5 — ghost activate endpoint is absent (no 200 / 201 response)
# ---------------------------------------------------------------------------

def test_ghost_activate_endpoint_is_absent(tmp_path) -> None:
    with _create_client(tmp_path) as client:
        fake_job_id = str(uuid.uuid4())
        resp = client.post(f"/modeladmin/retrain-jobs/{fake_job_id}/activate")
        # FastAPI returns 404 for unregistered paths; 405 would also be acceptable
        assert resp.status_code in (404, 405), (
            f"Expected 404/405 for ghost endpoint but got {resp.status_code}"
        )
