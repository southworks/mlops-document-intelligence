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

from app.services.confidence_gate import compute_confidence
from processing.storage import resolve_candidate_destination_folder

def test_unknown_classification_routes_to_unknown_folder() -> None:
    score = compute_confidence(
        document_type="unknown",
        classification_confidence=0.99,
        structured_data={},
    )
    assert score.should_notify is True
    assert score.trigger_reason == "unknown_classification"
    assert resolve_candidate_destination_folder(score.trigger_reason) == "unknown_classification"

def test_low_confidence_routes_to_low_confidence_classification_folder() -> None:
    score = compute_confidence(
        document_type="invoice",
        classification_confidence=0.10,
        structured_data={"invoice_number": {"value": "INV-1", "confidence": 0.99}},
    )
    assert score.should_notify is True
    assert score.trigger_reason == "low_confidence"
    assert resolve_candidate_destination_folder(score.trigger_reason) == "low_confidence"

def test_low_field_confidence_routes_to_low_confidence_fields_folder() -> None:
    score = compute_confidence(
        document_type="invoice",
        classification_confidence=0.95,
        structured_data={"invoice_number": {"value": "INV-1", "confidence": 0.10}},
    )
    assert score.should_notify is True
    assert score.trigger_reason == "low_field_confidence"
    assert resolve_candidate_destination_folder(score.trigger_reason) == "low_field_confidence"

def test_non_candidate_flow_has_no_folder_override() -> None:
    score = compute_confidence(
        document_type="invoice",
        classification_confidence=0.99,
        structured_data={"invoice_number": {"value": "INV-1", "confidence": 0.99}},
    )
    assert score.should_notify is False
    assert score.trigger_reason is None
    assert resolve_candidate_destination_folder(score.trigger_reason) is None
