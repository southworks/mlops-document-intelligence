"""Lightweight in-process telemetry for ModelAdmin service runtime."""

# pylint: disable=R0801

from threading import Lock

_COUNTERS = {
    "boundary_intake.accepted": 0,
    "boundary_intake.duplicate": 0,
    "boundary_intake.failed": 0,
}
_LOCK = Lock()


def increment_counter(name: str) -> None:
    if name not in _COUNTERS:
        return
    with _LOCK:
        _COUNTERS[name] += 1


def snapshot_counters() -> dict:
    with _LOCK:
        return dict(_COUNTERS)
