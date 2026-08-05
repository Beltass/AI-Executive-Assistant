"""Drive Folder Manager for hierarchical organization of advisor outputs.

Provides structured folder organization on Google Drive:
- Automatic folder hierarchy creation by advisor type
- Date-based organization (YYYY-MM format)
- Versioning support (v1, v2, v3...)
- Daily backup creation
- Monthly archiving
- Automatic cleanup of old files

Example usage:
    manager = DriveFolderManager(drive_manager, root_folder_id)
    await manager.initialize_folder_structure()

    links = await manager.upload_advisor_output(
        advisor_type=AdvisorType.DATA_ANALYST,
        output_name="Sales Analysis 2026-08-05",
        files={"report": "/tmp/report.pdf", "data": "/tmp/data.xlsx"}
    )
"""

from __future__ import annotations

import logging
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import asyncio

logger = logging.getLogger(__name__)


class AdvisorType(Enum):
    """Advisor types with folder mappings."""
    MEETING_NOTES = "meeting_notes"
    DATA_ANALYST = "data_analyst"
    LINKEDIN_COACH = "linkedin_coach"
    SOCIAL_MEDIA_COACH = "social_media_coach"
    PERSONAL_ASSISTANT = "personal_assistant"


@dataclass
class FolderStructure:
    """Defines folder hierarchy for each advisor."""
    root_folder_id: str
    current_month_folder: str
    archive_folder: str
    backup_folder: str


class DriveFolderManager:
    """Manages structured, hierarchical folder organization on Google Drive.

    Creates and maintains organized folder structures for each advisor type,
    with support for versioning and date-based organization.
    """

    FOLDER_STRUCTURE = {
        AdvisorType.MEETING_NOTES: {
            "display_name": "Meeting Notes",
            "subfolders": ["active", "archive", "backups"],
            "date_format": "%Y-%m"
        },
        AdvisorType.DATA_ANALYST: {
            "display_name": "Data Analysis",
            "subfolders": ["active", "archive", "backups", "templates"],
            "date_format": "%Y-%m"
        },
        AdvisorType.LINKEDIN_COACH: {
            "display_name": "LinkedIn Coach",
            "subfolders": ["profile_analysis", "content_calendar", "engagement_reports", "backups"],
            "date_format": "%Y-%m"
        },
        AdvisorType.SOCIAL_MEDIA_COACH: {
            "display_name": "Social Media Analysis",
            "subfolders": ["linkedin", "instagram", "twitter", "backups"],
            "date_format": "%Y-%m"
        },
        AdvisorType.PERSONAL_ASSISTANT: {
            "display_name": "Personal Assistant",
            "subfolders": ["daily_briefs", "tasks", "goals", "backups"],
            "date_format": "%Y-%m"
        }
    }

    def __init__(self, drive_manager: Any, root_folder_id: str):
        """Initialize the Drive Folder Manager.

        Args:
            drive_manager: GoogleDriveManager instance
            root_folder_id: Root folder ID for all advisor outputs
        """
        self.drive_manager = drive_manager
        self.root_folder_id = root_folder_id
        self.folder_cache: Dict[AdvisorType, Dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)

    async def initialize_folder_structure(self) -> Dict[str, str]:
        """Create complete folder hierarchy on first run.

        Returns:
            Dictionary mapping advisor types to their root folder IDs
        """
        self.logger.info("Initializing Drive folder structure...")
        results = {}

        for advisor_type, config in self.FOLDER_STRUCTURE.items():
            try:
                folder_id = await self._create_advisor_root(advisor_type, config)
                results[advisor_type.value] = folder_id
                self.logger.info(f"Initialized folder structure for {advisor_type.value}")
            except Exception as e:
                self.logger.error(f"Failed to initialize {advisor_type.value}: {e}")
                raise

        return results

    async def _create_advisor_root(self, advisor_type: AdvisorType, config: dict) -> str:
        """Create advisor root folder and subfolders.

        Args:
            advisor_type: The advisor type
            config: Configuration dict with display_name and subfolders

        Returns:
            Root folder ID
        """
        # Check if folder already exists
        existing_folder = self.drive_manager.get_folder_id_by_name(
            config["display_name"],
            self.root_folder_id
        )

        if existing_folder:
            self.logger.info(f"Advisor folder '{config['display_name']}' already exists")
            advisor_folder_id = existing_folder
        else:
            # Create root folder: AI-Executive-Assistant/[Advisor Name]
            advisor_folder_id = self.drive_manager.create_folder(
                folder_name=config["display_name"],
                parent_folder_id=self.root_folder_id
            )
            if not advisor_folder_id:
                raise Exception(f"Failed to create advisor root folder for {config['display_name']}")

        # Create/verify subfolders
        subfolders = {}
        for subfolder in config["subfolders"]:
            subfolder_id = self.drive_manager.get_or_create_folder(
                folder_name=subfolder,
                parent_folder_id=advisor_folder_id
            )
            if subfolder_id:
                subfolders[subfolder] = subfolder_id

        # Cache for quick access
        self.folder_cache[advisor_type] = {
            'root': advisor_folder_id,
            'subfolders': subfolders,
            'config': config
        }

        return advisor_folder_id

    async def get_current_month_folder(self, advisor_type: AdvisorType) -> str:
        """Get or create current month folder (e.g., 2026-08/).

        Args:
            advisor_type: The advisor type

        Returns:
            Current month folder ID
        """
        date_str = datetime.now().strftime("%Y-%m")

        if advisor_type not in self.folder_cache:
            await self._ensure_advisor_initialized(advisor_type)

        root_id = self.folder_cache[advisor_type]['root']

        # Check if folder exists
        existing = self.drive_manager.get_file_by_name(root_id, date_str)

        if existing:
            return existing['id']

        # Create month folder
        month_folder_id = self.drive_manager.create_folder(
            folder_name=date_str,
            parent_folder_id=root_id
        )

        if not month_folder_id:
            raise Exception(f"Failed to create month folder {date_str}")

        return month_folder_id

    async def _ensure_advisor_initialized(self, advisor_type: AdvisorType) -> None:
        """Ensure advisor folder is initialized.

        Args:
            advisor_type: The advisor type to initialize
        """
        if advisor_type not in self.folder_cache:
            config = self.FOLDER_STRUCTURE[advisor_type]
            await self._create_advisor_root(advisor_type, config)

    async def upload_advisor_output(
        self,
        advisor_type: AdvisorType,
        output_name: str,
        files: Dict[str, str]
    ) -> Dict[str, str]:
        """Upload advisor output to organized structure.

        Creates a folder hierarchy:
            [AdvisorName]/YYYY-MM/[OutputName]/
            ├── file1.pdf
            ├── file2.xlsx
            └── file3.txt

        Args:
            advisor_type: Type of advisor
            output_name: Name of output folder (e.g., "Sales Analysis 2026-08-05")
            files: Dict mapping file keys to file paths

        Returns:
            Dict mapping file keys to their Google Drive links
        """
        self.logger.info(f"Uploading output for {advisor_type.value}: {output_name}")

        await self._ensure_advisor_initialized(advisor_type)

        # Get month folder
        month_folder_id = await self.get_current_month_folder(advisor_type)

        # Create output folder (e.g., "Sales Analysis 2026-08-05")
        output_folder_id = self.drive_manager.create_folder(
            folder_name=output_name,
            parent_folder_id=month_folder_id
        )

        if not output_folder_id:
            raise Exception(f"Failed to create output folder: {output_name}")

        # Upload all files to output folder
        drive_links = {}
        for file_key, file_path in files.items():
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"{file_key}_{timestamp}"

                file_id = self.drive_manager.upload_file(
                    file_path=file_path,
                    folder_id=output_folder_id,
                    file_name=file_name
                )

                if file_id:
                    drive_links[file_key] = self.drive_manager.get_file_link(file_id)
                    self.logger.info(f"Uploaded {file_key} for {output_name}")
                else:
                    self.logger.error(f"Failed to upload {file_key}")

            except Exception as e:
                self.logger.error(f"Error uploading {file_key}: {e}")

        return drive_links

    async def create_version(
        self,
        advisor_type: AdvisorType,
        output_name: str,
        file_path: str
    ) -> str:
        """Create versioned copy (v1, v2, v3...) in same folder.

        Args:
            advisor_type: Type of advisor
            output_name: Base name for the file
            file_path: Path to file to upload

        Returns:
            Google Drive link to uploaded file
        """
        self.logger.info(f"Creating version for {output_name}")

        await self._ensure_advisor_initialized(advisor_type)
        month_folder_id = await self.get_current_month_folder(advisor_type)

        # Check for existing versions
        existing_files = self.drive_manager.list_files(month_folder_id)
        versions = [
            f for f in existing_files
            if output_name in f['name'] and 'v' in f['name']
        ]
        version_num = len(versions) + 1

        # Upload with version number
        file_id = self.drive_manager.upload_file(
            file_path=file_path,
            folder_id=month_folder_id,
            file_name=f"{output_name}_v{version_num}"
        )

        if not file_id:
            raise Exception(f"Failed to create version for {output_name}")

        return self.drive_manager.get_file_link(file_id)

    async def get_folder_stats(self, advisor_type: AdvisorType) -> Dict[str, Any]:
        """Get statistics about advisor's folder.

        Args:
            advisor_type: Type of advisor

        Returns:
            Dictionary with folder statistics
        """
        await self._ensure_advisor_initialized(advisor_type)
        root_id = self.folder_cache[advisor_type]['root']

        files = self.drive_manager.list_files(root_id)

        total_files = len(files)
        total_size = sum(int(f.get('size', 0)) for f in files if 'size' in f)

        return {
            "advisor_type": advisor_type.value,
            "root_folder_id": root_id,
            "total_files": total_files,
            "total_size_bytes": total_size,
            "created_at": datetime.now().isoformat()
        }


class DriveBackupManager:
    """Manages backup and archiving of advisor outputs.

    Provides:
    - Daily snapshots of current month folders
    - Automatic archiving of old files
    - Monthly archive creation
    """

    def __init__(
        self,
        drive_manager: Any,
        folder_manager: DriveFolderManager,
        archive_older_than_days: int = 30
    ):
        """Initialize the Backup Manager.

        Args:
            drive_manager: GoogleDriveManager instance
            folder_manager: DriveFolderManager instance
            archive_older_than_days: Archive files older than N days
        """
        self.drive_manager = drive_manager
        self.folder_manager = folder_manager
        self.archive_older_than_days = archive_older_than_days
        self.logger = logging.getLogger(__name__)

    async def create_daily_backup(self, advisor_type: AdvisorType) -> str:
        """Create daily snapshot of advisor folder.

        Args:
            advisor_type: Type of advisor to backup

        Returns:
            Backup folder ID
        """
        self.logger.info(f"Creating daily backup for {advisor_type.value}")

        try:
            await self.folder_manager._ensure_advisor_initialized(advisor_type)

            backup_folder_id = self.folder_manager.folder_cache[advisor_type]['subfolders'].get('backups')
            if not backup_folder_id:
                self.logger.error(f"Backup folder not found for {advisor_type.value}")
                return None

            today = datetime.now().strftime("%Y-%m-%d")

            # Create daily backup folder
            daily_backup = self.drive_manager.create_folder(
                folder_name=today,
                parent_folder_id=backup_folder_id
            )

            if not daily_backup:
                raise Exception(f"Failed to create backup folder for {today}")

            # Copy all files from current month to backup
            current_month_id = await self.folder_manager.get_current_month_folder(advisor_type)
            files_to_backup = self.drive_manager.list_files(current_month_id)

            backup_count = 0
            for file in files_to_backup:
                try:
                    # Copy file to backup folder
                    new_file = self.drive_manager.service.files().copy(
                        fileId=file['id'],
                        body={'parents': [daily_backup], 'name': f"{file['name']}_backup"},
                        fields='id'
                    ).execute()

                    if new_file:
                        backup_count += 1
                        self.logger.debug(f"Backed up file: {file['name']}")

                except Exception as e:
                    self.logger.error(f"Failed to backup file {file['name']}: {e}")

            self.logger.info(f"Daily backup created with {backup_count} files for {advisor_type.value}")
            return daily_backup

        except Exception as e:
            self.logger.error(f"Failed to create daily backup for {advisor_type.value}: {e}")
            return None

    async def archive_old_files(
        self,
        advisor_type: AdvisorType,
        older_than_days: Optional[int] = None
    ) -> int:
        """Move files older than N days to archive folder.

        Args:
            advisor_type: Type of advisor
            older_than_days: Archive files older than N days (uses default if None)

        Returns:
            Number of files archived
        """
        if older_than_days is None:
            older_than_days = self.archive_older_than_days

        self.logger.info(
            f"Archiving files older than {older_than_days} days for {advisor_type.value}"
        )

        try:
            await self.folder_manager._ensure_advisor_initialized(advisor_type)

            root_id = self.folder_manager.folder_cache[advisor_type]['root']
            archive_folder_id = self.folder_manager.folder_cache[advisor_type]['subfolders'].get('archive')

            if not archive_folder_id:
                self.logger.error(f"Archive folder not found for {advisor_type.value}")
                return 0

            # List all month folders
            month_folders = self.drive_manager.list_files(
                root_id,
                mime_type='application/vnd.google-apps.folder'
            )

            archived_count = 0
            cutoff_date = datetime.now() - timedelta(days=older_than_days)

            for month_folder in month_folders:
                try:
                    # Parse folder date
                    folder_date = datetime.strptime(month_folder['name'], "%Y-%m")

                    if folder_date < cutoff_date:
                        # Move folder to archive
                        self.drive_manager.move_file(
                            file_id=month_folder['id'],
                            parent_folder_id=archive_folder_id
                        )
                        archived_count += 1
                        self.logger.info(f"Archived folder: {month_folder['name']}")

                except ValueError:
                    # Skip folders that don't match date format
                    self.logger.debug(f"Skipping non-date folder: {month_folder['name']}")
                except Exception as e:
                    self.logger.error(f"Failed to archive {month_folder['name']}: {e}")

            self.logger.info(f"Archived {archived_count} folders for {advisor_type.value}")
            return archived_count

        except Exception as e:
            self.logger.error(f"Failed to archive old files for {advisor_type.value}: {e}")
            return 0

    async def create_monthly_archive(self, advisor_type: AdvisorType) -> Optional[str]:
        """At end of month, create archive snapshot.

        Args:
            advisor_type: Type of advisor

        Returns:
            Archive folder ID or None if failed
        """
        self.logger.info(f"Creating monthly archive for {advisor_type.value}")

        try:
            await self.folder_manager._ensure_advisor_initialized(advisor_type)

            archive_folder_id = self.folder_manager.folder_cache[advisor_type]['subfolders'].get('archive')
            if not archive_folder_id:
                self.logger.error(f"Archive folder not found for {advisor_type.value}")
                return None

            month_str = datetime.now().strftime("%Y-%m")
            archive_snapshot_name = f"{month_str}_archive"

            # Create archive folder
            archive_snapshot = self.drive_manager.create_folder(
                folder_name=archive_snapshot_name,
                parent_folder_id=archive_folder_id
            )

            if not archive_snapshot:
                raise Exception(f"Failed to create archive folder {archive_snapshot_name}")

            # Copy entire month folder to archive
            current_month_id = await self.folder_manager.get_current_month_folder(advisor_type)
            files = self.drive_manager.list_files(current_month_id)

            copy_count = 0
            for file in files:
                try:
                    new_file = self.drive_manager.service.files().copy(
                        fileId=file['id'],
                        body={'parents': [archive_snapshot], 'name': file['name']},
                        fields='id'
                    ).execute()

                    if new_file:
                        copy_count += 1
                        self.logger.debug(f"Archived file: {file['name']}")

                except Exception as e:
                    self.logger.error(f"Failed to archive file {file['name']}: {e}")

            self.logger.info(f"Monthly archive created with {copy_count} files for {advisor_type.value}")
            return archive_snapshot

        except Exception as e:
            self.logger.error(f"Failed to create monthly archive for {advisor_type.value}: {e}")
            return None

    async def cleanup_old_backups(
        self,
        advisor_type: AdvisorType,
        keep_days: int = 7
    ) -> int:
        """Delete backup snapshots older than keep_days.

        Args:
            advisor_type: Type of advisor
            keep_days: Number of days of backups to keep

        Returns:
            Number of backup folders deleted
        """
        self.logger.info(f"Cleaning up backups older than {keep_days} days for {advisor_type.value}")

        try:
            await self.folder_manager._ensure_advisor_initialized(advisor_type)

            backup_folder_id = self.folder_manager.folder_cache[advisor_type]['subfolders'].get('backups')
            if not backup_folder_id:
                self.logger.error(f"Backup folder not found for {advisor_type.value}")
                return 0

            # List all backup folders
            backup_folders = self.drive_manager.list_files(
                backup_folder_id,
                mime_type='application/vnd.google-apps.folder'
            )

            deleted_count = 0
            cutoff_date = datetime.now() - timedelta(days=keep_days)

            for backup_folder in backup_folders:
                try:
                    # Parse folder date
                    backup_date = datetime.strptime(backup_folder['name'], "%Y-%m-%d")

                    if backup_date < cutoff_date:
                        # Move to trash
                        self.drive_manager.service.files().update(
                            fileId=backup_folder['id'],
                            body={'trashed': True}
                        ).execute()
                        deleted_count += 1
                        self.logger.info(f"Deleted backup folder: {backup_folder['name']}")

                except ValueError:
                    # Skip folders that don't match date format
                    self.logger.debug(f"Skipping non-date backup folder: {backup_folder['name']}")
                except Exception as e:
                    self.logger.error(f"Failed to delete backup {backup_folder['name']}: {e}")

            self.logger.info(f"Deleted {deleted_count} backup folders for {advisor_type.value}")
            return deleted_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup backups for {advisor_type.value}: {e}")
            return 0
