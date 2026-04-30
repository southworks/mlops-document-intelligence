"""Shared audit logging helper.

Usage::

    from shared.logging_helpers import audit_log

    audit_log(logger, "extractor_submitted", job_id=job.id, model_id=model_id)

Future: replace with OpenTelemetry structured log emission so traces, metrics,
and logs share a single pipeline with correlation IDs.
"""

from __future__ import annotations

import logging


def audit_log(
    logger: logging.Logger,
    event: str,
    /,
    **kwargs,
) -> None:
    """Emit *event* with *kwargs* through the caller's logger at INFO level.

    :param logger:  Caller's ``logging.getLogger(__name__)`` instance.
    :param event:   Short snake_case event name, e.g. ``"extractor_submitted"``.
    :param kwargs:  Arbitrary key/value context pairs.
    """
    kv_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info("%s %s", event, kv_str)
