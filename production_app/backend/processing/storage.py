"""
Storage Module
Shared helpers for backend storage-related normalization logic.
"""

from typing import Optional

ALLOWED_CANDIDATE_TRIGGER_FOLDERS = {
    "unknown_classification",
    "low_confidence",
    "low_field_confidence",
}


def resolve_candidate_destination_folder(trigger_reason: Optional[str]) -> Optional[str]:
    """Return explicit folder override for candidate-triggered documents.

    Returns None when the trigger does not map to a candidate-specific folder.
    """
    if not trigger_reason:
        return None
    return trigger_reason if trigger_reason in ALLOWED_CANDIDATE_TRIGGER_FOLDERS else None

