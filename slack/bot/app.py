"""Slack bot application setup."""

import os
import logging
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request

from app.config import settings
from slack.bot.handlers import events, actions, shortcuts, commands

logger = logging.getLogger(__name__)

# Initialize Slack app
slack_app = App(
    token=settings.SLACK_BOT_TOKEN,
    signing_secret=settings.SLACK_SIGNING_SECRET,
)

# Initialize Flask app for webhook handling
flask_app = Flask(__name__)
handler = SlackRequestHandler(slack_app)


# Register event handlers
@slack_app.event("app_mention")
def handle_app_mention(body, say):
    """Handle app mention event."""
    logger.info("App mentioned")
    events.handle_mention(body, say)


@slack_app.event("message")
def handle_message(body, say):
    """Handle message event."""
    logger.info("Message received")
    events.handle_message(body, say)


# Register action handlers
@slack_app.action("content_approve")
def handle_content_approve(ack, body, say):
    """Handle content approval action."""
    ack()
    actions.approve_content(body, say)


@slack_app.action("content_regenerate")
def handle_content_regenerate(ack, body, say):
    """Handle content regeneration action."""
    ack()
    actions.regenerate_content(body, say)


@slack_app.action("content_reject")
def handle_content_reject(ack, body, say):
    """Handle content rejection action."""
    ack()
    actions.reject_content(body, say)


# Register shortcut handlers
@slack_app.shortcut("generate_content")
def handle_generate_shortcut(ack, body, respond):
    """Handle generate content shortcut."""
    ack()
    shortcuts.handle_generate_shortcut(body, respond)


# Register command handlers
@slack_app.command("/content-generate")
def handle_generate_command(ack, body, respond):
    """Handle /content-generate command."""
    ack()
    commands.handle_generate_command(body, respond)


@slack_app.command("/speaking-opportunities")
def handle_speaking_command(ack, body, respond):
    """Handle /speaking-opportunities command."""
    ack()
    commands.handle_speaking_command(body, respond)


@slack_app.command("/analytics")
def handle_analytics_command(ack, body, respond):
    """Handle /analytics command."""
    ack()
    commands.handle_analytics_command(body, respond)


# Flask route for Slack events
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    """Slack events webhook endpoint."""
    return handler.handle(request)


# Flask route for health check
@flask_app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return {"status": "ok"}, 200


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=3000, debug=True)
