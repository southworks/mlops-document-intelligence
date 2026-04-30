"""Azure Document Intelligence service wrapper for compose retraining flows."""

from __future__ import annotations
import logging

from modeladmin_sidecar.config import get_modeladmin_sidecar_settings
from shared.adi_helpers import format_adi_error, redact_adi_url


logger = logging.getLogger(__name__)


class DocumentIntelligenceService:
    """Wrapper around Azure Document Intelligence admin operations."""

    def _api_base_url(self) -> str:
        """Return normalized ADI API base that includes /documentintelligence."""
        base = self.endpoint.rstrip("/")
        if base.endswith("/documentintelligence"):
            return base
        return f"{base}/documentintelligence"

    def __init__(self) -> None:
        settings = get_modeladmin_sidecar_settings()
        self.endpoint = str(settings.adi_endpoint or "").strip()
        self.key = str(settings.adi_key or "").strip()

        if not self.endpoint:
            raise ValueError("ADI_ENDPOINT is required")
        if not self.key:
            raise ValueError("ADI_KEY is required")

    def begin_compose_model(
        self,
        *,
        classifier_model_id: str,
        doc_type_model_map: dict[str, str],
        model_name: str,
    ) -> str:
        """Begin compose model and return ADI operation URL."""
        import requests  # pylint: disable=import-outside-toplevel

        classifier_id = (classifier_model_id or "").strip()
        if not classifier_id:
            raise ValueError("classifier_model_id must not be empty")

        cleaned_doc_types = {
            (doc_type or "").strip(): (model_id or "").strip()
            for doc_type, model_id in (doc_type_model_map or {}).items()
            if (doc_type or "").strip() and (model_id or "").strip()
        }
        if not cleaned_doc_types:
            raise ValueError("doc_type_model_map must not be empty")

        model_id = (model_name or "").strip()
        if not model_id:
            raise ValueError("model_name is required")

        url = f"{self._api_base_url()}/documentModels:compose?api-version=2024-11-30"
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"}
        body = {
            "modelId": model_id,
            "classifierId": classifier_id,
            "docTypes": {
                doc_type: {"modelId": extractor_model_id}
                for doc_type, extractor_model_id in cleaned_doc_types.items()
            },
        }

        redacted_url = redact_adi_url(url)
        doc_types = sorted(cleaned_doc_types.keys())
        logger.info(
            "ADI compose request: url=%s model_id=%s classifier_id=%s doc_types=%s",
            redacted_url,
            model_id,
            classifier_id,
            doc_types,
        )

        response = requests.post(url, json=body, headers=headers, timeout=30)
        if response.status_code not in (201, 202):
            raise RuntimeError(
                f"ADI compose model failed ({response.status_code}): {response.text}"
            )
        operation_url = response.headers.get("Operation-Location", "")
        if not operation_url:
            raise RuntimeError("ADI did not return an Operation-Location header")
        return operation_url

    def get_compose_status(self, operation_id: str) -> tuple[str, str | None, str | None]:
        """
        Get compose operation status.

        Returns: (status, adi_model_id, error_message)
        status in {'running', 'succeeded', 'failed'}
        """
        if not operation_id or not operation_id.strip():
            raise ValueError("operation_id is required")

        try:
            operation_status = self.get_operation_status(operation_id)
            return (
                operation_status["status"],
                operation_status["model_id"],
                operation_status["error"],
            )
        except Exception as exc:  # pylint: disable=broad-except
            return "failed", None, str(exc)

    def begin_build_document_model(self, sas_url: str, model_id: str, prefix: str | None = None) -> str:
        """Call ADI POST /documentModels:build and return the operation poll URL."""
        import requests  # pylint: disable=import-outside-toplevel

        url = f"{self._api_base_url()}/documentModels:build?api-version=2024-11-30"
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"}
        source = {"containerUrl": sas_url}
        normalized_prefix = (prefix or "").strip()
        if normalized_prefix:
            source["prefix"] = normalized_prefix
        body = {
            "modelId": model_id,
            "buildMode": "template",
            "azureBlobSource": source,
        }
        redacted_url = redact_adi_url(url)
        redacted_sas_url = redact_adi_url(sas_url)
        logger.info(
            "ADI extractor build request: url=%s model_id=%s container_url=%s prefix=%s",
            redacted_url,
            model_id,
            redacted_sas_url,
            normalized_prefix,
        )
        response = requests.post(url, json=body, headers=headers, timeout=30)
        if response.status_code not in (201, 202):
            raise RuntimeError(
                f"ADI build document model failed ({response.status_code}): {response.text}"
            )
        operation_url = response.headers.get("Operation-Location", "")
        if not operation_url:
            raise RuntimeError("ADI did not return an Operation-Location header")
        return operation_url

    def begin_build_classifier(
        self,
        sas_urls: dict[str, str],
        model_id: str,
        prefixes: dict[str, str] | None = None,
    ) -> str:
        """Call ADI POST /documentClassifiers:build and return the operation poll URL."""
        import requests  # pylint: disable=import-outside-toplevel

        url = f"{self._api_base_url()}/documentClassifiers:build?api-version=2024-11-30"
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"}
        body = {
            "classifierId": model_id,
            "docTypes": {
                doc_type: {
                    "azureBlobSource": {
                        "containerUrl": sas_url,
                        **(
                            {"prefix": (prefixes or {}).get(doc_type, "")}
                            if (prefixes or {}).get(doc_type, "")
                            else {}
                        ),
                    }
                }
                for doc_type, sas_url in sas_urls.items()
            },
        }
        redacted_url = redact_adi_url(url)
        doc_types = sorted(sas_urls.keys())
        prefixes_by_type = {k: (prefixes or {}).get(k, "") for k in doc_types}
        logger.info(
            "ADI classifier build request: url=%s classifier_id=%s doc_types=%s prefixes=%s",
            redacted_url,
            model_id,
            doc_types,
            prefixes_by_type,
        )
        response = requests.post(url, json=body, headers=headers, timeout=30)
        if response.status_code not in (201, 202):
            raise RuntimeError(
                f"ADI build classifier failed ({response.status_code}): {response.text}"
            )
        operation_url = response.headers.get("Operation-Location", "")
        if not operation_url:
            raise RuntimeError("ADI did not return an Operation-Location header")
        return operation_url

    def get_operation_status(self, operation_url: str) -> dict:
        """GET the ADI operation URL and return status dict.

        Returns: {status: 'running'|'succeeded'|'failed', model_id: str|None, error: str|None}
        """
        import requests  # pylint: disable=import-outside-toplevel

        redacted_url = redact_adi_url(operation_url)
        logger.info("ADI get_operation_status url=%s", redacted_url)
        headers = {"Ocp-Apim-Subscription-Key": self.key}
        response = requests.get(operation_url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.info("ADI get_operation_status failed status_code=%s url=%s", response.status_code, redacted_url)
            return {"status": "failed", "model_id": None, "error": response.text}

        data = response.json()
        raw_status = data.get("status", "running").lower()

        if raw_status in ("succeeded", "completed"):
            result = data.get("result", {})
            model_id = result.get("modelId") or result.get("classifierId")
            logger.info("ADI get_operation_status succeeded model_id=%s url=%s", model_id, redacted_url)
            return {"status": "succeeded", "model_id": model_id, "error": None}

        if raw_status == "failed":
            error_info = data.get("error", {})
            error_msg = format_adi_error(error_info)
            logger.info("ADI get_operation_status failed error=%s url=%s", error_msg, redacted_url)
            return {"status": "failed", "model_id": None, "error": error_msg}

        logger.info("ADI get_operation_status running url=%s", redacted_url)
        return {"status": "running", "model_id": None, "error": None}

    def document_model_exists(self, model_id: str) -> bool:
        """Return True when ADI document model exists, False when not found."""
        import requests  # pylint: disable=import-outside-toplevel

        if not model_id or not model_id.strip():
            return False

        url = f"{self._api_base_url()}/documentModels/{model_id}?api-version=2024-11-30"
        logger.info("ADI document_model_exists model_id=%s url=%s", model_id, redact_adi_url(url))
        response = requests.get(url, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=30)

        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False

        logger.info("ADI document_model_exists error model_id=%s status_code=%s", model_id, response.status_code)
        raise RuntimeError(f"ADI model lookup failed for '{model_id}' ({response.status_code}): {response.text}")

    def classifier_exists(self, classifier_id: str) -> bool:
        """Return True when ADI classifier exists, False when not found."""
        import requests  # pylint: disable=import-outside-toplevel

        if not classifier_id or not classifier_id.strip():
            return False

        url = f"{self._api_base_url()}/documentClassifiers/{classifier_id}?api-version=2024-11-30"
        logger.info("ADI classifier_exists classifier_id=%s url=%s", classifier_id, redact_adi_url(url))
        response = requests.get(url, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=30)

        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False

        logger.info("ADI classifier_exists error classifier_id=%s status_code=%s", classifier_id, response.status_code)
        raise RuntimeError(
            f"ADI classifier lookup failed for '{classifier_id}' ({response.status_code}): {response.text}"
        )
