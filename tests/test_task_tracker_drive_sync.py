"""TaskTracker.load_from_drive must not stage its download at a fixed path.

The download destination used to be the literal string ``/tmp/tasks_sync.csv``:
shared between every process on the host, pre-creatable by any local user, and
non-existent on Windows. These tests pin the replacement behaviour — a unique
temporary file per call, handed to the parser and then removed.
"""

import os
from unittest.mock import Mock, patch

from ai_assistant.integrations.task_tracker import TaskTracker

CSV_BODY = (
    "ID,Title,Owner,Deadline,Status,Priority,Meeting\n"
    '"t-1","Write the report","@burak","","pending","3",""\n'
)

FIXED_PATH = "/tmp/tasks_sync.csv"


class DriveSyncRun:
    """One `load_from_drive` call, with everything it touched recorded."""

    def __init__(self):
        self.download_destinations = []
        self.parsed_paths = []
        self.parsed_contents = []
        self.result = None


def _exercise_load(tmp_path, run, download_succeeds=True):
    """Drive `load_from_drive` against a stubbed Drive client."""
    tracker = TaskTracker(state_dir=str(tmp_path / "state"))

    def download_file(file_id, destination):
        run.download_destinations.append(destination)
        if not download_succeeds:
            return False
        with open(destination, "w") as handle:
            handle.write(CSV_BODY)
        return True

    manager = Mock()
    manager.list_files = Mock(return_value=[{"id": "f1", "name": "tasks_2026.csv"}])
    manager.download_file = Mock(side_effect=download_file)

    def record_parse(path):
        # Read it here, while the call is still in flight: this is the only
        # moment the temporary file is supposed to exist.
        run.parsed_paths.append(path)
        with open(path) as handle:
            run.parsed_contents.append(handle.read())

    tracker._load_from_csv = record_parse

    with patch(
        "ai_assistant.integrations.google_drive_manager.GoogleDriveManager",
        return_value=manager,
    ):
        run.result = tracker.load_from_drive("folder_123")

    return tracker


def test_downloaded_csv_is_handed_to_the_parser(tmp_path):
    run = DriveSyncRun()

    _exercise_load(tmp_path, run)

    assert run.result is True
    assert run.parsed_paths == run.download_destinations
    assert run.parsed_contents == [CSV_BODY]


def test_download_destination_is_not_the_old_fixed_path(tmp_path):
    run = DriveSyncRun()

    _exercise_load(tmp_path, run)

    assert len(run.download_destinations) == 1
    assert run.download_destinations[0] != FIXED_PATH


def test_two_loads_use_different_destinations(tmp_path):
    """Concurrent syncs must not be able to clobber each other's download."""
    run = DriveSyncRun()

    _exercise_load(tmp_path, run)
    _exercise_load(tmp_path, run)

    assert len(run.download_destinations) == 2
    assert run.download_destinations[0] != run.download_destinations[1]


def test_temporary_file_is_removed_after_a_successful_load(tmp_path):
    run = DriveSyncRun()

    _exercise_load(tmp_path, run)

    assert not os.path.exists(run.download_destinations[0])


def test_temporary_file_is_removed_when_the_download_fails(tmp_path):
    run = DriveSyncRun()

    _exercise_load(tmp_path, run, download_succeeds=False)

    assert run.parsed_paths == []
    assert not os.path.exists(run.download_destinations[0])
