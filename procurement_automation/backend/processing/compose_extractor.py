"""Compose model extractor with JMESPath-driven field mapping."""

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jmespath

from app.models.document_type import normalize_document_type_value

logger = logging.getLogger(__name__)
SCHEMA_DIR = Path(__file__).with_name("jmespath")
_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


def parse_compose_result(raw_adi: dict) -> dict:
    """Parse a raw ADI response dict into a normalized mapped projection."""
    if not raw_adi.get("documents") or len(raw_adi["documents"]) == 0:
        logger.warning("No documents found in compose model result")
        return _empty_projection()

    doc = raw_adi["documents"][0]
    raw_doc_type = doc.get("docType") or doc.get("doc_type") or "unknown"
    confidence = _to_float(doc.get("confidence"), 0.0)
    doc_type = normalize_document_type_value(raw_doc_type)
    logger.info("📊 Raw Azure classification: %s", raw_doc_type)
    logger.info("✅ Normalized document type: %s (confidence: %s)", doc_type, confidence)

    structured_data = _extract_structured_data_by_schema(doc_type, raw_adi)
    logger.info("Extracted %s fields", len([v for v in structured_data.values() if v]))

    return {
        "document_type": doc_type,
        "confidence": confidence,
        "structured_data": structured_data,
    }


def extract_with_compose(
    client: Any,
    file_bytes: bytes,
    compose_model_id: str,
) -> dict:
    """Call Azure Document Intelligence and return the raw ADI response dict."""
    logger.info("Starting unified compose model extraction...")
    logger.info("File size: %s bytes", len(file_bytes))
    logger.info("Using compose model: %s", compose_model_id)

    base64_source = base64.b64encode(file_bytes).decode("utf-8")
    poller = client.begin_analyze_document(
        model_id=compose_model_id,
        analyze_request={"base64Source": base64_source},
    )
    result = poller.result(timeout=300)
    return result.as_dict() if hasattr(result, "as_dict") else {}


def extract_with_compose_from_url(
    client: Any,
    document_url: str,
    compose_model_id: str,
) -> dict:
    """Call Azure Document Intelligence via URL source and return the raw ADI response dict."""
    logger.info("Starting unified compose model extraction from URL source...")
    logger.info("Using compose model: %s", compose_model_id)

    poller = client.begin_analyze_document(
        model_id=compose_model_id,
        analyze_request={"urlSource": document_url},
    )
    result = poller.result(timeout=300)
    return result.as_dict() if hasattr(result, "as_dict") else {}


def _extract_structured_data_by_schema(doc_type: str, raw_adi: dict) -> Dict[str, Any]:
    schema = _load_schema_for_doc_type(doc_type)
    if not schema:
        logger.warning("Unknown or unsupported document type for schema extraction: %s", doc_type)
        return {}

    structured_data: Dict[str, Any] = {}
    for field_def in schema.get("fields", []):
        system_key = field_def.get("systemKey")
        if not system_key:
            continue

        if field_def.get("array"):
            items, _issues = _extract_array_items(raw_adi, field_def)
            structured_data[system_key] = items
        else:
            structured_data[system_key] = _extract_scalar_field(raw_adi, field_def)
    return structured_data


def _load_schema_for_doc_type(doc_type: str) -> Optional[Dict[str, Any]]:
    if doc_type in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[doc_type]

    schema_path = SCHEMA_DIR / f"{doc_type}.jmespath.json"
    if not schema_path.exists():
        return None

    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    _SCHEMA_CACHE[doc_type] = schema
    return schema


def _extract_scalar_field(payload: Dict[str, Any], field_def: Dict[str, Any]) -> Dict[str, Any]:
    path = field_def.get("path")
    if not path:
        return {"value": None, "confidence": None}
    node = jmespath.search(str(path), payload)
    value, confidence, _actual_type = _extract_value_and_confidence(node)
    return {
        "value": value,
        "confidence": confidence,
    }


def _extract_array_items(payload: Dict[str, Any], array_def: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    attempted_paths = [array_def.get("path")] + list(array_def.get("fallbackPaths", []))
    resolved_path, node, used_fallback = _resolve_first_path(payload, attempted_paths)
    issues: List[Dict[str, Any]] = []

    if node is None:
        issues.append(
            _build_issue(
                severity="error" if array_def.get("required") else "warning",
                code="required_field_missing" if array_def.get("required") else "path_unresolved",
                system_key=array_def.get("systemKey", "unknown"),
                message=f"Array field '{array_def.get('systemKey')}' could not be resolved from ADI payload.",
                attempted_paths=attempted_paths,
                resolved_path=None,
                expected_type="array",
                actual_type=None,
                required=bool(array_def.get("required")),
                raw_preview=None,
            )
        )
        return [], issues

    if used_fallback:
        issues.append(
            _build_issue(
                severity="warning",
                code="fallback_path_used",
                system_key=array_def.get("systemKey", "unknown"),
                message=f"Array field '{array_def.get('systemKey')}' resolved using a fallback path.",
                attempted_paths=attempted_paths,
                resolved_path=resolved_path,
                expected_type="array",
                actual_type=_infer_actual_type(node, None),
                required=bool(array_def.get("required")),
                raw_preview=None,
            )
        )

    item_array = _extract_array_value(node)
    if not item_array:
        if array_def.get("required"):
            issues.append(
                _build_issue(
                    severity="error",
                    code="empty_array",
                    system_key=array_def.get("systemKey", "unknown"),
                    message=f"Array field '{array_def.get('systemKey')}' resolved but contained no items.",
                    attempted_paths=attempted_paths,
                    resolved_path=resolved_path,
                    expected_type="array",
                    actual_type="array",
                    required=True,
                    raw_preview=None,
                )
            )
        return [], issues

    items: List[Dict[str, Any]] = []
    for index, item in enumerate(item_array):
        item_fields = _extract_object_value(item)
        extracted_item: Dict[str, Any] = {}
        for item_field_def in array_def.get("itemSchema", []):
            system_key = item_field_def.get("systemKey")
            if not system_key:
                continue

            item_attempted_paths = [item_field_def.get("path")] + list(item_field_def.get("fallbackPaths", []))
            item_resolved_path, item_node, item_used_fallback = _resolve_first_path(item_fields, item_attempted_paths)
            combined_resolved_path = None
            if item_resolved_path:
                combined_resolved_path = f"{resolved_path}[{index}].{item_resolved_path}"

            value, confidence, actual_type = _extract_value_and_confidence(item_node)
            extracted_item[system_key] = {
                "value": value,
                "confidence": confidence,
                "sourcePathResolved": combined_resolved_path,
            }

            if item_node is None:
                issues.append(
                    _build_issue(
                        severity="error" if item_field_def.get("required") else "warning",
                        code="required_field_missing" if item_field_def.get("required") else "path_unresolved",
                        system_key=f"{array_def.get('systemKey')}[{index}].{system_key}",
                        message=f"Array item field '{system_key}' could not be resolved from ADI payload.",
                        attempted_paths=item_attempted_paths,
                        resolved_path=None,
                        expected_type=item_field_def.get("expectedType"),
                        actual_type=None,
                        required=bool(item_field_def.get("required")),
                        raw_preview=None,
                    )
                )
                continue

            if item_used_fallback:
                issues.append(
                    _build_issue(
                        severity="warning",
                        code="fallback_path_used",
                        system_key=f"{array_def.get('systemKey')}[{index}].{system_key}",
                        message=f"Array item field '{system_key}' resolved using a fallback path.",
                        attempted_paths=item_attempted_paths,
                        resolved_path=combined_resolved_path,
                        expected_type=item_field_def.get("expectedType"),
                        actual_type=actual_type,
                        required=bool(item_field_def.get("required")),
                        raw_preview=_preview_value(value),
                    )
                )

            if not _matches_expected_type(item_field_def.get("expectedType"), actual_type, value):
                issues.append(
                    _build_issue(
                        severity="error",
                        code="type_mismatch",
                        system_key=f"{array_def.get('systemKey')}[{index}].{system_key}",
                        message=f"Array item field '{system_key}' value type did not match expected type.",
                        attempted_paths=item_attempted_paths,
                        resolved_path=combined_resolved_path,
                        expected_type=item_field_def.get("expectedType"),
                        actual_type=actual_type,
                        required=bool(item_field_def.get("required")),
                        raw_preview=_preview_value(value),
                    )
                )

        items.append(extracted_item)

    return items, issues


def _resolve_first_path(payload: Dict[str, Any], paths: List[Optional[str]]) -> Tuple[Optional[str], Any, bool]:
    valid_paths = [path for path in paths if path]
    for index, path in enumerate(valid_paths):
        result = jmespath.search(path, payload)
        if result is not None:
            return path, result, index > 0
    return None, None, False


def _extract_value_and_confidence(node: Any) -> Tuple[Any, Optional[float], Optional[str]]:
    if node is None:
        return None, None, None

    if isinstance(node, dict):
        confidence = _to_float(node.get("confidence") or node.get("confidence_score"), None)

        value_keys = (
            "valueString",
            "value_string",
            "valueNumber",
            "value_number",
            "valueDate",
            "value_date",
            "valueTime",
            "value_time",
            "valueInteger",
            "value_integer",
            "valueBoolean",
            "value_boolean",
            "valuePhoneNumber",
            "value_phone_number",
            "valueSelectionMark",
            "value_selection_mark",
        )
        for value_key in value_keys:
            if value_key in node and node.get(value_key) is not None:
                return node.get(value_key), confidence, _infer_actual_type(node, node.get(value_key))

        currency = node.get("valueCurrency") or node.get("value_currency")
        if isinstance(currency, dict) and currency.get("amount") is not None:
            return currency.get("amount"), confidence, _infer_actual_type(node, currency.get("amount"))

        if node.get("value") is not None:
            return node.get("value"), confidence, _infer_actual_type(node, node.get("value"))

        if node.get("content") is not None:
            return node.get("content"), confidence, _infer_actual_type(node, node.get("content"))

        if node.get("valueObject") is not None or node.get("value_object") is not None:
            obj_value = _extract_object_value(node)
            return obj_value, confidence, "object"

        if node.get("valueArray") is not None or node.get("value_array") is not None:
            array_value = _extract_array_value(node)
            return array_value, confidence, "array"

        return None, confidence, _infer_actual_type(node, None)

    return node, None, _infer_actual_type(None, node)


def _extract_array_value(node: Any) -> List[Any]:
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        return node.get("valueArray") or node.get("value_array") or []
    return []


def _extract_object_value(node: Any) -> Dict[str, Any]:
    if isinstance(node, dict):
        return node.get("valueObject") or node.get("value_object") or node
    return {}


def _build_diagnostics(*, schema_version: int, document_type: str, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": schema_version,
        "document_type": document_type,
        "status": "has_issues" if issues else "ok",
        "required_missing_count": sum(1 for issue in issues if issue.get("code") == "required_field_missing"),
        "type_mismatch_count": sum(1 for issue in issues if issue.get("code") == "type_mismatch"),
        "path_unresolved_count": sum(1 for issue in issues if issue.get("code") == "path_unresolved"),
        "warning_count": sum(1 for issue in issues if issue.get("severity") == "warning"),
        "issues": issues,
    }


def _empty_projection(document_type: str = "unknown", confidence: float = 0.0) -> Dict[str, Any]:
    return {
        "document_type": document_type,
        "confidence": confidence,
        "structured_data": {},
        "diagnostics": _build_diagnostics(
            schema_version=1,
            document_type=document_type,
            issues=[
                _build_issue(
                    severity="error",
                    code="path_unresolved",
                    system_key="documents[0]",
                    message="No documents found in ADI response.",
                    attempted_paths=["documents[0]"],
                    resolved_path=None,
                    expected_type="object",
                    actual_type=None,
                    required=True,
                    raw_preview=None,
                )
            ],
        ),
        
    }


def _preview_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    preview = str(value)
    return preview[:117] + "..." if len(preview) > 120 else preview


def _infer_actual_type(node: Optional[Dict[str, Any]], value: Any) -> Optional[str]:
    if isinstance(node, dict):
        node_type = node.get("type") or node.get("fieldType") or node.get("field_type")
        if isinstance(node_type, str):
            return node_type.lower()

    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _matches_expected_type(expected_type: Optional[str], actual_type: Optional[str], value: Any) -> bool:
    if not expected_type or value is None:
        return True

    normalized_expected = expected_type.lower()
    normalized_actual = (actual_type or "").lower()
    compatible_types = {
        "number": {"number", "currency", "integer"},
        "date": {"date", "string"},
        "string": {"string", "phonenumber", "selectionmark"},
        "array": {"array"},
        "object": {"object"},
        "boolean": {"boolean"},
    }
    if normalized_expected == "date" and isinstance(value, str):
        return True
    return normalized_actual in compatible_types.get(normalized_expected, {normalized_expected})


def _build_issue(
    *,
    severity: str,
    code: str,
    system_key: str,
    message: str,
    attempted_paths: List[Optional[str]],
    resolved_path: Optional[str],
    expected_type: Optional[str],
    actual_type: Optional[str],
    required: bool,
    raw_preview: Optional[str],
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "systemKey": system_key,
        "message": message,
        "attemptedPaths": [path for path in attempted_paths if path],
        "resolvedPath": resolved_path,
        "expectedType": expected_type,
        "actualType": actual_type,
        "required": required,
        "rawPreview": raw_preview,
    }


def _to_float(value: Any, default: Optional[float]) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
