"""Container runtime switch for API or worker mode."""

import logging
import os
import sys

from app.worker import run_worker

logger = logging.getLogger(__name__)


def run_api() -> None:
    """Exec gunicorn API server process."""
    api_workers = os.getenv("API_WORKERS", "2")
    command = [
        "gunicorn",
        "-k",
        "uvicorn.workers.UvicornWorker",
        "--bind",
        "0.0.0.0:8000",
        "--workers",
        api_workers,
        "--timeout",
        "600",
        "--graceful-timeout",
        "120",
        "app.main:app",
    ]
    os.execvp(command[0], command)


def main() -> None:
    """Run mode selected by MODE env var."""
    mode = os.getenv("MODE", "api").strip().lower()

    if mode == "api":
        run_api()
        return

    if mode == "worker":
        run_worker()
        return

    logger.error("Unsupported MODE '%s'. Expected 'api' or 'worker'.", mode)
    sys.exit(1)


if __name__ == "__main__":
    main()
