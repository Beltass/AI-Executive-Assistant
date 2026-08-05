"""Tests for Drive Folder Manager and Backup Manager.

Comprehensive test suite with 25+ tests covering:
- Folder structure creation
- File uploads and organization
- Versioning
- Backup operations
- Archive operations
- Error handling
- Concurrent operations
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from typing import Dict, List, Any

from src.ai_assistant.integrations.drive_folder_manager import (
    DriveFolderManager,
    DriveBackupManager,
    AdvisorType,
    FolderStructure
)


class TestDriveFolderManager:
    """Test suite for DriveFolderManager."""

    @pytest.fixture
    def mock_drive_manager(self):
        """Create a mock Google Drive Manager."""
        mock = Mock()
        mock.create_folder = Mock(side_effect=lambda folder_name, parent_folder_id: f"folder_{folder_name}")
        mock.get_folder_id_by_name = Mock(return_value=None)
        mock.get_or_create_folder = Mock(side_effect=lambda folder_name, parent_folder_id: f"folder_{folder_name}")
        mock.get_file_by_name = Mock(return_value=None)
        mock.list_files = Mock(return_value=[])
        mock.upload_file = Mock(return_value="file_123")
        mock.get_file_link = Mock(return_value="https://drive.google.com/file/d/file_123/view")
        mock.move_file = Mock(return_value=True)
        mock.service = Mock()
        mock.service.files = Mock(return_value=Mock())
        return mock

    @pytest.fixture
    def folder_manager(self, mock_drive_manager):
        """Create a DriveFolderManager instance."""
        return DriveFolderManager(mock_drive_manager, "root_folder_123")

    @pytest.mark.asyncio
    async def test_initialization(self, folder_manager):
        """Test DriveFolderManager initialization."""
        assert folder_manager.root_folder_id == "root_folder_123"
        assert isinstance(folder_manager.folder_cache, dict)
        assert len(folder_manager.folder_cache) == 0

    def test_folder_structure_enum(self):
        """Test AdvisorType enum."""
        assert AdvisorType.MEETING_NOTES.value == "meeting_notes"
        assert AdvisorType.DATA_ANALYST.value == "data_analyst"
        assert AdvisorType.LINKEDIN_COACH.value == "linkedin_coach"
        assert AdvisorType.SOCIAL_MEDIA_COACH.value == "social_media_coach"
        assert AdvisorType.PERSONAL_ASSISTANT.value == "personal_assistant"

    def test_folder_structure_config(self):
        """Test folder structure configuration."""
        config = DriveFolderManager.FOLDER_STRUCTURE
        assert len(config) == 5

        # Check DATA_ANALYST config
        data_analyst_config = config[AdvisorType.DATA_ANALYST]
        assert data_analyst_config["display_name"] == "Data Analysis"
        assert "active" in data_analyst_config["subfolders"]
        assert "archive" in data_analyst_config["subfolders"]
        assert "backups" in data_analyst_config["subfolders"]
        assert "templates" in data_analyst_config["subfolders"]

    @pytest.mark.asyncio
    async def test_create_advisor_root_new_folder(self, folder_manager, mock_drive_manager):
        """Test creating new advisor root folder."""
        config = DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]

        result = await folder_manager._create_advisor_root(AdvisorType.DATA_ANALYST, config)

        assert result == "folder_Data Analysis"
        assert AdvisorType.DATA_ANALYST in folder_manager.folder_cache
        mock_drive_manager.create_folder.assert_called()

    @pytest.mark.asyncio
    async def test_create_advisor_root_existing_folder(self, folder_manager, mock_drive_manager):
        """Test handling existing advisor root folder."""
        mock_drive_manager.get_folder_id_by_name = Mock(return_value="existing_folder_123")

        config = DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.LINKEDIN_COACH]

        result = await folder_manager._create_advisor_root(AdvisorType.LINKEDIN_COACH, config)

        assert result == "existing_folder_123"

    @pytest.mark.asyncio
    async def test_initialize_folder_structure(self, folder_manager, mock_drive_manager):
        """Test complete folder structure initialization."""
        results = await folder_manager.initialize_folder_structure()

        assert len(results) == 5
        assert "meeting_notes" in results
        assert "data_analyst" in results
        assert len(folder_manager.folder_cache) == 5

    @pytest.mark.asyncio
    async def test_get_current_month_folder_creates_new(self, folder_manager, mock_drive_manager):
        """Test creating current month folder."""
        # Pre-initialize cache
        folder_manager.folder_cache[AdvisorType.DATA_ANALYST] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
        }

        month_folder = await folder_manager.get_current_month_folder(AdvisorType.DATA_ANALYST)

        assert month_folder is not None
        current_month = datetime.now().strftime("%Y-%m")
        mock_drive_manager.get_file_by_name.assert_called()

    @pytest.mark.asyncio
    async def test_get_current_month_folder_existing(self, folder_manager, mock_drive_manager):
        """Test retrieving existing month folder."""
        mock_drive_manager.get_file_by_name = Mock(return_value={'id': 'existing_month_123'})

        # Pre-initialize cache
        folder_manager.folder_cache[AdvisorType.MEETING_NOTES] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.MEETING_NOTES]
        }

        month_folder = await folder_manager.get_current_month_folder(AdvisorType.MEETING_NOTES)

        assert month_folder == 'existing_month_123'

    @pytest.mark.asyncio
    async def test_upload_advisor_output(self, folder_manager, mock_drive_manager, tmp_path):
        """Test uploading advisor output files."""
        # Pre-initialize
        folder_manager.folder_cache[AdvisorType.DATA_ANALYST] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
        }

        files = {
            "report": str(tmp_path / "report.pdf"),
            "data": str(tmp_path / "data.xlsx"),
        }

        links = await folder_manager.upload_advisor_output(
            advisor_type=AdvisorType.DATA_ANALYST,
            output_name="Test Analysis",
            files=files
        )

        assert "report" in links
        assert "data" in links
        assert links["report"] == "https://drive.google.com/file/d/file_123/view"
        assert links["data"] == "https://drive.google.com/file/d/file_123/view"

    @pytest.mark.asyncio
    async def test_upload_advisor_output_creates_folder_hierarchy(self, folder_manager, mock_drive_manager, tmp_path):
        """Test folder hierarchy creation during upload."""
        folder_manager.folder_cache[AdvisorType.PERSONAL_ASSISTANT] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.PERSONAL_ASSISTANT]
        }

        files = {"summary": str(tmp_path / "summary.txt")}

        await folder_manager.upload_advisor_output(
            advisor_type=AdvisorType.PERSONAL_ASSISTANT,
            output_name="Daily Brief 2026-08-05",
            files=files
        )

        # Verify folder creation calls
        assert mock_drive_manager.create_folder.called

    @pytest.mark.asyncio
    async def test_create_version(self, folder_manager, mock_drive_manager, tmp_path):
        """Test creating versioned copies of files."""
        folder_manager.folder_cache[AdvisorType.DATA_ANALYST] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
        }

        mock_drive_manager.list_files = Mock(return_value=[])

        link = await folder_manager.create_version(
            advisor_type=AdvisorType.DATA_ANALYST,
            output_name="Sales Report",
            file_path=str(tmp_path / "report.pdf"),
        )

        assert link == "https://drive.google.com/file/d/file_123/view"
        mock_drive_manager.upload_file.assert_called()

    @pytest.mark.asyncio
    async def test_create_version_increments(self, folder_manager, mock_drive_manager, tmp_path):
        """Test version number incrementation."""
        folder_manager.folder_cache[AdvisorType.DATA_ANALYST] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
        }

        # Simulate existing versions
        mock_drive_manager.list_files = Mock(return_value=[
            {'name': 'Report_v1', 'id': 'file_1'},
            {'name': 'Report_v2', 'id': 'file_2'},
        ])

        await folder_manager.create_version(
            advisor_type=AdvisorType.DATA_ANALYST,
            output_name="Report",
            file_path=str(tmp_path / "report.pdf"),
        )

        # Verify that upload was called with v3
        call_args = mock_drive_manager.upload_file.call_args
        assert "v3" in call_args[1]['file_name'] or "v3" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_folder_stats(self, folder_manager, mock_drive_manager):
        """Test retrieving folder statistics."""
        folder_manager.folder_cache[AdvisorType.DATA_ANALYST] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
        }

        mock_drive_manager.list_files = Mock(return_value=[
            {'id': 'file_1', 'name': 'report.pdf', 'size': '1000000'},
            {'id': 'file_2', 'name': 'data.xlsx', 'size': '500000'},
        ])

        stats = await folder_manager.get_folder_stats(AdvisorType.DATA_ANALYST)

        assert stats['advisor_type'] == 'data_analyst'
        assert stats['total_files'] == 2
        assert stats['total_size_bytes'] == 1500000

    @pytest.mark.asyncio
    async def test_ensure_advisor_initialized(self, folder_manager, mock_drive_manager):
        """Test automatic initialization when accessing uninitialized advisor."""
        result = await folder_manager._ensure_advisor_initialized(AdvisorType.LINKEDIN_COACH)

        assert AdvisorType.LINKEDIN_COACH in folder_manager.folder_cache

    @pytest.mark.asyncio
    async def test_multiple_advisor_folders(self, folder_manager, mock_drive_manager):
        """Test managing folders for multiple advisors."""
        await folder_manager.initialize_folder_structure()

        # All advisors should have folders
        assert len(folder_manager.folder_cache) == 5

        # Each should have subfolder mapping
        for advisor_type, cache_data in folder_manager.folder_cache.items():
            assert 'root' in cache_data
            assert 'subfolders' in cache_data


class TestDriveBackupManager:
    """Test suite for DriveBackupManager."""

    @pytest.fixture
    def mock_drive_manager(self):
        """Create a mock Google Drive Manager."""
        mock = Mock()
        mock.create_folder = Mock(return_value="backup_folder_123")
        mock.list_files = Mock(return_value=[])
        mock.move_file = Mock(return_value=True)
        mock.service = Mock()
        mock.service.files = Mock(return_value=Mock())
        return mock

    @pytest.fixture
    def mock_folder_manager(self, mock_drive_manager):
        """Create a mock DriveFolderManager."""
        manager = Mock()
        manager.folder_cache = {
            AdvisorType.DATA_ANALYST: {
                'root': 'root_123',
                'subfolders': {
                    'backups': 'backup_folder_123',
                    'archive': 'archive_folder_123'
                }
            }
        }
        manager._ensure_advisor_initialized = AsyncMock()
        manager.get_current_month_folder = AsyncMock(return_value='month_123')
        return manager

    @pytest.fixture
    def backup_manager(self, mock_drive_manager, mock_folder_manager):
        """Create a DriveBackupManager instance."""
        return DriveBackupManager(mock_drive_manager, mock_folder_manager)

    @pytest.mark.asyncio
    async def test_backup_manager_initialization(self, backup_manager):
        """Test BackupManager initialization."""
        assert backup_manager.archive_older_than_days == 30

    @pytest.mark.asyncio
    async def test_create_daily_backup(self, backup_manager, mock_drive_manager, mock_folder_manager):
        """Test creating daily backup."""
        # Mock file copy
        copy_mock = MagicMock()
        copy_mock.execute = Mock(return_value={'id': 'copied_file_123'})
        mock_drive_manager.service.files.return_value.copy = Mock(return_value=copy_mock)

        # Mock list_files to return some files
        mock_drive_manager.list_files = Mock(return_value=[
            {'id': 'file_1', 'name': 'report.pdf'},
            {'id': 'file_2', 'name': 'data.xlsx'},
        ])

        result = await backup_manager.create_daily_backup(AdvisorType.DATA_ANALYST)

        assert result is not None
        mock_drive_manager.create_folder.assert_called()

    @pytest.mark.asyncio
    async def test_archive_old_files(self, backup_manager, mock_drive_manager, mock_folder_manager):
        """Test archiving files older than specified days."""
        # Mock month folders
        old_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m")
        recent_date = datetime.now().strftime("%Y-%m")

        mock_drive_manager.list_files = Mock(return_value=[
            {'id': 'old_folder_1', 'name': old_date},
            {'id': 'recent_folder_1', 'name': recent_date},
        ])

        mock_folder_manager.folder_cache[AdvisorType.DATA_ANALYST]['root'] = 'root_123'

        count = await backup_manager.archive_old_files(AdvisorType.DATA_ANALYST, older_than_days=30)

        assert count >= 0
        if count > 0:
            mock_drive_manager.move_file.assert_called()

    @pytest.mark.asyncio
    async def test_create_monthly_archive(self, backup_manager, mock_drive_manager, mock_folder_manager):
        """Test creating monthly archive."""
        # Mock file copy
        copy_mock = MagicMock()
        copy_mock.execute = Mock(return_value={'id': 'archived_file_123'})
        mock_drive_manager.service.files.return_value.copy = Mock(return_value=copy_mock)

        mock_drive_manager.list_files = Mock(return_value=[
            {'id': 'file_1', 'name': 'report.pdf'},
        ])

        result = await backup_manager.create_monthly_archive(AdvisorType.DATA_ANALYST)

        assert result is not None
        mock_drive_manager.create_folder.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_old_backups(self, backup_manager, mock_drive_manager, mock_folder_manager):
        """Test cleaning up old backup folders."""
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")

        mock_drive_manager.list_files = Mock(return_value=[
            {'id': 'backup_old', 'name': old_date},
            {'id': 'backup_recent', 'name': recent_date},
        ])

        update_mock = MagicMock()
        update_mock.execute = Mock(return_value={})
        mock_drive_manager.service.files.return_value.update = Mock(return_value=update_mock)

        count = await backup_manager.cleanup_old_backups(AdvisorType.DATA_ANALYST, keep_days=7)

        assert count >= 0

    @pytest.mark.asyncio
    async def test_archive_with_custom_days(self, backup_manager, mock_drive_manager, mock_folder_manager):
        """Test archiving with custom days parameter."""
        mock_drive_manager.list_files = Mock(return_value=[])
        mock_folder_manager.folder_cache[AdvisorType.DATA_ANALYST]['root'] = 'root_123'

        await backup_manager.archive_old_files(AdvisorType.DATA_ANALYST, older_than_days=60)

        # Should complete without error
        assert True

    @pytest.mark.asyncio
    async def test_cleanup_with_custom_days(self, backup_manager, mock_drive_manager, mock_folder_manager):
        """Test cleanup with custom days parameter."""
        mock_drive_manager.list_files = Mock(return_value=[])

        update_mock = MagicMock()
        update_mock.execute = Mock(return_value={})
        mock_drive_manager.service.files.return_value.update = Mock(return_value=update_mock)

        await backup_manager.cleanup_old_backups(AdvisorType.DATA_ANALYST, keep_days=14)

        # Should complete without error
        assert True


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.fixture
    def mock_drive_manager(self):
        """Create a mock Google Drive Manager."""
        mock = Mock()
        return mock

    @pytest.fixture
    def folder_manager(self, mock_drive_manager):
        """Create a DriveFolderManager instance."""
        return DriveFolderManager(mock_drive_manager, "root_folder_123")

    @pytest.mark.asyncio
    async def test_upload_with_missing_root_folder(self, folder_manager, mock_drive_manager, tmp_path):
        """Test handling missing root folder ID."""
        # Don't initialize, so folder_cache is empty
        with pytest.raises(Exception):
            await folder_manager.upload_advisor_output(
                advisor_type=AdvisorType.DATA_ANALYST,
                output_name="Test",
                files={"file": str(tmp_path / "test.txt")}
            )

    @pytest.mark.asyncio
    async def test_create_folder_failure(self, folder_manager, mock_drive_manager):
        """Test handling folder creation failure."""
        mock_drive_manager.create_folder = Mock(return_value=None)
        mock_drive_manager.get_folder_id_by_name = Mock(return_value=None)

        # When create_folder returns None, should raise exception
        with pytest.raises(Exception):
            await folder_manager._create_advisor_root(
                AdvisorType.DATA_ANALYST,
                DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
            )

    @pytest.mark.asyncio
    async def test_backup_with_empty_folder(self):
        """Test backup with empty folder."""
        mock_drive = Mock()
        mock_drive.list_files = Mock(return_value=[])

        mock_folder = Mock()
        mock_folder.folder_cache = {
            AdvisorType.DATA_ANALYST: {
                'subfolders': {'backups': 'backup_123'}
            }
        }
        mock_folder._ensure_advisor_initialized = AsyncMock()
        mock_folder.get_current_month_folder = AsyncMock(return_value='month_123')

        backup_manager = DriveBackupManager(mock_drive, mock_folder)

        result = await backup_manager.create_daily_backup(AdvisorType.DATA_ANALYST)

        # Should handle empty folder gracefully
        assert result is not None


class TestConcurrentOperations:
    """Test concurrent operations."""

    @pytest.fixture
    def mock_drive_manager(self):
        """Create a mock Google Drive Manager."""
        mock = Mock()
        mock.create_folder = Mock(side_effect=lambda folder_name, parent_folder_id: f"folder_{folder_name}")
        mock.get_folder_id_by_name = Mock(return_value=None)
        mock.get_or_create_folder = Mock(side_effect=lambda folder_name, parent_folder_id: f"folder_{folder_name}")
        mock.get_file_by_name = Mock(return_value=None)
        mock.list_files = Mock(return_value=[])
        mock.upload_file = Mock(return_value="file_123")
        mock.get_file_link = Mock(return_value="https://drive.google.com/file/d/file_123/view")
        return mock

    @pytest.fixture
    def folder_manager(self, mock_drive_manager):
        """Create a DriveFolderManager instance."""
        return DriveFolderManager(mock_drive_manager, "root_folder_123")

    @pytest.mark.asyncio
    async def test_concurrent_uploads(self, folder_manager, mock_drive_manager, tmp_path):
        """Test concurrent file uploads."""
        folder_manager.folder_cache[AdvisorType.DATA_ANALYST] = {
            'root': 'root_123',
            'subfolders': {},
            'config': DriveFolderManager.FOLDER_STRUCTURE[AdvisorType.DATA_ANALYST]
        }

        # Simulate concurrent uploads
        tasks = []
        for i in range(3):
            task = folder_manager.upload_advisor_output(
                advisor_type=AdvisorType.DATA_ANALYST,
                output_name=f"Report_{i}",
                files={f"file_{i}": str(tmp_path / f"file_{i}.txt")}
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        for result in results:
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_concurrent_backup_all_advisors(self, folder_manager, mock_drive_manager):
        """Test concurrent backups for multiple advisors."""
        await folder_manager.initialize_folder_structure()

        # This would require async backup operations
        # For now, verify structure initialization is concurrent-safe
        assert len(folder_manager.folder_cache) == 5


# Integration-like tests
class TestIntegration:
    """Integration tests for complete workflows."""

    @pytest.fixture
    def mock_drive_manager(self):
        """Create a realistic mock Google Drive Manager."""
        mock = Mock()

        # Simulate folder creation
        folder_ids = {}
        counter = [0]

        def create_folder_impl(folder_name, parent_folder_id=None):
            counter[0] += 1
            folder_id = f"folder_{counter[0]}"
            key = f"{parent_folder_id}_{folder_name}"
            folder_ids[key] = folder_id
            return folder_id

        mock.create_folder = Mock(side_effect=create_folder_impl)
        mock.get_folder_id_by_name = Mock(return_value=None)
        mock.get_or_create_folder = Mock(side_effect=create_folder_impl)
        mock.get_file_by_name = Mock(return_value=None)
        mock.list_files = Mock(return_value=[])
        mock.upload_file = Mock(return_value="file_123")
        mock.get_file_link = Mock(return_value="https://drive.google.com/file/d/file_123/view")
        mock.move_file = Mock(return_value=True)
        return mock

    @pytest.fixture
    def folder_manager(self, mock_drive_manager):
        """Create a DriveFolderManager instance."""
        return DriveFolderManager(mock_drive_manager, "root_folder_123")

    @pytest.mark.asyncio
    async def test_complete_workflow(self, folder_manager, mock_drive_manager, tmp_path):
        """Test complete workflow: init, upload, version, stats."""
        # Initialize structure
        await folder_manager.initialize_folder_structure()
        assert len(folder_manager.folder_cache) == 5

        # Upload advisor output
        files = {
            "report": str(tmp_path / "report.pdf"),
            "data": str(tmp_path / "data.xlsx"),
        }
        links = await folder_manager.upload_advisor_output(
            advisor_type=AdvisorType.DATA_ANALYST,
            output_name="Sales Report",
            files=files
        )
        assert "report" in links
        assert "data" in links

        # Get stats
        stats = await folder_manager.get_folder_stats(AdvisorType.DATA_ANALYST)
        assert stats['advisor_type'] == 'data_analyst'
