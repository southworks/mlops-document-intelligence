from processing.storage import resolve_candidate_destination_folder


def test_resolve_unknown_classification_folder() -> None:
    assert resolve_candidate_destination_folder("unknown_classification") == "unknown_classification"


def test_resolve_low_confidence_folder() -> None:
    assert (
        resolve_candidate_destination_folder("low_confidence")
        == "low_confidence"
    )


def test_resolve_low_field_confidence_folder() -> None:
    assert (
        resolve_candidate_destination_folder("low_field_confidence")
        == "low_field_confidence"
    )


def test_resolve_unmapped_trigger_returns_none() -> None:
    assert resolve_candidate_destination_folder("non_candidate_reason") is None


def test_resolve_none_trigger_returns_none() -> None:
    assert resolve_candidate_destination_folder(None) is None
