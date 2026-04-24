"""Runtime boundary port for ModelAdmin candidate intake."""

from dataclasses import dataclass
import logging
import time
from typing import Optional, Protocol

import httpx

from app.config import Settings, get_settings
from app.modeladmin_core.boundary_contracts import CandidateCreatedV1Payload, CandidateCreatedV1Response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelAdminIntakeResult:
    accepted: bool
    candidate_id: Optional[str] = None
    transport: str = "inprocess"
    fallback_used: bool = False


class ModelAdminPort(Protocol):
    def intake_candidate_created(self, payload: CandidateCreatedV1Payload) -> ModelAdminIntakeResult:
        """Dispatch candidate-created payload to ModelAdmin runtime boundary."""


class ExternalBoundaryClient(Protocol):
    def post_candidate_created(
        self,
        payload: CandidateCreatedV1Payload,
        correlation_id: str,
    ) -> CandidateCreatedV1Response:
        """Send candidate-created payload to external ModelAdmin runtime."""


class DisabledModelAdminPort:
    """Safe no-op adapter when external boundary is unavailable."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def intake_candidate_created(self, payload: CandidateCreatedV1Payload) -> ModelAdminIntakeResult:
        logger.warning(
            "ModelAdmin intake skipped",
            extra={
                "reason": self.reason,
                "document_id": payload.document_id,
                "correlation_id": payload.idempotency_key,
            },
        )
        return ModelAdminIntakeResult(
            accepted=False,
            transport="disabled",
        )


class ExternalModelAdminPort:
    """Adapter for future external ModelAdmin service boundary."""

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: int = 5,
        retry_attempts: int = 2,
        retry_backoff_ms: int = 200,
        api_key: Optional[str] = None,
        client: Optional[ExternalBoundaryClient] = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(0, retry_attempts)
        self.retry_backoff_ms = max(0, retry_backoff_ms)
        self.api_key = (api_key or "").strip()
        self.client = client or HttpxExternalBoundaryClient(
            self.endpoint,
            self.timeout_seconds,
            self.api_key,
        )

    def intake_candidate_created(self, payload: CandidateCreatedV1Payload) -> ModelAdminIntakeResult:
        correlation_id = payload.idempotency_key
        attempt_count = self.retry_attempts + 1

        try:
            response_payload = None
            for attempt in range(1, attempt_count + 1):
                try:
                    response_payload = self.client.post_candidate_created(
                        payload=payload,
                        correlation_id=correlation_id,
                    )
                    break
                except (httpx.TimeoutException, httpx.HTTPError):
                    if attempt >= attempt_count:
                        raise
                    logger.warning(
                        "External ModelAdmin intake attempt failed; retrying",
                        extra={
                            "endpoint": self.endpoint,
                            "timeout_seconds": self.timeout_seconds,
                            "document_id": payload.document_id,
                            "correlation_id": correlation_id,
                            "attempt": attempt,
                            "max_attempts": attempt_count,
                        },
                    )
                    if self.retry_backoff_ms > 0:
                        time.sleep(self.retry_backoff_ms / 1000.0)

            return ModelAdminIntakeResult(
                accepted=bool(response_payload and response_payload.accepted),
                candidate_id=response_payload.candidate_id if response_payload else None,
                transport="external",
            )
        except httpx.TimeoutException:
            logger.exception(
                "External ModelAdmin intake timed out",
                extra={
                    "endpoint": self.endpoint,
                    "timeout_seconds": self.timeout_seconds,
                    "document_id": payload.document_id,
                    "correlation_id": correlation_id,
                },
            )
            return ModelAdminIntakeResult(
                accepted=False,
                transport="external",
            )
        except Exception:
            logger.exception(
                "External ModelAdmin intake failed",
                extra={
                    "endpoint": self.endpoint,
                    "timeout_seconds": self.timeout_seconds,
                    "document_id": payload.document_id,
                    "correlation_id": correlation_id,
                },
            )
            return ModelAdminIntakeResult(
                accepted=False,
                transport="external",
            )


class HttpxExternalBoundaryClient:
    def __init__(self, endpoint: str, timeout_seconds: int = 5, api_key: str = "") -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_key = (api_key or "").strip()

    def post_candidate_created(
        self,
        payload: CandidateCreatedV1Payload,
        correlation_id: str,
    ) -> CandidateCreatedV1Response:
        headers = {
            "Content-Type": "application/json",
            "X-Idempotency-Key": payload.idempotency_key,
            "X-Correlation-Id": correlation_id,
        }
        if self.api_key:
            headers["X-Service-Auth"] = self.api_key

        response = httpx.post(
            f"{self.endpoint}/boundary/modeladmin/candidate-created",
            headers=headers,
            json=payload.model_dump(mode="json"),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        response_payload = response.json() if response.content else {"accepted": True}
        return CandidateCreatedV1Response.model_validate(response_payload)


def build_candidate_created_payload(
    *,
    document_id: str,
    blob_path: str,
    processed_blob_path: str,
    document_type: str,
    classification_confidence: Optional[float],
    compose_model_id: str,
    source_channel: str,
    trigger_reason: str,
    has_low_confidence: bool,
    original_filename: Optional[str],
    structured_data: Optional[dict],
    error_details: Optional[str],
) -> CandidateCreatedV1Payload:
    return CandidateCreatedV1Payload(
        document_id=document_id,
        compose_model_id=compose_model_id,
        idempotency_key=f"{document_id}:{compose_model_id}",
        blob_path=blob_path,
        processed_blob_path=processed_blob_path,
        source_channel=source_channel,
        predicted_document_type=document_type,
        classification_confidence=classification_confidence,
        has_low_confidence=has_low_confidence,
        trigger_reason=trigger_reason,
        original_filename=original_filename,
        structured_data=structured_data,
        processing_error=error_details,
    )


def intake_candidate_created(
    payload: CandidateCreatedV1Payload,
    port: Optional[ModelAdminPort] = None,
    settings_override: Optional[Settings] = None,
) -> ModelAdminIntakeResult:
    adapter = port or _resolve_port_from_settings(settings_override or get_settings())
    return adapter.intake_candidate_created(payload)


def resolve_active_model_id(settings_override: Optional[Settings] = None) -> Optional[str]:
    settings = settings_override or get_settings()
    endpoint = (settings.modeladmin_external_endpoint or "").strip()
    if not endpoint:
        return None

    headers = {"Accept": "application/json"}
    if settings.modeladmin_external_api_key:
        headers["X-Service-Auth"] = settings.modeladmin_external_api_key

    try:
        response = httpx.get(
            f"{endpoint.rstrip('/')}/modeladmin/models/active",
            headers=headers,
            timeout=settings.modeladmin_external_timeout_seconds,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json() if response.content else {}
        item = payload.get("item") if isinstance(payload, dict) else None
        if not isinstance(item, dict):
            return None
        model_id = item.get("active_model_id")
        return model_id.strip() if isinstance(model_id, str) and model_id.strip() else None
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Failed to resolve active model id from ModelAdmin",
            extra={"endpoint": endpoint},
            exc_info=True,
        )
        return None


def _resolve_port_from_settings(settings: Settings) -> ModelAdminPort:
    endpoint = (settings.modeladmin_external_endpoint or "").strip()
    if not endpoint:
        return DisabledModelAdminPort(
            "MODELADMIN_EXTERNAL_ENDPOINT is missing; backend direct persistence is disabled",
        )

    return ExternalModelAdminPort(
        endpoint=endpoint,
        timeout_seconds=settings.modeladmin_external_timeout_seconds,
        retry_attempts=settings.modeladmin_external_retry_attempts,
        retry_backoff_ms=settings.modeladmin_external_retry_backoff_ms,
        api_key=settings.modeladmin_external_api_key,
    )
