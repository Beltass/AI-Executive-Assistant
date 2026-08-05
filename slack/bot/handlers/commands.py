"""Slack command handlers."""

import logging

logger = logging.getLogger(__name__)


def handle_generate_command(body, respond):
    """Handle /content-generate command."""
    text = body.get("text", "")
    user_id = body.get("user_id")

    logger.info(f"Generate command from {user_id}: {text}")

    if not text:
        respond(
            {
                "text": "Please provide a topic for content generation",
                "response_type": "ephemeral",
            }
        )
        return

    # TODO: Call backend API to generate content
    respond(
        {
            "text": f"Generating content for topic: {text}",
            "response_type": "in_channel",
        }
    )


def handle_speaking_command(body, respond):
    """Handle /speaking-opportunities command."""
    user_id = body.get("user_id")

    logger.info(f"Speaking opportunities command from {user_id}")

    # TODO: Fetch speaking opportunities from backend API
    respond(
        {
            "text": "Fetching your speaking opportunities...",
            "response_type": "ephemeral",
        }
    )


def handle_analytics_command(body, respond):
    """Handle /analytics command."""
    text = body.get("text", "")
    user_id = body.get("user_id")

    logger.info(f"Analytics command from {user_id}: {text}")

    # TODO: Fetch analytics from backend API
    period = text or "30"
    respond(
        {
            "text": f"Fetching analytics for last {period} days...",
            "response_type": "ephemeral",
        }
    )
