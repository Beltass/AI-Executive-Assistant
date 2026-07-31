#!/usr/bin/env python
"""Example: Using IntegrationMetrics to track integration health and performance.

This example shows how to integrate the IntegrationMetrics tracking with the
daily briefing workflow. It demonstrates:

1. Recording Slack messages sent during delivery
2. Tracking Asana task/project operations
3. Monitoring Google Drive uploads
4. Recording health checks for each integration
5. Persisting metrics for the dashboard

Run this example to see how metrics are collected and persisted::

    python -m examples.integration_metrics_example
"""

from datetime import datetime, timezone
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai_assistant.integration_tracker import (
    check_integration_health,
    get_metrics,
    persist_metrics,
    record_asana_task,
    record_drive_document,
    record_slack_message,
)
from src.ai_assistant.status_report import IntegrationMetrics


def example_slack_tracking():
    """Example: Track Slack message deliveries."""
    print("\n--- Slack Message Tracking Example ---")

    # Simulate sending messages to different channels
    channels = ["general", "announcements", "team-updates"]

    for i, channel in enumerate(channels):
        success = i < 2  # First 2 succeed, last one fails
        record_slack_message(channel, success=success)
        status = "✓ sent" if success else "✗ failed"
        print(f"  Channel '{channel}': {status}")

    # Check the current state
    metrics = get_metrics()
    slack_data = metrics.data["integrations"]["slack"]
    print(
        f"  Total sent: {slack_data['messages_sent_today']}, "
        f"Failed: {len(slack_data['failed_sends'])}"
    )


def example_asana_tracking():
    """Example: Track Asana task and project operations."""
    print("\n--- Asana Operations Tracking Example ---")

    operations = [
        ("project_created", True),
        ("task_created", True),
        ("task_created", True),
        ("task_completed", True),
        ("task_created", False),  # Failed operation
    ]

    for operation, success in operations:
        record_asana_task(operation, success=success)
        status = "✓" if success else "✗"
        print(f"  {status} {operation}")

    metrics = get_metrics()
    asana_data = metrics.data["integrations"]["asana"]
    print(
        f"  Projects: {asana_data['projects_created']}, "
        f"Tasks: {asana_data['tasks_created']}, "
        f"Completed: {asana_data['tasks_completed']}, "
        f"Failed: {len(asana_data['failed_operations'])}"
    )


def example_drive_tracking():
    """Example: Track Google Drive uploads."""
    print("\n--- Google Drive Upload Tracking Example ---")

    uploads = [
        ("briefing_2026_07_31.pdf", True),
        ("daily_report.docx", True),
        ("archive_2026_07.zip", True),  # Counts as archive
        ("backup_data.xlsx", False),  # Failed upload
    ]

    for filename, success in uploads:
        record_drive_document(filename, success=success)
        status = "✓" if success else "✗"
        is_archive = "archive" if "archive" in filename else "document"
        print(f"  {status} {filename} ({is_archive})")

    metrics = get_metrics()
    drive_data = metrics.data["integrations"]["drive"]
    print(
        f"  Documents: {drive_data['documents_uploaded']}, "
        f"Archives: {drive_data['archive_count']}, "
        f"Failed: {len(drive_data['failed_uploads'])}"
    )


def example_health_checks():
    """Example: Record integration health checks."""
    print("\n--- Health Check Tracking Example ---")

    checks = [
        ("slack", True),
        ("asana", True),
        ("drive", False),  # Drive is unhealthy
    ]

    for integration, healthy in checks:
        check_integration_health(integration, healthy)
        status = "✓ healthy" if healthy else "✗ unhealthy"
        print(f"  {integration}: {status}")

    metrics = get_metrics()
    for integration in ["slack", "asana", "drive"]:
        health_status = metrics.data["integrations"][integration]["health_status"]
        print(f"  {integration} status: {health_status}")


def example_view_summary():
    """Example: View the complete metrics summary."""
    print("\n--- Integration Metrics Summary ---")

    metrics = get_metrics()
    summary = metrics.get_integration_summary()

    print(f"  Date: {summary['date']}")
    print("\n  Slack:")
    slack = summary["integrations"]["slack"]
    print(f"    - Messages sent: {slack['messages_sent_today']}")
    print(f"    - Failed sends: {len(slack['failed_sends'])}")
    print(f"    - Last post: {slack['last_post_time']}")

    print("\n  Asana:")
    asana = summary["integrations"]["asana"]
    print(f"    - Projects created: {asana['projects_created']}")
    print(f"    - Tasks created: {asana['tasks_created']}")
    print(f"    - Tasks completed: {asana['tasks_completed']}")
    print(f"    - Failed operations: {len(asana['failed_operations'])}")

    print("\n  Drive:")
    drive = summary["integrations"]["drive"]
    print(f"    - Documents uploaded: {drive['documents_uploaded']}")
    print(f"    - Archives stored: {drive['archive_count']}")
    print(f"    - Failed uploads: {len(drive['failed_uploads'])}")


def example_persist():
    """Example: Persist metrics to disk for the dashboard."""
    print("\n--- Persisting Metrics ---")

    success = persist_metrics()
    if success:
        print(f"  ✓ Metrics persisted to integration_metrics.json")
    else:
        print(f"  ✗ Failed to persist metrics")


def main():
    """Run all examples."""
    print("=" * 60)
    print("Integration Metrics Tracking Examples")
    print("=" * 60)

    # Run examples in order
    example_slack_tracking()
    example_asana_tracking()
    example_drive_tracking()
    example_health_checks()
    example_view_summary()
    example_persist()

    print("\n" + "=" * 60)
    print("Example completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
