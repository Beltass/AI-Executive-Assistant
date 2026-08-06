"""Pydantic schemas for Slack integration."""

from typing import Optional
from pydantic import BaseModel


class SlackEventRequest(BaseModel):
    """Slack event request schema."""

    token: str
    team_id: str
    api_app_id: str
    event: dict
    type: str
    event_id: str
    event_time: int
    challenge: Optional[str] = None


class SlackCommandRequest(BaseModel):
    """Slack slash command request schema."""

    token: str
    team_id: str
    team_domain: str
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    command: str
    text: str
    api_app_id: str
    response_url: str
    trigger_id: str


class ContentApprovalRequest(BaseModel):
    """Request to approve content via Slack."""

    content_id: int
    approved: bool
    feedback: Optional[str] = None
