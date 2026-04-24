"""Queue-driven worker runtime for document processing."""

import logging
import signal
import threading

from app.config import get_settings
from app.database.connection import SessionLocal
from app.model_registry import initialize_from_config
from app.services.document_processor import process_document_job
from app.services.queue_jobs import (
    QueueMessageValidationError,
    ensure_queue_exists,
    get_queue_client,
    parse_document_job_message,
)

settings = get_settings()
logger = logging.getLogger(__name__)


def run_worker() -> None:
    """Run polling loop that consumes queue messages and processes documents."""
    logging.basicConfig(level=logging.INFO)
    stop_event = threading.Event()

    def _handle_stop(_signum, _frame):
        logger.info("Worker shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    queue_client = get_queue_client()
    ensure_queue_exists(queue_client)

    # Match API startup behavior: initialize model registry once from runtime config.
    initialize_from_config(compose_model_id=settings.azure_compose_model_id)

    logger.info("Worker started. queue=%s", settings.azure_storage_queue_name)

    while not stop_event.is_set():
        processed_message = False

        try:
            messages = queue_client.receive_messages(
                messages_per_page=1,
                visibility_timeout=settings.worker_visibility_timeout_seconds,
            )

            for page in messages.by_page():
                for message in page:
                    processed_message = True
                    try:
                        payload = parse_document_job_message(message.content)
                        document_id = payload["documentId"]
                        blob_path_or_url = payload.get("blobPath") or payload["blobUrl"]
                        original_filename = payload.get("originalFilename") or document_id

                        with SessionLocal() as db:
                            process_document_job(
                                document_id=document_id,
                                blob_path_or_url=blob_path_or_url,
                                original_filename=original_filename,
                                db=db,
                                source_channel="queue-worker",
                            )

                        queue_client.delete_message(message.id, message.pop_receipt)
                        logger.info("Processed and deleted message for documentId=%s", document_id)
                    except QueueMessageValidationError as validation_error:
                        logger.error("Invalid queue message: %s", str(validation_error))
                        queue_client.delete_message(message.id, message.pop_receipt)
                    except Exception as processing_error:
                        logger.exception("Processing failed; message retained for retry: %s", str(processing_error))
                break

        except Exception as poll_error:
            logger.exception("Queue polling failed: %s", str(poll_error))

        if not processed_message:
            stop_event.wait(settings.worker_poll_interval_seconds)

    logger.info("Worker stopped")
