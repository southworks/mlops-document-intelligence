"""ModelAdmin UI routes hosted by modeladmin-service runtime."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from starlette.status import HTTP_302_FOUND

UI_ROOT = Path(__file__).resolve().parents[1] / "ui"
UI_STATIC_ROOT = UI_ROOT / "static"

router = APIRouter(tags=["modeladmin-ui"])


def _serve_ui_file(file_name: str) -> FileResponse:
    file_path = UI_ROOT / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"UI asset not found: {file_name}")
    return FileResponse(file_path)


@router.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/modeladmin/ui", status_code=HTTP_302_FOUND)


@router.get("/modeladmin/ui", include_in_schema=False)
def modeladmin_queue_page() -> FileResponse:
    return _serve_ui_file("queue.html")


@router.get("/modeladmin/ui/retrain-candidates", include_in_schema=False)
def modeladmin_retrain_candidates_page() -> FileResponse:
    return _serve_ui_file("retrain.html")


@router.get("/modeladmin/ui/candidates/{candidate_id}", include_in_schema=False)
def modeladmin_candidate_page(candidate_id: str) -> RedirectResponse:
    _ = candidate_id
    return RedirectResponse(url="/modeladmin/ui", status_code=HTTP_302_FOUND)


@router.get("/modeladmin/ui/datasets", include_in_schema=False)
def modeladmin_datasets_list_page() -> FileResponse:
    return _serve_ui_file("datasets.html")


@router.get("/modeladmin/ui/datasets/{dataset_id}", include_in_schema=False)
def modeladmin_dataset_curation_page(dataset_id: str) -> FileResponse:
    _ = dataset_id
    return _serve_ui_file("dataset_curation.html")


@router.get("/modeladmin/ui/retrain-jobs", include_in_schema=False)
def modeladmin_retrain_jobs_page() -> FileResponse:
    return _serve_ui_file("retrain_jobs.html")


@router.get("/modeladmin/ui/retrain-jobs/{job_id}", include_in_schema=False)
def modeladmin_retrain_job_page(job_id: str) -> FileResponse:
    _ = job_id
    return _serve_ui_file("retrain_job_detail.html")


@router.get("/modeladmin/ui/static/{asset_path:path}", include_in_schema=False)
def modeladmin_ui_static(asset_path: str) -> FileResponse:
    file_path = UI_STATIC_ROOT / asset_path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Static UI asset not found: {asset_path}")
    return FileResponse(file_path)
