"""Slack action handlers."""

import logging

logger = logging.getLogger(__name__)


def approve_content(body, say):
    """Handle content approval action."""
    action_value = body.get("actions", [{}])[0].get("value", "")
    logger.info(f"Approving content: {action_value}")

    # Extract content ID from action value
    # Example value format: "approve_123"
    parts = action_value.split("_")
    if len(parts) == 2:
        content_id = parts[1]
        # TODO: Call API to approve content
        say(f"Content {content_id} has been approved!")


def regenerate_content(body, say):
    """Handle content regeneration action."""
    action_value = body.get("actions", [{}])[0].get("value", "")
    logger.info(f"Regenerating content: {action_value}")

    # Extract content ID from action value
    parts = action_value.split("_")
    if len(parts) == 2:
        content_id = parts[1]
        # TODO: Call API to regenerate content
        say(f"Regenerating content {content_id}...")


def reject_content(body, say):
    """Handle content rejection action."""
    action_value = body.get("actions", [{}])[0].get("value", "")
    logger.info(f"Rejecting content: {action_value}")

    # Extract content ID from action value
    parts = action_value.split("_")
    if len(parts) == 2:
        content_id = parts[1]
        # TODO: Call API to delete/reject content
        say(f"Content {content_id} has been rejected.")
