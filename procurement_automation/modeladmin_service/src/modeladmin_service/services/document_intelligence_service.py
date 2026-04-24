"""Azure Document Intelligence service wrapper for compose retraining flows."""

from __future__ import annotations
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from modeladmin_service.config import get_modeladmin_service_settings


logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("sqlalchemy.engine.Engine")


class DocumentIntelligenceService:
    """Wrapper around Azure Document Intelligence admin operations."""

    def _api_base_url(self) -> str:
        """Return normalized ADI API base that includes /documentintelligence."""
        base = self.endpoint.rstrip("/")
        if base.endswith("/documentintelligence"):
            return base
        return f"{base}/documentintelligence"

    def __init__(self) -> None:
        settings = get_modeladmin_service_settings()
        self.endpoint = str(settings.adi_endpoint or "").strip()
        self.key = str(settings.adi_key or "").strip()

        if not self.endpoint:
            raise ValueError("ADI_ENDPOINT is required")
        if not self.key:
            raise ValueError("ADI_KEY is required")

    @staticmethod
    def _redact_url(url: str) -> str:
        """Redact secret-bearing query parameters when logging URLs."""
        try:
            parts = urlsplit(url)
            if not parts.query:
                return url
            redacted = []
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                if key.lower() in {"sig", "se", "sp", "sr", "skoid", "sktid", "skt", "ske", "skv"}:
                    redacted.append((key, "***"))
                else:
                    redacted.append((key, value))
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment))
        except Exception:  # pylint: disable=broad-except
            return "<redaction-failed>"

    @staticmethod
    def _format_adi_error(error_info: dict | None) -> str:
        """Flatten ADI error payloads into a readable one-line message."""
        if not isinstance(error_info, dict):
            return "Unknown ADI error"

        parts: list[str] = []

        top_message = str(error_info.get("message") or "").strip()
        if top_message:
            parts.append(top_message)

        code = str(error_info.get("code") or "").strip()
        if code and code not in parts:
            parts.append(f"code={code}")

        details = error_info.get("details")
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                detail_message = str(detail.get("message") or "").strip()
                detail_target = str(detail.get("target") or "").strip()
                if detail_message and detail_target:
                    parts.append(f"{detail_target}: {detail_message}")
                elif detail_message:
                    parts.append(detail_message)

        inner = error_info.get("innererror")
        if isinstance(inner, dict):
            inner_message = str(inner.get("message") or "").strip()
            inner_code = str(inner.get("code") or "").strip()
            if inner_message:
                parts.append(inner_message)
            if inner_code:
                parts.append(f"inner_code={inner_code}")

            inner_details = inner.get("details")
            if isinstance(inner_details, list):
                for detail in inner_details:
                    if isinstance(detail, dict):
                        msg = str(detail.get("message") or "").strip()
                        if msg:
                            parts.append(msg)

        # Preserve order but remove duplicates/noise.
        deduped: list[str] = []
        seen: set[str] = set()
        for part in parts:
            normalized = part.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)

        return " | ".join(deduped) if deduped else "Unknown ADI error"

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

        redacted_url = self._redact_url(url)
        doc_types = sorted(cleaned_doc_types.keys())
        logger.warning(
            "ADI compose request: url=%s model_id=%s classifier_id=%s doc_types=%s",
            redacted_url,
            model_id,
            classifier_id,
            doc_types,
        )
        audit_logger.warning(
            "ADI compose request: url=%s model_id=%s classifier_id=%s doc_types=%s",
            redacted_url,
            model_id,
            classifier_id,
            doc_types,
        )
        print(
            f"ADI_AUDIT compose url={redacted_url} model_id={model_id} classifier_id={classifier_id} doc_types={doc_types}",
            flush=True,
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
        redacted_url = self._redact_url(url)
        redacted_sas_url = self._redact_url(sas_url)
        logger.warning(
            "ADI extractor build request: url=%s model_id=%s container_url=%s prefix=%s",
            redacted_url,
            model_id,
            redacted_sas_url,
            normalized_prefix,
        )
        audit_logger.warning(
            "ADI extractor build request: url=%s model_id=%s container_url=%s prefix=%s",
            redacted_url,
            model_id,
            redacted_sas_url,
            normalized_prefix,
        )
        print(
            f"ADI_AUDIT extractor_build url={redacted_url} model_id={model_id} container_url={redacted_sas_url} prefix={normalized_prefix}",
            flush=True,
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
        redacted_url = self._redact_url(url)
        doc_types = sorted(sas_urls.keys())
        prefixes_by_type = {k: (prefixes or {}).get(k, "") for k in doc_types}
        logger.warning(
            "ADI classifier build request: url=%s classifier_id=%s doc_types=%s prefixes=%s",
            redacted_url,
            model_id,
            doc_types,
            prefixes_by_type,
        )
        audit_logger.warning(
            "ADI classifier build request: url=%s classifier_id=%s doc_types=%s prefixes=%s",
            redacted_url,
            model_id,
            doc_types,
            prefixes_by_type,
        )
        print(
            f"ADI_AUDIT classifier_build url={redacted_url} classifier_id={model_id} doc_types={doc_types} prefixes={prefixes_by_type}",
            flush=True,
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

        redacted_url = self._redact_url(operation_url)
        print(f"ADI_AUDIT get_operation_status url={redacted_url}", flush=True)
        headers = {"Ocp-Apim-Subscription-Key": self.key}
        response = requests.get(operation_url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"ADI_AUDIT get_operation_status_failed status_code={response.status_code} url={redacted_url}", flush=True)
            return {"status": "failed", "model_id": None, "error": response.text}

        data = response.json()
        raw_status = data.get("status", "running").lower()

        if raw_status in ("succeeded", "completed"):
            result = data.get("result", {})
            model_id = result.get("modelId") or result.get("classifierId")
            print(f"ADI_AUDIT get_operation_status_succeeded model_id={model_id} url={redacted_url}", flush=True)
            return {"status": "succeeded", "model_id": model_id, "error": None}

        if raw_status == "failed":
            error_info = data.get("error", {})
            error_msg = self._format_adi_error(error_info)
            print(f"ADI_AUDIT get_operation_status_failed error={error_msg} url={redacted_url}", flush=True)
            return {"status": "failed", "model_id": None, "error": error_msg}

        print(f"ADI_AUDIT get_operation_status_running url={redacted_url}", flush=True)
        return {"status": "running", "model_id": None, "error": None}

    def document_model_exists(self, model_id: str) -> bool:
        """Return True when ADI document model exists, False when not found."""
        import requests  # pylint: disable=import-outside-toplevel

        if not model_id or not model_id.strip():
            return False

        url = f"{self._api_base_url()}/documentModels/{model_id}?api-version=2024-11-30"
        print(f"ADI_AUDIT document_model_exists model_id={model_id} url={self._redact_url(url)}", flush=True)
        response = requests.get(url, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=30)

        if response.status_code == 200:
            print(f"ADI_AUDIT document_model_exists_found model_id={model_id}", flush=True)
            return True
        if response.status_code == 404:
            print(f"ADI_AUDIT document_model_exists_not_found model_id={model_id}", flush=True)
            return False

        print(f"ADI_AUDIT document_model_exists_error model_id={model_id} status_code={response.status_code}", flush=True)
        raise RuntimeError(f"ADI model lookup failed for '{model_id}' ({response.status_code}): {response.text}")

    def classifier_exists(self, classifier_id: str) -> bool:
        """Return True when ADI classifier exists, False when not found."""
        import requests  # pylint: disable=import-outside-toplevel

        if not classifier_id or not classifier_id.strip():
            return False

        url = f"{self._api_base_url()}/documentClassifiers/{classifier_id}?api-version=2024-11-30"
        print(f"ADI_AUDIT classifier_exists classifier_id={classifier_id} url={self._redact_url(url)}", flush=True)
        response = requests.get(url, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=30)

        if response.status_code == 200:
            print(f"ADI_AUDIT classifier_exists_found classifier_id={classifier_id}", flush=True)
            return True
        if response.status_code == 404:
            print(f"ADI_AUDIT classifier_exists_not_found classifier_id={classifier_id}", flush=True)
            return False

        print(f"ADI_AUDIT classifier_exists_error classifier_id={classifier_id} status_code={response.status_code}", flush=True)
        raise RuntimeError(
            f"ADI classifier lookup failed for '{classifier_id}' ({response.status_code}): {response.text}"
        )
