"""Azure Document Intelligence helper utilities.

Module-level functions for URL redaction and error formatting — stateless
utilities used by any service that calls the ADI REST API.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_ADI_SENSITIVE_PARAMS: frozenset[str] = frozenset(
    {"sig", "se", "sp", "sr", "skoid", "sktid", "skt", "ske", "skv"}
)


def redact_adi_url(url: str) -> str:
    """Redact secret-bearing query parameters from an ADI URL for safe logging.

    Returns the original URL with any sensitive SAS/token query parameters
    replaced by "***".  Falls back to "<redaction-failed>" on any parse error.
    """
    try:
        parts = urlsplit(url)
        if not parts.query:
            return url
        redacted = [
            (key, "***") if key.lower() in _ADI_SENSITIVE_PARAMS else (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment)
        )
    except Exception:  # pylint: disable=broad-except
        return "<redaction-failed>"


def format_adi_error(error_info: dict | None) -> str:
    """Flatten an ADI error payload dict into a readable one-line message.

    Handles nested ``details`` and ``innererror`` fields.  Deduplicates
    repeated messages and returns "Unknown ADI error" if nothing useful is
    found.
    """
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
