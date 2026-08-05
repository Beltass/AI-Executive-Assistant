"""Meeting Notes Poller - Main entrypoint for the meeting-notes-poller workflow.

Runs every 30 minutes to:
1. Poll Gmail for new meeting notifications
2. Extract audio file URLs (Drive, Dropbox, etc.)
3. Transcribe audio
4. Analyze with LLM
5. Generate reports (PDF, Doc, Excel)
6. Create tasks in tracker
7. Send Slack deadline reminders
8. Sync to Drive

Usage:
    python -m ai_assistant.integrations.meeting_notes_poller
    python -m ai_assistant.integrations.meeting_notes_poller \
        --email-query="subject:Meeting" \
        --auto-transcribe=true \
        --generate-reports=true
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..advisors.meeting_notes import MeetingNotesAgent, MeetingNotes
from ..integrations.gmail import GmailClient
from ..integrations.google_drive_manager import GoogleDriveManager
from ..integrations.task_tracker import TaskTracker

logger = logging.getLogger(__name__)


class MeetingNotesPoller:
    """Main poller for meeting notes from Gmail."""

    def __init__(self):
        """Initialize the poller."""
        self.logger = logging.getLogger(__name__)
        self.agent = MeetingNotesAgent()
        self.drive_manager = GoogleDriveManager()
        self.task_tracker = TaskTracker()
        self.state_dir = Path(".assistant_state")
        self.state_dir.mkdir(exist_ok=True)
        self.processed_file = self.state_dir / "processed_meetings.json"

    async def run(
        self,
        email_query: str = 'from:notifications has:attachment filename:(mp3 OR wav OR m4a)',
        auto_transcribe: bool = True,
        generate_reports: bool = True,
    ) -> bool:
        """Run the poller.

        Args:
            email_query: Gmail query for finding meeting emails
            auto_transcribe: Whether to auto-transcribe audio
            generate_reports: Whether to generate reports

        Returns:
            True if successful
        """
        try:
            self.logger.info("Starting Meeting Notes Poller")

            # Get Gmail client
            gmail_client = GmailClient()

            # Search for meeting emails
            self.logger.info(f"Searching Gmail: {email_query}")
            messages = gmail_client.search(email_query, max_results=10)

            if not messages:
                self.logger.info("No new meeting emails found")
                return True

            self.logger.info(f"Found {len(messages)} potential meeting emails")

            # Process each message
            processed_count = 0
            for message in messages:
                meeting_id = message.get('id')

                # Skip if already processed
                if self._is_processed(meeting_id):
                    self.logger.debug(f"Meeting {meeting_id} already processed")
                    continue

                try:
                    success = await self._process_meeting(
                        message,
                        auto_transcribe=auto_transcribe,
                        generate_reports=generate_reports,
                    )

                    if success:
                        self._mark_processed(meeting_id)
                        processed_count += 1

                except Exception as e:
                    self.logger.error(f"Failed to process meeting {meeting_id}: {e}")
                    continue

            self.logger.info(f"Processed {processed_count} new meetings")

            # Send reminders
            await self.agent.send_deadline_reminders()

            # Sync to Drive
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            if folder_id:
                self.task_tracker.sync_to_drive(folder_id)

            return True

        except Exception as e:
            self.logger.error(f"Poller failed: {e}")
            return False

    async def _process_meeting(
        self,
        message: dict,
        auto_transcribe: bool = True,
        generate_reports: bool = True,
    ) -> bool:
        """Process a single meeting email.

        Args:
            message: Gmail message dict
            auto_transcribe: Whether to transcribe audio
            generate_reports: Whether to generate reports

        Returns:
            True if successful
        """
        try:
            message_id = message.get('id')
            subject = message.get('subject', 'Unknown Meeting')

            self.logger.info(f"Processing meeting: {subject}")

            # Extract audio URL from message (mock implementation)
            audio_url = self._extract_audio_url(message)

            if not audio_url:
                self.logger.warning(f"No audio URL found in message {message_id}")
                return False

            # Transcribe audio if enabled
            transcript = ""
            if auto_transcribe:
                self.logger.info(f"Transcribing audio from {audio_url}")
                transcript = await self.agent.transcribe_audio(audio_url)

                if not transcript:
                    self.logger.error("Transcription failed")
                    return False

            # Analyze meeting
            self.logger.info("Analyzing meeting...")
            attendees = message.get('attendees', [])
            meeting_notes = await self.agent.analyze_meeting(
                transcript,
                meeting_title=subject,
                attendees=attendees,
            )

            # Generate reports if enabled
            if generate_reports:
                self.logger.info("Generating reports...")
                reports = await self.agent.generate_report(meeting_notes)
                self.logger.info(f"Generated reports: {reports}")

            # Create tasks
            self.logger.info(f"Creating {len(meeting_notes.action_items)} action items...")
            task_ids = await self.agent.create_tasks_in_tracker(
                meeting_notes.action_items,
                meeting_notes.meeting_id,
            )
            self.logger.info(f"Created {len(task_ids)} tasks")

            # Save meeting notes to state
            self._save_meeting_notes(meeting_notes)

            return True

        except Exception as e:
            self.logger.error(f"Failed to process meeting: {e}")
            return False

    def _extract_audio_url(self, message: dict) -> Optional[str]:
        """Extract audio file URL from message.

        Looks for:
        - Google Drive links (drive.google.com)
        - Dropbox links (dropbox.com)
        - Direct attachment URLs

        Args:
            message: Gmail message dict

        Returns:
            Audio URL or None
        """
        # This is a mock implementation
        # In production, would parse email body/attachments
        body = message.get('body', '')

        if 'drive.google.com' in body:
            self.logger.debug("Found Google Drive link in message")
            # Extract drive ID from URL
            import re
            match = re.search(r'/d/([a-zA-Z0-9-_]+)', body)
            if match:
                return f"https://drive.google.com/file/d/{match.group(1)}/preview"

        if 'dropbox.com' in body:
            self.logger.debug("Found Dropbox link in message")
            # Would extract Dropbox URL

        return None

    def _save_meeting_notes(self, notes: MeetingNotes) -> None:
        """Save meeting notes to persistent storage."""
        try:
            meetings_file = self.state_dir / "meetings.json"
            data = {}

            if meetings_file.exists():
                with open(meetings_file, 'r') as f:
                    data = json.load(f)

            data[notes.meeting_id] = notes.to_dict()

            with open(meetings_file, 'w') as f:
                json.dump(data, f, indent=2)

            self.logger.info(f"Saved meeting notes: {notes.meeting_id}")

        except Exception as e:
            self.logger.error(f"Failed to save meeting notes: {e}")

    def _is_processed(self, message_id: str) -> bool:
        """Check if message already processed."""
        try:
            if not self.processed_file.exists():
                return False

            with open(self.processed_file, 'r') as f:
                data = json.load(f)

            return message_id in data.get('processed', [])

        except Exception:
            return False

    def _mark_processed(self, message_id: str) -> None:
        """Mark message as processed."""
        try:
            data = {}

            if self.processed_file.exists():
                with open(self.processed_file, 'r') as f:
                    data = json.load(f)

            if 'processed' not in data:
                data['processed'] = []

            data['processed'].append(message_id)
            data['last_run'] = datetime.now(timezone.utc).isoformat()

            with open(self.processed_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to mark message as processed: {e}")


async def main():
    """Main entrypoint."""
    parser = argparse.ArgumentParser(
        description="Meeting Notes Poller - Process meeting emails and track action items"
    )
    parser.add_argument(
        "--email-query",
        default='from:notifications has:attachment filename:(mp3 OR wav OR m4a)',
        help="Gmail query for finding meeting emails",
    )
    parser.add_argument(
        "--auto-transcribe",
        type=lambda x: x.lower() == 'true',
        default=True,
        help="Auto-transcribe audio files",
    )
    parser.add_argument(
        "--generate-reports",
        type=lambda x: x.lower() == 'true',
        default=True,
        help="Generate meeting reports",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run poller
    poller = MeetingNotesPoller()
    success = await poller.run(
        email_query=args.email_query,
        auto_transcribe=args.auto_transcribe,
        generate_reports=args.generate_reports,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
