"""Slack integration API routes."""

import logging
import json
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.slack_service import SlackService
from app.services.content_service import ContentService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/events")
async def handle_slack_event(request: Request, db: Session = Depends(get_db)):
    """Handle Slack event callbacks."""
    body = await request.body()
    slack_service = SlackService()

    # Verify request signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not slack_service.verify_request(timestamp, signature, body.decode()):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse request
    data = json.loads(body)

    # Handle URL verification
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}

    # Handle events
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        event_type = event.get("type")

        if event_type == "app_mention":
            await _handle_mention(event, db)

        elif event_type == "message":
            await _handle_message(event, db)

    return {"ok": True}


@router.post("/actions")
async def handle_slack_action(request: Request, db: Session = Depends(get_db)):
    """Handle Slack interactive actions."""
    body = await request.body()
    slack_service = SlackService()

    # Verify request
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not slack_service.verify_request(timestamp, signature, body.decode()):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    data = json.loads(body)
    payload = json.loads(data.get("payload", "{}"))

    action_type = payload.get("type")

    if action_type == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            action_id = action.get("action_id")

            if action_id == "content_approve":
                await _handle_approve(action, db)

            elif action_id == "content_regenerate":
                await _handle_regenerate(action, db)

            elif action_id == "content_reject":
                await _handle_reject(action, db)

    return {"ok": True}


@router.post("/commands")
async def handle_slack_command(request: Request, db: Session = Depends(get_db)):
    """Handle Slack slash commands."""
    body = await request.body()
    slack_service = SlackService()

    # Verify request
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not slack_service.verify_request(timestamp, signature, body.decode()):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse form data
    from urllib.parse import parse_qs
    data = parse_qs(body.decode())

    command = data.get("command", [""])[0]
    text = data.get("text", [""])[0]
    user_id = data.get("user_id", [""])[0]
    channel_id = data.get("channel_id", [""])[0]

    if command == "/content-generate":
        await _handle_generate_command(text, user_id, channel_id, db)

    elif command == "/speaking-opportunities":
        await _handle_speaking_command(user_id, channel_id, db)

    return {"ok": True}


async def _handle_mention(event: dict, db: Session):
    """Handle app mention event."""
    text = event.get("text", "")
    channel = event.get("channel")
    user_id = event.get("user")

    logger.info(f"Received mention from {user_id}: {text}")

    # Process command in text
    if "generate content" in text.lower():
        await _process_content_generation_from_slack(channel, db)


async def _handle_message(event: dict, db: Session):
    """Handle message event."""
    # TODO: Implement message handling logic
    pass


async def _handle_approve(action: dict, db: Session):
    """Handle content approval action."""
    try:
        value = action.get("value", "").split("_")
        if len(value) == 2:
            content_id = int(value[1])

            service = ContentService(db)
            content = await service.approve_content(user_id=1, content_id=content_id)

            if content:
                logger.info(f"Content {content_id} approved via Slack")

    except Exception as e:
        logger.error(f"Error approving content: {e}")


async def _handle_regenerate(action: dict, db: Session):
    """Handle content regeneration action."""
    try:
        value = action.get("value", "").split("_")
        if len(value) == 2:
            content_id = int(value[1])
            logger.info(f"Regenerating content {content_id}")

            # TODO: Trigger regeneration logic

    except Exception as e:
        logger.error(f"Error regenerating content: {e}")


async def _handle_reject(action: dict, db: Session):
    """Handle content rejection action."""
    try:
        value = action.get("value", "").split("_")
        if len(value) == 2:
            content_id = int(value[1])

            service = ContentService(db)
            await service.delete_content(user_id=1, content_id=content_id)

            logger.info(f"Content {content_id} rejected via Slack")

    except Exception as e:
        logger.error(f"Error rejecting content: {e}")


async def _handle_generate_command(topic: str, user_id: str, channel_id: str, db: Session):
    """Handle /content-generate command."""
    if not topic:
        # TODO: Send modal for content generation
        pass
    else:
        logger.info(f"Generate content for topic: {topic}")
        # TODO: Trigger content generation


async def _handle_speaking_command(user_id: str, channel_id: str, db: Session):
    """Handle /speaking-opportunities command."""
    logger.info(f"Fetching speaking opportunities for user: {user_id}")
    # TODO: Fetch and display speaking opportunities


async def _process_content_generation_from_slack(channel: str, db: Session):
    """Process content generation triggered from Slack."""
    service = SlackService()
    await service.send_message(
        channel, "Processing your content generation request..."
    )
