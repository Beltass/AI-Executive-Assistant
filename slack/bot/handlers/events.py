"""Slack event handlers."""

import logging

logger = logging.getLogger(__name__)


def handle_mention(body, say):
    """Handle app mention event."""
    event = body.get("event", {})
    text = event.get("text", "")
    user_id = event.get("user")

    logger.info(f"Mention from {user_id}: {text}")

    # Process commands in text
    if "generate" in text.lower():
        say("I'll help you generate content. Let me process that...")
    elif "speaking" in text.lower():
        say("Let me fetch your speaking opportunities...")
    else:
        say("How can I help you with content creation?")


def handle_message(body, say):
    """Handle direct message event."""
    event = body.get("event", {})
    text = event.get("text", "")
    channel = event.get("channel")

    logger.info(f"Message in {channel}: {text}")

    # TODO: Implement message handling logic
    pass
