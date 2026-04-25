#!/usr/bin/env python3
"""Prepare a clean local demo environment starting from model v0.

This script merges reset + setup responsibilities:
- Reset backend and modeladmin databases in Docker containers
- Clear storage containers and recreate required Azure tables
- Seed training-data container with procurement-dataset.v0 files only
- Apply ModelAdmin bootstrap payload from scripts/bootstrap.json
- Optionally restart containers and verify end-to-end readiness
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_env_file(env_path: Path) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(f".env.local not found at: {env_path}")

    with env_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_vars[key.strip()] = value.strip()

    return env_vars


def run_command(command: list[str], dry_run: bool = False) -> None:
    logger.info("$ %s", " ".join(command))
    if dry_run:
        return
    subprocess.run(command, check=True)


def list_existing_containers() -> set[str]:
    """Return a set of existing Docker container names (from `docker ps -a`)."""
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            check=True,
            capture_output=True,
            text=True,
        )
        names = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
        return names
    except subprocess.CalledProcessError:
        return set()


def reset_databases(dry_run: bool) -> None:
    logger.info("=== Reset local DBs ===")

    modeladmin_cmd = [
        "docker",
        "exec",
        "modeladmin-container",
        "python",
        "-c",
        (
            "import modeladmin_sidecar.database.models; "
            "from modeladmin_sidecar.database.connection import Base, engine; "
            "Base.metadata.drop_all(bind=engine); "
            "Base.metadata.create_all(bind=engine); "
            "print('modeladmin db reset complete')"
        ),
    ]
    run_command(modeladmin_cmd, dry_run=dry_run)

    backend_cmd = [
        "docker",
        "exec",
        "backend-container",
        "python",
        "-c",
        (
            "import app.database.models; "
            "from app.database.connection import Base, engine; "
            "Base.metadata.drop_all(bind=engine); "
            "Base.metadata.create_all(bind=engine); "
            "print('backend db reset complete')"
        ),
    ]
    run_command(backend_cmd, dry_run=dry_run)


def clear_containers(blob_service: BlobServiceClient, container_names: list[str], dry_run: bool) -> None:
    logger.info("=== Clear storage containers ===")
    for container_name in container_names:
        container_client = blob_service.get_container_client(container_name)
        deleted = 0

        if dry_run:
            logger.info("[dry-run] would clear container: %s", container_name)
            continue

        try:
            blob_names = [item.name for item in container_client.list_blobs()]
        except ResourceNotFoundError:
            blob_names = []

        for blob_name in blob_names:
            container_client.delete_blob(blob_name)
            deleted += 1

        logger.info("container:%s:deleted=%s", container_name, deleted)


def recreate_tables(table_service: TableServiceClient, table_names: list[str], dry_run: bool) -> None:
    logger.info("=== Recreate required tables ===")
    for table_name in table_names:
        if dry_run:
            logger.info("[dry-run] would recreate table: %s", table_name)
            continue

        try:
            table_service.delete_table(table_name)
            logger.info("table:%s:deleted", table_name)
        except HttpResponseError as exc:
            logger.info("table:%s:delete_skipped:%s", table_name, exc)

        for _ in range(30):
            try:
                table_service.create_table(table_name)
                logger.info("table:%s:created", table_name)
                break
            except HttpResponseError as exc:
                message = str(exc)
                if "TableBeingDeleted" in message:
                    time.sleep(2)
                    continue
                if "TableAlreadyExists" in message:
                    logger.info("table:%s:already_exists", table_name)
                    break
                raise
        else:
            raise RuntimeError(f"failed to recreate table {table_name}")

        table_client = table_service.get_table_client(table_name)
        count = sum(1 for _ in table_client.list_entities())
        logger.info("table:%s:count=%s", table_name, count)


def upload_dataset_files(
    blob_service: BlobServiceClient,
    container_name: str,
    dataset_dir: Path,
    dry_run: bool,
) -> dict[str, int]:
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    logger.info("=== Seed training-data container from v0 dataset ===")
    container_client = blob_service.get_container_client(container_name)

    if not dry_run:
        try:
            container_client.get_container_properties()
        except (ResourceNotFoundError, HttpResponseError):
            logger.info("Creating container '%s'", container_name)
            container_client.create_container()

    uploaded = 0
    skipped = 0

    for file_path in dataset_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part.startswith(".") for part in file_path.parts):
            continue

        relative_path = file_path.relative_to(dataset_dir)
        blob_name = str(relative_path).replace("\\", "/")

        if dry_run:
            logger.info("[dry-run] would upload: %s", blob_name)
            uploaded += 1
            continue

        blob_client = container_client.get_blob_client(blob_name)
        with file_path.open("rb") as file_data:
            blob_client.upload_blob(file_data, overwrite=True)
        uploaded += 1

    logger.info("training_data_seed:uploaded=%s skipped=%s", uploaded, skipped)
    return {"uploaded": uploaded, "skipped": skipped}


def apply_bootstrap(modeladmin_endpoint: str, bootstrap_config: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    payload = {
        "compose_model_id": bootstrap_config["compose_model_id"],
        "classifier_model_id": bootstrap_config["classifier_model_id"],
        "extractors": bootstrap_config["extractors"],
        "activate": bootstrap_config.get("activate", True),
    }

    url = f"{modeladmin_endpoint.rstrip('/')}/modeladmin/models/bootstrap/apply"
    logger.info("=== Apply bootstrap ===")
    logger.info("bootstrap_url=%s", url)
    logger.info("bootstrap_payload=%s", json.dumps(payload))

    if dry_run:
        return {"success": True, "dry_run": True, "payload": payload}

    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def verify(modeladmin_endpoint: str, backend_endpoint: str, dry_run: bool) -> None:
    logger.info("=== Verify local state ===")

    modeladmin_counts_cmd = [
        "docker",
        "exec",
        "modeladmin-container",
        "python",
        "-c",
        (
            "from modeladmin_sidecar.database.connection import SESSION_LOCAL; "
            "from modeladmin_sidecar.database.models import ReviewCandidateModel, TrainingDatasetModel; "
            "s=SESSION_LOCAL(); "
            "print('review_candidates=' + str(s.query(ReviewCandidateModel).count())); "
            "print('training_datasets=' + str(s.query(TrainingDatasetModel).count())); "
            "s.close()"
        ),
    ]
    run_command(modeladmin_counts_cmd, dry_run=dry_run)

    backend_counts_cmd = [
        "docker",
        "exec",
        "backend-container",
        "python",
        "-c",
        (
            "from app.database.connection import SessionLocal; "
            "from app.database.models import JobModel; "
            "s=SessionLocal(); "
            "print('jobs=' + str(s.query(JobModel).count())); "
            "s.close()"
        ),
    ]
    run_command(backend_counts_cmd, dry_run=dry_run)

    if dry_run:
        logger.info("[dry-run] would call verification APIs")
        return

    candidates_url = f"{modeladmin_endpoint.rstrip('/')}/modeladmin/review-candidates?limit=5"
    active_model_url = f"{modeladmin_endpoint.rstrip('/')}/modeladmin/models/active"
    documents_url = f"{backend_endpoint.rstrip('/')}/documents/?type=all&page=1&limit=5"

    candidates_response = requests.get(candidates_url, timeout=20)
    logger.info("modeladmin_api_items=%s", len(candidates_response.json().get("items", [])))

    active_response = requests.get(active_model_url, timeout=20)
    active_payload = active_response.json()
    compose_id = (
        active_payload.get("item", {}).get("active_model_id")
        or active_payload.get("compose_model", {}).get("compose_model_id")
    )
    logger.info("active_compose_model=%s", compose_id)

    documents_response = requests.get(documents_url, timeout=20)
    docs_payload = documents_response.json()
    if "items" in docs_payload:
        docs_count = len(docs_payload["items"])
    elif "documents" in docs_payload:
        docs_count = len(docs_payload["documents"])
    else:
        docs_count = 0
    logger.info("backend_documents_api_items=%s", docs_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare FinOpt demo environment from model v0")
    parser.add_argument("--no-restart", action="store_true", help="Skip restarting containers")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without mutating state")
    parser.add_argument("--skip-bootstrap", action="store_true", help="Skip bootstrap apply step")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    procurement_root = script_dir.parent

    env_path = procurement_root / ".env.local"
    bootstrap_path = script_dir / "bootstrap.json"

    env_vars = load_env_file(env_path)
    if not bootstrap_path.exists():
        raise FileNotFoundError(f"bootstrap.json not found at: {bootstrap_path}")

    with bootstrap_path.open("r", encoding="utf-8") as handle:
        bootstrap_config = json.load(handle)

    connection_string = env_vars.get("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING not found in .env.local")

    modeladmin_endpoint = env_vars.get("MODELADMIN_EXTERNAL_ENDPOINT", "http://localhost:8100")
    backend_endpoint = env_vars.get("BACKEND_EXTERNAL_ENDPOINT", "http://localhost:8000")
    container_name = env_vars.get("TRAINING_DATA_CONTAINER", "training-data")
    documents_container_name = env_vars.get("AZURE_STORAGE_CONTAINER_NAME", "documents")

    training_data_cfg = bootstrap_config.get("training_data", {})
    dataset_rel_path = training_data_cfg.get("dataset_path")
    if not dataset_rel_path:
        raise ValueError("training_data.dataset_path missing in bootstrap.json")
    dataset_dir = (bootstrap_path.parent / dataset_rel_path).resolve()

    logger.info("script_dir=%s", script_dir)
    logger.info("dataset_dir=%s", dataset_dir)
    logger.info("modeladmin_endpoint=%s", modeladmin_endpoint)

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    table_service = TableServiceClient.from_connection_string(connection_string)

    reset_databases(dry_run=args.dry_run)
    clear_containers(blob_service, [documents_container_name, container_name], dry_run=args.dry_run)
    recreate_tables(table_service, ["Documents", "DocumentMatches"], dry_run=args.dry_run)
    upload_dataset_files(
        blob_service=blob_service,
        container_name=container_name,
        dataset_dir=dataset_dir,
        dry_run=args.dry_run,
    )

    if args.skip_bootstrap:
        logger.info("=== Skip bootstrap (requested) ===")
    else:
        bootstrap_result = apply_bootstrap(modeladmin_endpoint, bootstrap_config, dry_run=args.dry_run)
        logger.info("bootstrap_result=%s", json.dumps(bootstrap_result))

    if args.no_restart:
        logger.info("=== Skip service restart (requested) ===")
    else:
        logger.info("=== Restart services ===")
        expected = ["backend-container", "modeladmin-container"]
        if args.dry_run:
            logger.info("[dry-run] would restart: %s", ", ".join(expected))
        else:
            existing = list_existing_containers()
            to_restart = [c for c in expected if c in existing]
            if not to_restart:
                logger.info("No matching containers found to restart: %s", ", ".join(expected))
            else:
                logger.info("restarting_containers=%s", ", ".join(to_restart))
                run_command(["docker", "restart"] + to_restart, dry_run=args.dry_run)

    verify(modeladmin_endpoint=modeladmin_endpoint, backend_endpoint=backend_endpoint, dry_run=args.dry_run)
    logger.info("DEMO_READY")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        requests.RequestException,
        HttpResponseError,
    ) as exc:
        logger.error("prepare-demo failed: %s", exc, exc_info=True)
        sys.exit(1)
