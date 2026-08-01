# Integration Metrics Tracking

## Overview

The integration metrics system tracks health and performance of external integrations (Slack, Asana, Google Drive) throughout the daily briefing execution. Metrics are accumulated throughout a calendar day (UTC) and automatically reset at midnight.

## Features

- **Slack Tracking**: Messages sent to channels, failed sends with timestamps
- **Asana Tracking**: Projects/tasks created, tasks completed, failed operations
- **Google Drive Tracking**: Documents uploaded, archive count, failed uploads
- **Health Checks**: Integration availability status
- **Persistent Storage**: Metrics saved to `frontend/integration_metrics.json`
- **Daily Rollover**: Automatic reset at UTC midnight
- **Error Isolation**: Failures in tracking never break the main workflow

## Architecture

### Core Components

#### `IntegrationMetrics` Class (`status_report.py`)

The main class that manages all metrics tracking:

```python
from ai_assistant.status_report import IntegrationMetrics

metrics = IntegrationMetrics()

# Record operations
metrics.record_slack_send(channel="general", success=True)
metrics.record_asana_operation(operation_type="task_created", success=True)
metrics.record_drive_upload(filename="report.pdf", success=True)

# Record health checks
metrics.record_health_check(integration="slack", healthy=True)

# Get summary
summary = metrics.get_integration_summary()

# Persist to disk
metrics.persist()
```

#### Helper Functions (`integration_tracker.py`)

Convenience functions for common operations:

```python
from ai_assistant.integration_tracker import (
    record_slack_message,
    record_asana_task,
    record_drive_document,
    check_integration_health,
    persist_metrics,
)

# Simple API
record_slack_message("general", success=True)
record_asana_task("task_created", success=True)
record_drive_document("report.pdf", success=True)
check_integration_health("slack", healthy=True)
persist_metrics()
```

### Data Structure

Metrics are stored in `frontend/integration_metrics.json`:

```json
{
  "date": "2026-07-31",
  "integrations": {
    "slack": {
      "enabled": true,
      "channels_configured": 16,
      "messages_sent_today": 12,
      "failed_sends": [
        {
          "channel": "general",
          "timestamp": "2026-07-31T10:30:00Z"
        }
      ],
      "last_post_time": "2026-07-31T10:30:00Z",
      "health_status": "healthy",
      "last_health_check": "2026-07-31T10:30:00Z"
    },
    "asana": {
      "enabled": true,
      "projects_created": 3,
      "tasks_created": 45,
      "tasks_completed": 12,
      "failed_operations": [
        {
          "operation": "task_created",
          "timestamp": "2026-07-31T10:30:00Z"
        }
      ],
      "last_sync_time": "2026-07-31T10:30:00Z",
      "health_status": "healthy",
      "last_health_check": "2026-07-31T10:30:00Z"
    },
    "drive": {
      "enabled": true,
      "documents_uploaded": 234,
      "archive_count": 56,
      "failed_uploads": [
        {
          "filename": "backup.zip",
          "timestamp": "2026-07-31T10:30:00Z"
        }
      ],
      "last_sync_time": "2026-07-31T10:30:00Z",
      "health_status": "healthy",
      "last_health_check": "2026-07-31T10:30:00Z"
    }
  }
}
```

## Integration Points

### Slack Notifier

In `notifiers/slack_notifier.py`, record message sends:

```python
from ai_assistant.integration_tracker import record_slack_message

def send_message(text: str, blocks=None) -> CheckResult:
    # ... existing code ...
    result = _post_webhook(url, text, blocks)
    
    # Record the attempt
    record_slack_message(
        channel=os.getenv("SLACK_CHANNEL", "general"),
        success=result.ok
    )
    
    return result
```

### Asana Integration

In Asana advisor/integration code:

```python
from ai_assistant.integration_tracker import record_asana_task

def create_task(task_name: str) -> bool:
    try:
        # ... create task ...
        record_asana_task("task_created", success=True)
        return True
    except Exception:
        record_asana_task("task_created", success=False)
        return False

def complete_task(task_id: str) -> bool:
    try:
        # ... complete task ...
        record_asana_task("task_completed", success=True)
        return True
    except Exception:
        record_asana_task("task_completed", success=False)
        return False
```

### Google Drive Integration

In Drive upload code:

```python
from ai_assistant.integration_tracker import record_drive_document

def upload_document(filepath: str, folder_id: str) -> bool:
    try:
        filename = os.path.basename(filepath)
        # ... upload to Drive ...
        record_drive_document(filename, success=True)
        return True
    except Exception:
        record_drive_document(os.path.basename(filepath), success=False)
        return False
```

### Health Checks

After integration operations, record health status:

```python
from ai_assistant.integration_tracker import check_integration_health

def check_slack_health() -> bool:
    try:
        from integrations.slack import check_connection
        result = check_connection()
        check_integration_health("slack", result.ok)
        return result.ok
    except Exception:
        check_integration_health("slack", False)
        return False
```

### Status Report

The metrics are automatically included in `status.json` via `_integrations_snapshot()`:

```python
def build_status(supervision, slack_result=None, ...):
    # ... existing code ...
    return {
        # ... other fields ...
        "integrations": _integrations_snapshot(),  # Included here
        # ... other fields ...
    }
```

## Configuration

### Environment Variables

```bash
# Where to store integration metrics (optional)
INTEGRATION_METRICS_FILE=frontend/integration_metrics.json

# Existing Slack channel env vars are counted
SLACK_CHANNEL_MAIN=general
SLACK_CHANNEL_CAREER=career
# etc.
```

## Daily Workflow

1. **Initialization**: `IntegrationMetrics()` loads today's metrics or starts fresh
2. **Recording**: Throughout execution, integration operations are recorded
3. **Aggregation**: Counts accumulate throughout the day
4. **Persistence**: After each operation batch, `persist_metrics()` saves to disk
5. **Reset**: At UTC midnight, new day automatically starts fresh

## Best Practices

### Recording Operations

1. **Record immediately after operation**:
   ```python
   # Good
   result = api.create_task()
   record_asana_task("task_created", success=result.ok)
   ```

2. **Never let tracking break main flow**:
   ```python
   # Tracking is wrapped in try/except
   try:
       record_slack_message(channel, success=True)
   except Exception as exc:
       logger.warning("Could not record metric: %s", exc)
   ```

3. **Include relevant context**:
   ```python
   # Good - identifies which channel failed
   record_slack_message("general", success=False)
   
   # Instead of - no context
   record_slack_message("?", success=False)
   ```

### Persistence

1. **Call `persist_metrics()` after batch operations**:
   ```python
   # In daily_digest.py or after sending to Slack
   from ai_assistant.integration_tracker import persist_metrics
   
   # ... send messages to multiple channels ...
   persist_metrics()  # Save accumulated metrics
   ```

2. **Errors are logged but never raised**:
   ```python
   success = persist_metrics()  # Returns bool, never raises
   if not success:
       logger.warning("Could not persist metrics")
   ```

## Monitoring

### View Metrics

Raw metrics file:
```bash
cat frontend/integration_metrics.json | jq '.integrations'
```

### Dashboard Display

The dashboard can display:
- Daily message sends per channel
- Success rate of Asana operations
- Archive uploads tracking
- Health status indicators
- Failure trends over time

### Alerts (Future)

The framework supports adding alerts:
```python
if len(slack_data["failed_sends"]) > 5:
    logger.warning("High Slack failure rate today")

if asana_data["health_status"] == "unhealthy":
    logger.warning("Asana integration is unhealthy")
```

## Error Handling

The system is designed to never break the briefing:

```python
try:
    metrics = IntegrationMetrics()
    metrics.record_slack_send("general", success=True)
    metrics.persist()
except Exception as exc:
    # Log but continue - briefing must go out
    logger.warning("Metrics tracking failed: %s", exc)
    # Briefing continues normally
```

## Testing

Run the example to verify setup:

```bash
python examples/integration_metrics_example.py
```

This demonstrates:
- Recording Slack sends
- Tracking Asana operations
- Monitoring Drive uploads
- Recording health checks
- Persisting metrics
- Viewing the summary

## File Locations

- **Metrics tracking**: `src/ai_assistant/status_report.py` (IntegrationMetrics class)
- **Helper functions**: `src/ai_assistant/integration_tracker.py`
- **Persistent storage**: `frontend/integration_metrics.json`
- **Status integration**: `src/ai_assistant/status_report.py` (_integrations_snapshot function)
- **Example usage**: `examples/integration_metrics_example.py`

## Future Enhancements

1. **Per-integration rate limiting**: Track rate limit warnings
2. **Advisor-level tracking**: Map operations to specific advisors
3. **Cost tracking**: Associate operations with API costs
4. **Retry analysis**: Track retry patterns and suggest optimizations
5. **Dashboard alerts**: Auto-alert on integration failures
6. **SLA tracking**: Monitor integration uptime SLA
