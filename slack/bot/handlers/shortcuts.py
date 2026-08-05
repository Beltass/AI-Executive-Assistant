"""Slack shortcut handlers."""

import logging

logger = logging.getLogger(__name__)


def handle_generate_shortcut(body, respond):
    """Handle generate content shortcut."""
    logger.info("Generate content shortcut triggered")

    # TODO: Open modal for content generation
    respond("Opening content generation form...")
