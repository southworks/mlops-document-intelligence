from pydantic import ValidationError
import pytest

from modeladmin_service.modeladmin_core.service_api_contracts import BootstrapImportRequest


def test_bootstrap_contract_accepts_minimal_payload():
    payload = BootstrapImportRequest.model_validate(
        {
            "compose_model_id": "compose-v1",
            "classifier_model_id": "classifier-v1",
            "extractors": {"invoice": "invoice-extractor-v1"},
        }
    )

    assert payload.activate is True
    assert payload.extractors["invoice"] == "invoice-extractor-v1"


def test_bootstrap_contract_rejects_empty_extractors():
    with pytest.raises(ValidationError):
        BootstrapImportRequest.model_validate(
            {
                "compose_model_id": "compose-v1",
                "classifier_model_id": "classifier-v1",
                "extractors": {},
            }
        )


def test_bootstrap_contract_rejects_invalid_extractor_type():
    with pytest.raises(ValidationError):
        BootstrapImportRequest.model_validate(
            {
                "compose_model_id": "compose-v1",
                "classifier_model_id": "classifier-v1",
                "extractors": {"unknown-type": "some-model-v1"},
            }
        )
