"""Advisor Daily Scheduler — Schedules daily advisor updates to Slack.

This module handles:
- Scheduled daily advisor report generation
- Upload to Google Drive
- Slack notification with Drive links
- Error handling and retry logic
- Concurrent processing of multiple advisors

Schedule:
  Every day at 07:00 UTC (configurable via SLACK_ADVISOR_UPDATE_HOUR)
  Advisors to update configurable via SLACK_ADVISOR_INCLUDE env var
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time
from typing import List, Optional, Dict, Any, Callable, Awaitable

logger = logging.getLogger(__name__)

ADVISORS_TO_UPDATE = [
    "data_analyst",
    "linkedin_coach",
    "social_media_coach",
    "personal_assistant",
]

ADVISOR_REPORT_GENERATORS = {
    # Placeholders for actual advisor report generation
    # These should be injected via initialization
}


class AdvisorDailyScheduler:
    """Schedules and manages daily advisor updates to Slack."""

    def __init__(
        self,
        slack_bridge: Optional[Any] = None,
        drive_manager: Optional[Any] = None,
        update_hour: Optional[int] = None,
        advisors_to_update: Optional[List[str]] = None,
    ):
        """Initialize the daily scheduler.

        Args:
            slack_bridge: SlackAdvisorBridge instance
            drive_manager: GoogleDriveManager instance
            update_hour: Hour to send updates (0-23 UTC, default 7)
            advisors_to_update: List of advisor keys to update (default: all)
        """
        self.slack_bridge = slack_bridge
        self.drive_manager = drive_manager
        self.update_hour = update_hour or int(
            os.getenv("SLACK_ADVISOR_UPDATE_HOUR", "7")
        )
        self.advisors_to_update = advisors_to_update or self._get_configured_advisors()

        # Report generators to be injected
        self.report_generators: Dict[str, Callable[[], Awaitable[Dict[str, Any]]]] = {}

    @staticmethod
    def _get_configured_advisors() -> List[str]:
        """Get advisors to update from environment.

        Environment variable format: SLACK_ADVISOR_INCLUDE=advisor1,advisor2,...
        Defaults to all advisors.

        Returns:
            List of advisor keys
        """
        configured = os.getenv("SLACK_ADVISOR_INCLUDE", "")
        if configured:
            advisors = [a.strip() for a in configured.split(",") if a.strip()]
            if advisors:
                return advisors
        return ADVISORS_TO_UPDATE

    def register_report_generator(
        self,
        advisor_key: str,
        generator: Callable[[], Awaitable[Dict[str, Any]]],
    ) -> None:
        """Register a report generator for an advisor.

        Args:
            advisor_key: Advisor identifier
            generator: Async callable that returns dict with keys:
                - summary: str
                - drive_links: dict of {key: url}
                - timestamp: datetime
                - other_data: any advisor-specific data
        """
        self.report_generators[advisor_key] = generator
        logger.info(f"Registered report generator for {advisor_key}")

    async def schedule_advisor_updates(self) -> Dict[str, bool]:
        """Run daily advisor updates for all configured advisors.

        Returns:
            Dict of {advisor_key: success_bool} for each advisor
        """
        logger.info(
            f"Starting daily advisor updates for {len(self.advisors_to_update)} advisors"
        )

        results = {}

        # Process advisors concurrently
        tasks = [
            self._update_advisor(advisor_key) for advisor_key in self.advisors_to_update
        ]

        update_results = await asyncio.gather(*tasks, return_exceptions=True)

        for advisor_key, result in zip(self.advisors_to_update, update_results):
            if isinstance(result, Exception):
                logger.error(f"Exception updating {advisor_key}: {result}")
                results[advisor_key] = False
            else:
                results[advisor_key] = result

        success_count = sum(1 for v in results.values() if v)
        logger.info(
            f"Daily advisor updates complete: {success_count}/{len(self.advisors_to_update)} successful"
        )

        return results

    async def _update_advisor(self, advisor_key: str) -> bool:
        """Update single advisor.

        Process:
        1. Get advisor's daily report
        2. Upload to Drive
        3. Send to Slack

        Args:
            advisor_key: Advisor identifier

        Returns:
            True if successful
        """
        try:
            # 1. Get advisor's daily report
            report = await self._get_advisor_report(advisor_key)
            if not report:
                logger.warning(f"No report generated for {advisor_key}")
                return False

            # 2. Upload to Drive if report generator provided it
            drive_links = report.get("drive_links", {})
            if not drive_links and self.drive_manager:
                drive_links = await self._upload_advisor_report(advisor_key, report)
                report["drive_links"] = drive_links

            # 3. Send to Slack
            if self.slack_bridge:
                response = await self.slack_bridge.send_daily_advisor_update(
                    advisor_key=advisor_key,
                    report_data=report,
                )

                if response and response.get("ok"):
                    logger.info(f"Successfully updated {advisor_key} in Slack")
                    return True
                else:
                    logger.error(f"Failed to post {advisor_key} update to Slack")
                    return False
            else:
                logger.warning("Slack bridge not configured, skipping Slack update")
                return True

        except Exception as e:
            logger.error(f"Failed to update advisor {advisor_key}: {e}")
            return False

    async def _get_advisor_report(self, advisor_key: str) -> Optional[Dict[str, Any]]:
        """Get daily report from advisor.

        Args:
            advisor_key: Advisor identifier

        Returns:
            Report dict or None if not available
        """
        generator = self.report_generators.get(advisor_key)
        if not generator:
            logger.warning(f"No report generator registered for {advisor_key}")
            return None

        try:
            report = await generator()
            if not isinstance(report, dict):
                logger.error(f"Report generator for {advisor_key} returned non-dict")
                return None

            # Ensure required fields
            report.setdefault("summary", "Daily update from advisor")
            report.setdefault("drive_links", {})
            report.setdefault("timestamp", datetime.now())

            return report
        except Exception as e:
            logger.error(f"Report generator for {advisor_key} failed: {e}")
            return None

    async def _upload_advisor_report(
        self, advisor_key: str, report: Dict[str, Any]
    ) -> Dict[str, str]:
        """Upload advisor report to Google Drive.

        Args:
            advisor_key: Advisor identifier
            report: Report data to upload

        Returns:
            Dict of {type: drive_link_url}
        """
        if not self.drive_manager:
            logger.warning("Drive manager not configured")
            return {}

        try:
            # Create folder name: advisor_key_YYYY-MM-DD
            date_str = datetime.now().strftime("%Y-%m-%d")
            folder_name = f"{advisor_key}_{date_str}"

            drive_links = {}

            # Upload summary as document
            if "summary" in report:
                summary_text = report["summary"]
                # This would need a proper implementation to upload text as a Drive doc
                # For now, return empty as this depends on specific document structure
                logger.debug(f"Would upload summary for {advisor_key} to Drive")

            # Upload data files if available
            if "data_files" in report:
                for file_key, file_data in report.get("data_files", {}).items():
                    # Upload file to Drive
                    logger.debug(f"Would upload data file {file_key} for {advisor_key}")

            return drive_links

        except Exception as e:
            logger.error(f"Failed to upload report for {advisor_key}: {e}")
            return {}

    async def start_scheduler(self) -> None:
        """Start the daily scheduler loop.

        Runs indefinitely, checking at the scheduled hour each day.
        """
        logger.info(
            f"Starting advisor daily scheduler (update hour: {self.update_hour}:00 UTC)"
        )

        while True:
            try:
                now = datetime.utcnow()
                scheduled_time = now.replace(
                    hour=self.update_hour, minute=0, second=0, microsecond=0
                )

                # If we're past today's scheduled time, schedule for tomorrow
                if now > scheduled_time:
                    scheduled_time = (
                        scheduled_time.replace(day=scheduled_time.day + 1)
                        if scheduled_time.day < 31
                        else (
                            scheduled_time.replace(
                                day=1, month=scheduled_time.month + 1
                            )
                            if scheduled_time.month < 12
                            else scheduled_time.replace(
                                day=1, month=1, year=scheduled_time.year + 1
                            )
                        )
                    )

                sleep_seconds = (scheduled_time - now).total_seconds()
                logger.debug(
                    f"Next update scheduled in {sleep_seconds:.0f} seconds "
                    f"({scheduled_time.strftime('%Y-%m-%d %H:%M:%S')} UTC)"
                )

                # Sleep until update time
                await asyncio.sleep(sleep_seconds)

                # Run updates
                await self.schedule_advisor_updates()

            except Exception as e:
                logger.error(f"Exception in scheduler loop: {e}")
                # Sleep for 1 minute before retrying
                await asyncio.sleep(60)

    def get_update_schedule(self) -> Dict[str, Any]:
        """Get scheduler configuration.

        Returns:
            Dict with schedule info
        """
        return {
            "update_hour": self.update_hour,
            "advisors": self.advisors_to_update,
            "generators_registered": len(self.report_generators),
            "slack_bridge_configured": self.slack_bridge is not None,
            "drive_manager_configured": self.drive_manager is not None,
        }


class AdvisorUpdateTask:
    """Represents a single advisor update task."""

    def __init__(
        self,
        advisor_key: str,
        scheduled_for: datetime,
        retry_count: int = 0,
        max_retries: int = 3,
    ):
        """Initialize update task.

        Args:
            advisor_key: Advisor identifier
            scheduled_for: Scheduled execution time
            retry_count: Current retry count
            max_retries: Maximum number of retries
        """
        self.advisor_key = advisor_key
        self.scheduled_for = scheduled_for
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.created_at = datetime.now()
        self.last_error: Optional[str] = None

    def should_retry(self) -> bool:
        """Check if task should be retried.

        Returns:
            True if retry count < max_retries
        """
        return self.retry_count < self.max_retries

    def mark_failed(self, error: str) -> None:
        """Mark task as failed and increment retry count.

        Args:
            error: Error message
        """
        self.retry_count += 1
        self.last_error = error
        logger.warning(
            f"Task for {self.advisor_key} failed (attempt {self.retry_count}/{self.max_retries}): {error}"
        )

    def mark_success(self) -> None:
        """Mark task as successful."""
        self.last_error = None
        logger.info(f"Task for {self.advisor_key} completed successfully")
