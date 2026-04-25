"""CLI for ModelAdmin bootstrap import."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from modeladmin_sidecar.database.connection import SESSION_LOCAL
from modeladmin_sidecar.modeladmin_core.service_api_contracts import BootstrapImportRequest
from modeladmin_sidecar.services.bootstrap_import_service import BootstrapImportService, BootstrapValidationError
from modeladmin_sidecar.services.document_intelligence_service import DocumentIntelligenceService


def _load_payload(file_path: str) -> BootstrapImportRequest:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    return BootstrapImportRequest.model_validate(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap ModelAdmin using external ADI model IDs")
    parser.add_argument("--file", required=True, help="Path to bootstrap JSON file")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate payload and ADI model existence without DB writes",
    )
    args = parser.parse_args()

    payload = _load_payload(args.file)
    adi_service = DocumentIntelligenceService()

    # Get directory of bootstrap.json for resolving relative paths
    bootstrap_dir = Path(args.file).parent.absolute()

    if args.validate_only:
        service = BootstrapImportService(db=None, adi_service=adi_service, bootstrap_file_dir=str(bootstrap_dir))
        result = service.validate_against_adi(payload)
        print(json.dumps(result, indent=2))
        return 0

    session = SESSION_LOCAL()
    try:
        service = BootstrapImportService(db=session, adi_service=adi_service, bootstrap_file_dir=str(bootstrap_dir))
        result = service.apply(payload)
        print(json.dumps(result, indent=2))
        return 0
    except BootstrapValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
