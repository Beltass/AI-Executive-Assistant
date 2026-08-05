"""Drive Backup Scheduler - CLI for automated backup operations.

Provides command-line interface for:
- Daily backups
- Monthly archiving
- Old file cleanup
- Backup cleanup

Usage:
    python -m ai_assistant.integrations.drive_backup_scheduler daily
    python -m ai_assistant.integrations.drive_backup_scheduler monthly
    python -m ai_assistant.integrations.drive_backup_scheduler archive --older-than=30
    python -m ai_assistant.integrations.drive_backup_scheduler cleanup --keep-days=7
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from .google_drive_manager import GoogleDriveManager
from .drive_folder_manager import (
    DriveFolderManager,
    DriveBackupManager,
    AdvisorType
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BackupScheduler:
    """Scheduler for automated backup operations."""

    def __init__(self):
        """Initialize the scheduler."""
        self.drive_manager = GoogleDriveManager()

        root_folder_id = os.getenv('GOOGLE_DRIVE_ROOT_FOLDER_ID')
        if not root_folder_id:
            raise ValueError("GOOGLE_DRIVE_ROOT_FOLDER_ID environment variable not set")

        self.folder_manager = DriveFolderManager(self.drive_manager, root_folder_id)
        self.backup_manager = DriveBackupManager(self.drive_manager, self.folder_manager)

    async def create_daily_backups(self) -> None:
        """Create daily backups for all advisor types."""
        logger.info("Starting daily backup process...")

        for advisor_type in AdvisorType:
            try:
                await self.backup_manager.create_daily_backup(advisor_type)
                logger.info(f"Daily backup completed for {advisor_type.value}")
            except Exception as e:
                logger.error(f"Failed to backup {advisor_type.value}: {e}")

        logger.info("Daily backup process completed")

    async def create_monthly_archives(self) -> None:
        """Create monthly archives for all advisor types."""
        logger.info("Starting monthly archive process...")

        for advisor_type in AdvisorType:
            try:
                await self.backup_manager.create_monthly_archive(advisor_type)
                logger.info(f"Monthly archive completed for {advisor_type.value}")
            except Exception as e:
                logger.error(f"Failed to archive {advisor_type.value}: {e}")

        logger.info("Monthly archive process completed")

    async def archive_old_files(self, older_than_days: int = 30) -> None:
        """Archive files older than specified days.

        Args:
            older_than_days: Archive files older than this many days
        """
        logger.info(f"Starting archive process for files older than {older_than_days} days...")

        for advisor_type in AdvisorType:
            try:
                count = await self.backup_manager.archive_old_files(
                    advisor_type,
                    older_than_days=older_than_days
                )
                logger.info(f"Archived {count} folders for {advisor_type.value}")
            except Exception as e:
                logger.error(f"Failed to archive {advisor_type.value}: {e}")

        logger.info("Archive process completed")

    async def cleanup_old_backups(self, keep_days: int = 7) -> None:
        """Clean up backup snapshots older than specified days.

        Args:
            keep_days: Keep backups from the last N days
        """
        logger.info(f"Starting cleanup process for backups older than {keep_days} days...")

        for advisor_type in AdvisorType:
            try:
                count = await self.backup_manager.cleanup_old_backups(
                    advisor_type,
                    keep_days=keep_days
                )
                logger.info(f"Deleted {count} backup folders for {advisor_type.value}")
            except Exception as e:
                logger.error(f"Failed to cleanup {advisor_type.value}: {e}")

        logger.info("Cleanup process completed")


async def main():
    """Main entry point for CLI."""
    if len(sys.argv) < 2:
        print("Usage: python -m ai_assistant.integrations.drive_backup_scheduler <command> [options]")
        print("Commands:")
        print("  daily                    - Create daily backups for all advisors")
        print("  monthly                  - Create monthly archives for all advisors")
        print("  archive                  - Archive old files (--older-than=DAYS)")
        print("  cleanup                  - Cleanup old backups (--keep-days=DAYS)")
        sys.exit(1)

    command = sys.argv[1]

    try:
        scheduler = BackupScheduler()

        if command == "daily":
            await scheduler.create_daily_backups()
        elif command == "monthly":
            await scheduler.create_monthly_archives()
        elif command == "archive":
            older_than = 30
            for arg in sys.argv[2:]:
                if arg.startswith("--older-than="):
                    older_than = int(arg.split("=")[1])
            await scheduler.archive_old_files(older_than)
        elif command == "cleanup":
            keep_days = 7
            for arg in sys.argv[2:]:
                if arg.startswith("--keep-days="):
                    keep_days = int(arg.split("=")[1])
            await scheduler.cleanup_old_backups(keep_days)
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Backup scheduler failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
