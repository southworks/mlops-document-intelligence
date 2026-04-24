# pylint: disable=wrong-import-position

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

from modeladmin_service.main import create_modeladmin_service_app


def test_modeladmin_service_registers_expected_routes() -> None:
    app = create_modeladmin_service_app()
    paths = {route.path for route in app.routes}

    assert "/health/" in paths
    assert "/health/metrics" in paths
    assert "/boundary/modeladmin/candidate-created" in paths
    assert "/modeladmin/review-candidates/" in paths
    assert "/modeladmin/review-candidates/{candidate_id}" in paths
    assert "/modeladmin/review-candidates/{candidate_id}/label" in paths
    assert "/modeladmin/review-candidates/{candidate_id}/approve" in paths
    assert "/modeladmin/review-candidates/{candidate_id}/reject" in paths
    assert "/modeladmin/training-datasets/" in paths
    assert "/modeladmin/training-datasets/{dataset_id}" in paths
    assert "/modeladmin/training-datasets/{dataset_id}/members/{candidate_id}" in paths
    assert "/modeladmin/training-datasets/{dataset_id}/mark-ready" in paths
    assert "/modeladmin/ui/datasets" in paths
    assert "/modeladmin/ui/datasets/{dataset_id}" in paths
    assert "/modeladmin/retrain" not in paths
    assert all("/reprocess" not in path for path in paths)


def test_modeladmin_service_openapi_metadata() -> None:
    app = create_modeladmin_service_app()

    assert app.title == "ModelAdmin Service"
    assert app.version == "v1"
