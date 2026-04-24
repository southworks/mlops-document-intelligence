# pylint: disable=wrong-import-position,import-outside-toplevel

import json
import os
import threading

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;",
)
os.environ.setdefault("DATABASE_URL", "sqlite:///./invoice_ocr.db")

import pytest

from app.services.queue_jobs import (
    QueueMessageValidationError,
    build_document_job_message,
    parse_document_job_message,
)


# ---------------------------------------------------------------------------
# parse_document_job_message
# ---------------------------------------------------------------------------


def test_parse_document_job_message_valid():
    payload = {
        "documentId": "doc-1",
        "blobUrl": "https://example.com/blob.pdf",
        "originalFilename": "invoice.pdf",
        "blobPath": "documents/doc-1.pdf",
    }
    result = parse_document_job_message(json.dumps(payload))
    assert result["documentId"] == "doc-1"
    assert result["blobUrl"] == "https://example.com/blob.pdf"


def test_parse_document_job_message_missing_document_id():
    payload = {"blobUrl": "https://example.com/blob.pdf"}
    with pytest.raises(QueueMessageValidationError, match="documentId"):
        parse_document_job_message(json.dumps(payload))


def test_parse_document_job_message_missing_blob_url():
    payload = {"documentId": "doc-1"}
    with pytest.raises(QueueMessageValidationError, match="blobUrl"):
        parse_document_job_message(json.dumps(payload))


def test_parse_document_job_message_invalid_json():
    with pytest.raises(QueueMessageValidationError, match="not valid JSON"):
        parse_document_job_message("not-json")


def test_parse_document_job_message_not_an_object():
    with pytest.raises(QueueMessageValidationError, match="JSON object"):
        parse_document_job_message(json.dumps(["list", "not", "dict"]))


# ---------------------------------------------------------------------------
# build_document_job_message
# ---------------------------------------------------------------------------


def test_build_document_job_message_roundtrip():
    raw = build_document_job_message(
        document_id="job-42",
        blob_url="https://storage.example.com/docs/job-42.pdf",
        original_filename="receipt.pdf",
        blob_path="documents/job-42.pdf",
    )
    parsed = json.loads(raw)
    assert parsed["documentId"] == "job-42"
    assert parsed["blobUrl"] == "https://storage.example.com/docs/job-42.pdf"
    assert parsed["originalFilename"] == "receipt.pdf"
    assert parsed["blobPath"] == "documents/job-42.pdf"


# ---------------------------------------------------------------------------
# Worker: delete-on-success / retain-on-failure
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, payload: dict):
        self.content = json.dumps(payload)
        self.id = "msg-id-1"
        self.pop_receipt = "pop-receipt-1"


class _FakePage:
    def __init__(self, messages):
        self._messages = messages

    def __iter__(self):
        return iter(self._messages)


class _FakePageIterator:
    def __init__(self, pages):
        self._pages = pages

    def by_page(self):
        return iter(self._pages)


def _make_fake_queue_message_iter(messages):
    return _FakePageIterator([_FakePage(messages)])


def _make_queue_client(messages, deleted):
    """Build a fake queue client that returns messages once then empty pages."""
    call_count = [0]

    class _FakeQueueClient:
        def create_queue(self):
            pass

        def receive_messages(self, **_kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_fake_queue_message_iter(messages)
            # Subsequent calls return empty — triggers stop_event.wait path
            return _make_fake_queue_message_iter([])

        def delete_message(self, msg_id, pop_receipt):
            deleted.append((msg_id, pop_receipt))

    return _FakeQueueClient()


def test_worker_deletes_message_on_success(monkeypatch):
    """Worker must delete the message when processing succeeds."""
    from app import worker

    valid_payload = {
        "documentId": "doc-ok",
        "blobUrl": "https://example.com/ok.pdf",
        "originalFilename": "ok.pdf",
        "blobPath": "documents/ok.pdf",
    }

    deleted = []
    processed_calls = []

    monkeypatch.setattr(worker, "get_queue_client", lambda: _make_queue_client([_FakeMessage(valid_payload)], deleted))
    monkeypatch.setattr(worker, "ensure_queue_exists", lambda _qc: None)

    def _mock_process(**kwargs):
        processed_calls.append(kwargs)
        return {"success": True}

    monkeypatch.setattr(worker, "process_document_job", _mock_process)

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(worker, "SessionLocal", lambda: _FakeSession())

    # After the empty-page second call, stop_event.wait is called — stop the loop there
    def _patched_wait(self_event, timeout=None):
        self_event.set()
        return True

    monkeypatch.setattr(threading.Event, "wait", _patched_wait)

    worker.run_worker()

    assert len(deleted) == 1
    assert deleted[0] == ("msg-id-1", "pop-receipt-1")
    assert processed_calls[0]["document_id"] == "doc-ok"


def test_worker_retains_message_on_processing_failure(monkeypatch):
    """Worker must NOT delete the message when processing raises an exception."""
    from app import worker

    valid_payload = {
        "documentId": "doc-fail",
        "blobUrl": "https://example.com/fail.pdf",
        "originalFilename": "fail.pdf",
        "blobPath": "documents/fail.pdf",
    }

    deleted = []

    monkeypatch.setattr(worker, "get_queue_client", lambda: _make_queue_client([_FakeMessage(valid_payload)], deleted))
    monkeypatch.setattr(worker, "ensure_queue_exists", lambda _qc: None)

    def _failing_process(**_kwargs):
        raise RuntimeError("extraction failed")

    monkeypatch.setattr(worker, "process_document_job", _failing_process)

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(worker, "SessionLocal", lambda: _FakeSession())

    def _patched_wait(self_event, timeout=None):
        self_event.set()
        return True

    monkeypatch.setattr(threading.Event, "wait", _patched_wait)

    worker.run_worker()

    assert len(deleted) == 0, "Message should NOT be deleted when processing fails"


def test_worker_deletes_invalid_messages_immediately(monkeypatch):
    """Worker must delete messages with invalid payloads to avoid poison loops."""
    from app import worker

    deleted = []

    class _InvalidMessage:
        content = "not-json-at-all"
        id = "msg-bad"
        pop_receipt = "pop-bad"

    monkeypatch.setattr(worker, "get_queue_client", lambda: _make_queue_client([_InvalidMessage()], deleted))
    monkeypatch.setattr(worker, "ensure_queue_exists", lambda _qc: None)
    monkeypatch.setattr(worker, "process_document_job", lambda **_kwargs: None)

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(worker, "SessionLocal", lambda: _FakeSession())

    def _patched_wait(self_event, timeout=None):
        self_event.set()
        return True

    monkeypatch.setattr(threading.Event, "wait", _patched_wait)

    worker.run_worker()

    assert len(deleted) == 1, "Invalid (poison) messages should be deleted immediately"
    assert deleted[0] == ("msg-bad", "pop-bad")
