"""Integration tracking utilities — record metrics from integration operations.

This module provides helpers to record integration events during the daily
briefing workflow. It is meant to be used by:

- notifiers/slack_notifier.py — record Slack message sends
- advisors that sync to Asana — record task/project operations
- reporters that save to Drive — record document uploads

Example usage::

    from .integration_tracker import get_metrics

    metrics = get_metrics()
    metrics.record_slack_send("general", success=True)
    metrics.record_asana_operation("task_created", success=True)
    metrics.record_drive_upload("report.pdf", success=True)
    metrics.persist()

The metrics are accumulated throughout a calendar day (UTC) and automatically
reset at midnight. Health checks can be recorded to track integration availability.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .status_report import IntegrationMetrics

logger = logging.getLogger(__name__)

# Global metrics instance — initialized on first use
_metrics_instance: Optional[IntegrationMetrics] = None


def get_metrics() -> IntegrationMetrics:
    """Get or initialize the global integration metrics tracker.

    Returns:
        IntegrationMetrics: The global metrics instance for this run.
    """
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = IntegrationMetrics()
    return _metrics_instance


def record_slack_message(
    channel: str, success: bool, timestamp: Optional[datetime] = None
) -> None:
    """Record a Slack message send.

    Args:
        channel: Slack channel name or ID where the message was sent.
        success: True if send succeeded, False if failed.
        timestamp: When the send occurred (defaults to now).
    """
    try:
        metrics = get_metrics()
        metrics.record_slack_send(channel, success, timestamp)
    except Exception as exc:
        logger.warning("Slack metriği kaydedilirken hata: %s", exc)


def record_asana_task(
    operation: str, success: bool, timestamp: Optional[datetime] = None
) -> None:
    """Record an Asana task or project operation.

    Args:
        operation: One of "project_created", "task_created", "task_completed".
        success: True if operation succeeded, False if failed.
        timestamp: When the operation occurred (defaults to now).
    """
    try:
        metrics = get_metrics()
        metrics.record_asana_operation(operation, success, timestamp)
    except Exception as exc:
        logger.warning("Asana metriği kaydedilirken hata: %s", exc)


def record_drive_document(
    filename: str, success: bool, timestamp: Optional[datetime] = None
) -> None:
    """Record a Google Drive document upload.

    Args:
        filename: Name of the uploaded file.
        success: True if upload succeeded, False if failed.
        timestamp: When the upload occurred (defaults to now).
    """
    try:
        metrics = get_metrics()
        metrics.record_drive_upload(filename, success, timestamp)
    except Exception as exc:
        logger.warning("Drive metriği kaydedilirken hata: %s", exc)


def check_integration_health(integration: str, healthy: bool) -> None:
    """Record an integration health check result.

    Args:
        integration: One of "slack", "asana", "drive".
        healthy: True if health check passed, False if it failed.
    """
    try:
        metrics = get_metrics()
        metrics.record_health_check(integration, healthy)
    except Exception as exc:
        logger.warning(
            "Entegrasyon sağlık kontrolü kaydedilirken hata (%s): %s",
            integration,
            exc,
        )


def persist_metrics() -> bool:
    """Persist collected metrics to disk.

    Returns:
        True if persistence succeeded, False if it failed.
    """
    try:
        metrics = get_metrics()
        return metrics.persist()
    except Exception as exc:
        logger.warning("Metrikleri kaydetme başarısız: %s", exc)
        return False


__all__ = [
    "check_integration_health",
    "get_metrics",
    "persist_metrics",
    "record_asana_task",
    "record_drive_document",
    "record_slack_message",
]
