"""Domain contracts for training dataset lifecycle and membership rules."""

from dataclasses import dataclass
from typing import Literal

DEFAULT_MIN_ITEMS_PER_CLASS = 5

TrainingDatasetStatus = Literal["draft", "staged", "ready_for_retrain"]


@dataclass(frozen=True)
class TrainingDatasetMembershipItem:
    candidate_id: str
    compose_model_id: str


@dataclass(frozen=True)
class TrainingDatasetTransitionRequest:
    min_items_per_class: int = DEFAULT_MIN_ITEMS_PER_CLASS


def is_valid_transition(
    *,
    current_status: TrainingDatasetStatus,
    target_status: TrainingDatasetStatus,
) -> bool:
    if current_status == target_status:
        return True
    return current_status == "draft" and target_status == "ready_for_retrain"
