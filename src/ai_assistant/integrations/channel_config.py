"""Slack channel configuration for multi-channel advisor distribution.

Maps each advisor to a Slack channel ID for targeted distribution. Loads channel
mappings from environment variables with a fallback to the main channel.

Channel environment variables follow the pattern: SLACK_CHANNEL_<ADVISOR_KEY_UPPERCASE>
Example: SLACK_CHANNEL_WEATHER, SLACK_CHANNEL_JOB_SCOUT, etc.

If a specific channel is not configured, the advisor's report falls back to
SLACK_MAIN_CHANNEL if set, otherwise the legacy SLACK_CHANNEL is used.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MAIN_CHANNEL_ENV = "SLACK_MAIN_CHANNEL"
FALLBACK_CHANNEL_ENV = "SLACK_CHANNEL"  # Legacy fallback


def _advisor_channel_env(advisor_key: str) -> str:
    """Build the env var name for an advisor's channel.

    Example: "weather" -> "SLACK_CHANNEL_WEATHER"
    Example: "job_scout" -> "SLACK_CHANNEL_JOB_SCOUT"
    """
    return f"SLACK_CHANNEL_{advisor_key.upper()}"


class ChannelConfig:
    """Manages advisor-to-channel mappings loaded from environment.

    Attributes:
        main_channel: The default/main channel for briefing summaries.
        advisor_channels: Explicit channel for each advisor (if configured).
    """

    def __init__(self):
        """Initialize channel mappings from environment variables."""
        self.main_channel = (os.getenv(MAIN_CHANNEL_ENV) or "").strip()
        self.advisor_channels: Dict[str, str] = {}

    def get_channel(
        self, advisor_key: str, advisor_title: str = ""
    ) -> Optional[str]:
        """Get the channel ID for an advisor.

        Falls back to main_channel if no specific channel is configured, then to
        the legacy SLACK_CHANNEL. Never raises, never returns empty string.

        Args:
            advisor_key: The stable advisor identifier (e.g., "weather").
            advisor_title: The Turkish advisor title (used for logging only).

        Returns:
            The channel ID to post to, or None if no channel is configured.
        """
        # Check if already cached
        if advisor_key in self.advisor_channels:
            return self.advisor_channels[advisor_key]

        # Try specific advisor channel
        env_var = _advisor_channel_env(advisor_key)
        channel = (os.getenv(env_var) or "").strip()

        if channel:
            self.advisor_channels[advisor_key] = channel
            logger.debug(
                f"Channel for {advisor_title or advisor_key}: {channel} (from {env_var})"
            )
            return channel

        # Fallback to main channel
        if self.main_channel:
            self.advisor_channels[advisor_key] = self.main_channel
            logger.debug(
                f"Channel for {advisor_title or advisor_key}: {self.main_channel} (main channel)"
            )
            return self.main_channel

        # Ultimate fallback to legacy SLACK_CHANNEL
        fallback = (os.getenv(FALLBACK_CHANNEL_ENV) or "").strip()
        if fallback:
            self.advisor_channels[advisor_key] = fallback
            logger.debug(
                f"Channel for {advisor_title or advisor_key}: {fallback} (legacy SLACK_CHANNEL)"
            )
            return fallback

        # No channel configured at all
        self.advisor_channels[advisor_key] = None
        return None

    def has_any_channel(self) -> bool:
        """Whether any Slack channel is configured (main, advisor-specific, or legacy)."""
        if self.main_channel:
            return True
        if (os.getenv(FALLBACK_CHANNEL_ENV) or "").strip():
            return True
        # Check if any advisor-specific channel is set
        for key in self._get_known_advisor_keys():
            env_var = _advisor_channel_env(key)
            if (os.getenv(env_var) or "").strip():
                return True
        return False

    @staticmethod
    def _get_known_advisor_keys() -> list:
        """List of all known advisor keys for fallback checking.

        This is a static list to avoid circular imports from the advisors module.
        """
        return [
            "weather",
            "leadership_coach",
            "kids_development",
            "career_hr",
            "job_scout",
            "sector_intel",
            "ai_news",
            "free_certs",
            "banking_cc_projects",
            "ai_mastery",
            "cx_research",
            "daily_ops_briefing",
            "language_coach",
            "anka_bridge",
            "innovation_lab",
            "accountability_coach",
        ]


# Global singleton instance
_config: Optional[ChannelConfig] = None


def get_channel_config() -> ChannelConfig:
    """Get or create the global channel configuration instance."""
    global _config
    if _config is None:
        _config = ChannelConfig()
    return _config


def get_channel_for_advisor(advisor_key: str, advisor_title: str = "") -> Optional[str]:
    """Convenience function to get a channel for an advisor.

    Args:
        advisor_key: The stable advisor identifier (e.g., "weather").
        advisor_title: The Turkish advisor title (used for logging only).

    Returns:
        The channel ID to post to, or None if no channel is configured.
    """
    return get_channel_config().get_channel(advisor_key, advisor_title)
