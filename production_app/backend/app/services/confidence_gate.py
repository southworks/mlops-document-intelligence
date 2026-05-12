"""Confidence Gate — evaluates whether a processed document should be forwarded
to ModelAdmin as a review candidate (``compute_confidence``), then dispatches
the candidate payload to the ModelAdmin sidecar (``notify_modeladmin``)."""

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional, Protocol

import httpx

from app.config import Settings, get_settings
from app.modeladmin_core.boundary_contracts import CandidateCreatedV1Payload, CandidateCreatedV1Response
from app.modeladmin_core.contracts import DocumentProcessingOutcome
from app.modeladmin_core.policy import evaluate_candidate_decision

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfidenceScore:
    """Outcome of policy evaluation for a processed document."""
    should_notify: bool
    trigger_reason: Optional[str]
    has_low_confidence: bool


@dataclass(frozen=True)
class NotifyResult:
    accepted: bool
    candidate_id: Optional[str] = None
    transport: str = "inprocess"
    fallback_used: bool = False


def _extract_low_confidence_field_names(
    structured_data: Optional[Dict[str, Any]],
    threshold: float,
) -> List[str]:
    """Extract names of fields whose confidence is below threshold."""
    if not structured_data or not isinstance(structured_data, dict):
        return []

    field_names: list[str] = []

    for field_name, field_value in structured_data.items():
        if isinstance(field_value, dict):
            confidence = field_value.get("confidence")
            if isinstance(confidence, (int, float)) and float(confidence) < threshold:
                field_names.append(field_name)
            continue

        if isinstance(field_value, list):
            for entry in field_value:
                if not isinstance(entry, dict):
                    continue
                for sub_field_name, sub_field_value in entry.items():
                    if not isinstance(sub_field_value, dict):
                        continue
                    confidence = sub_field_value.get("confidence")
                    if isinstance(confidence, (int, float)) and float(confidence) < threshold:
                        field_names.append(f"{field_name}.{sub_field_name}")

    return list(dict.fromkeys(field_names))


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

def compute_confidence(
    document_type: str,
    classification_confidence: Optional[float],
    structured_data: Optional[Dict[str, Any]],
    settings_override: Optional[Settings] = None,
) -> ConfidenceScore:
    """Evaluate policy for a processed document and return a ConfidenceScore.

    Determines whether the document should be forwarded to ModelAdmin as a
    review candidate, and what the trigger reason is.
    """
    cfg = settings_override or get_settings()
    outcome = DocumentProcessingOutcome(
        document_id="policy-probe",
        blob_path="",
        processed_blob_path="",
        predicted_document_type=document_type,
        classification_confidence=classification_confidence,
        compose_model_id="policy-probe",
        source_channel="policy-probe",
        structured_data=structured_data,
    )
    decision = evaluate_candidate_decision(
        outcome=outcome,
        confidence_threshold=cfg.modeladmin_confidence_threshold,
        always_flag_unknown=cfg.modeladmin_always_flag_unknown,
    )
    return ConfidenceScore(
        should_notify=decision.should_create,
        trigger_reason=decision.trigger_reason,
        has_low_confidence=decision.has_low_confidence,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def notify_modeladmin(
    payload: CandidateCreatedV1Payload,
    settings_override: Optional[Settings] = None,
) -> NotifyResult:
    """Send a candidate-created payload to the ModelAdmin sidecar.

    Selects the appropriate transport adapter based on settings and dispatches
    the payload.
    """
    adapter = _resolve_adapter(settings_override or get_settings())
    return adapter.intake(payload)


# ---------------------------------------------------------------------------
# Payload builder (convenience — keeps all gate logic co-located)
# ---------------------------------------------------------------------------

def build_candidate_payload(
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
    settings_override: Optional[Settings] = None,
) -> CandidateCreatedV1Payload:
    cfg = settings_override or get_settings()
    low_confidence_field_names = _extract_low_confidence_field_names(
        structured_data,
        cfg.modeladmin_confidence_threshold,
    )

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
        low_confidence_field_names=low_confidence_field_names or None,
    )


# ---------------------------------------------------------------------------
# Active model resolver (used by document_processor to pick the compose model)
# ---------------------------------------------------------------------------

def resolve_active_model_id(settings_override: Optional[Settings] = None) -> Optional[str]:
    """Query ModelAdmin sidecar for the currently active compose model ID."""
    settings = settings_override or get_settings()
    endpoint = (settings.modeladmin_external_endpoint or "").strip()
    if not endpoint:
        return None

    headers: Dict[str, str] = {"Accept": "application/json"}
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


# ---------------------------------------------------------------------------
# Internal transport adapters
# ---------------------------------------------------------------------------

class BoundaryClientProtocol(Protocol):
    def post_candidate_created(
        self,
        payload: CandidateCreatedV1Payload,
        correlation_id: str,
    ) -> CandidateCreatedV1Response: ...


class DisabledAdapter:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def intake(self, payload: CandidateCreatedV1Payload) -> NotifyResult:
        logger.warning(
            "ModelAdmin notify skipped",
            extra={"reason": self.reason, "document_id": payload.document_id},
        )
        return NotifyResult(accepted=False, transport="disabled")


class ExternalAdapter:
    def __init__(
        self,
        endpoint: str,
        timeout_seconds: int = 5,
        retry_attempts: int = 2,
        retry_backoff_ms: int = 200,
        api_key: Optional[str] = None,
        client: Optional[BoundaryClientProtocol] = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(0, retry_attempts)
        self.retry_backoff_ms = max(0, retry_backoff_ms)
        self.api_key = (api_key or "").strip()
        self.client: BoundaryClientProtocol = client or HttpxClient(
            self.endpoint, self.timeout_seconds, self.api_key
        )

    def intake(self, payload: CandidateCreatedV1Payload) -> NotifyResult:
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
                        "ModelAdmin notify attempt failed; retrying",
                        extra={
                            "endpoint": self.endpoint,
                            "document_id": payload.document_id,
                            "attempt": attempt,
                            "max_attempts": attempt_count,
                        },
                    )
                    if self.retry_backoff_ms > 0:
                        time.sleep(self.retry_backoff_ms / 1000.0)

            return NotifyResult(
                accepted=bool(response_payload and response_payload.accepted),
                candidate_id=response_payload.candidate_id if response_payload else None,
                transport="external",
            )
        except httpx.TimeoutException:
            logger.exception(
                "ModelAdmin notify timed out",
                extra={"endpoint": self.endpoint, "document_id": payload.document_id},
            )
            return NotifyResult(accepted=False, transport="external")
        except Exception:
            logger.exception(
                "ModelAdmin notify failed",
                extra={"endpoint": self.endpoint, "document_id": payload.document_id},
            )
            return NotifyResult(accepted=False, transport="external")


class HttpxClient:
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


def _resolve_adapter(settings: Settings) -> DisabledAdapter | ExternalAdapter:
    endpoint = (settings.modeladmin_external_endpoint or "").strip()
    if not endpoint:
        return DisabledAdapter(
            "MODELADMIN_EXTERNAL_ENDPOINT is missing; ModelAdmin notify is disabled"
        )
    return ExternalAdapter(
        endpoint=endpoint,
        timeout_seconds=settings.modeladmin_external_timeout_seconds,
        retry_attempts=settings.modeladmin_external_retry_attempts,
        retry_backoff_ms=settings.modeladmin_external_retry_backoff_ms,
        api_key=settings.modeladmin_external_api_key,
    )


