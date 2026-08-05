# Google Drive Folder Structure & Auto-Backup System

## Overview

The Drive Folder Structure system provides automated, hierarchical organization of advisor outputs on Google Drive, with built-in backup, archiving, and versioning capabilities.

**Key Features:**
- Automatic folder hierarchy for each advisor type
- Date-based organization (YYYY-MM format)
- File versioning (v1, v2, v3...)
- Daily backup snapshots
- Monthly archive creation
- Automatic cleanup of old files
- Concurrent upload support

---

## Folder Hierarchy

### Structure

All advisor outputs are organized under a single root folder with the following structure:

```
AI-Executive-Assistant/
├── Data Analysis/
│   ├── 2026-08/
│   │   ├── Sales Analysis 2026-08-05/
│   │   │   ├── report_20260805_120000.pdf
│   │   │   ├── data_20260805_120000.xlsx
│   │   │   └── summary_20260805_120000.txt
│   │   └── Market Report 2026-08-03/
│   │       └── market_analysis.pdf
│   ├── 2026-07/
│   ├── active/
│   ├── archive/
│   ├── backups/
│   └── templates/
│
├── Meeting Notes/
│   ├── 2026-08/
│   ├── 2026-07/
│   ├── active/
│   ├── archive/
│   └── backups/
│
├── LinkedIn Coach/
│   ├── 2026-08/
│   ├── profile_analysis/
│   ├── content_calendar/
│   ├── engagement_reports/
│   ├── archive/
│   └── backups/
│
├── Social Media Analysis/
│   ├── linkedin/
│   ├── instagram/
│   ├── twitter/
│   └── backups/
│
└── Personal Assistant/
    ├── daily_briefs/
    ├── tasks/
    ├── goals/
    ├── archive/
    └── backups/
```

### Advisor Types

| Advisor Type | Display Name | Subfolders |
|---|---|---|
| MEETING_NOTES | Meeting Notes | active, archive, backups |
| DATA_ANALYST | Data Analysis | active, archive, backups, templates |
| LINKEDIN_COACH | LinkedIn Coach | profile_analysis, content_calendar, engagement_reports, backups |
| SOCIAL_MEDIA_COACH | Social Media Analysis | linkedin, instagram, twitter, backups |
| PERSONAL_ASSISTANT | Personal Assistant | daily_briefs, tasks, goals, backups |

---

## How Files Are Organized

### 1. Date-Based Organization

Files are organized by month (YYYY-MM format). Each month automatically gets a new folder:
- `2026-08/` (August 2026)
- `2026-07/` (July 2026)
- etc.

### 2. Output Folders

Within each month folder, outputs are organized in descriptive folders:
```
Data Analysis/2026-08/Sales Analysis 2026-08-05/
├── report_20260805_120000.pdf
├── data_20260805_120000.xlsx
└── summary_20260805_120000.txt
```

**Naming Convention:**
- Folder: `{OutputName}` (e.g., "Sales Analysis 2026-08-05")
- Files: `{file_key}_{YYYYMMDD_HHMMSS}.{ext}`

### 3. File Versioning

When creating multiple versions of the same analysis:
- v1: `Report_v1.pdf`
- v2: `Report_v2.pdf`
- v3: `Report_v3.pdf`

Versions are stored in the same month folder for easy comparison.

### 4. Timestamps

All uploaded files include timestamps to avoid collisions:
- Format: `YYYYMMDD_HHMMSS`
- Example: `report_20260805_143025.pdf`

---

## Backup Strategy

### Daily Backups

**When:** Every day at 23:00 UTC (can be customized)

**What:** Snapshots of the current month's files

**Where:** `{AdvisorName}/backups/YYYY-MM-DD/`

**Example:**
```
Data Analysis/backups/
├── 2026-08-05/
│   ├── report_20260805_120000.pdf_backup
│   ├── data_20260805_120000.xlsx_backup
│   └── summary_20260805_120000.txt_backup
├── 2026-08-04/
│   └── ...
└── 2026-08-03/
    └── ...
```

**Retention:** By default, daily backups are kept for 7 days. Older backups are automatically deleted.

### Monthly Archives

**When:** Last day of each month at 23:30 UTC

**What:** Complete snapshot of all files from the month

**Where:** `{AdvisorName}/archive/{YYYY-MM}_archive/`

**Purpose:** Long-term preservation of monthly outputs for historical reference

**Example:**
```
Data Analysis/archive/
├── 2026-08_archive/
│   ├── Sales Analysis 2026-08-05/
│   │   ├── report_20260805_120000.pdf
│   │   └── data_20260805_120000.xlsx
│   └── Market Report 2026-08-03/
│       └── market_analysis.pdf
├── 2026-07_archive/
└── 2026-06_archive/
```

### Automatic File Archiving

**When:** 1st of each month at 23:00 UTC

**What:** Moves month folders older than 30 days to archive

**Rule:** Files in folders older than `DRIVE_ARCHIVE_OLDER_THAN_DAYS` are moved from:
- `Data Analysis/2026-01/` → `Data Analysis/archive/`

**Configuration:**
```env
DRIVE_ARCHIVE_OLDER_THAN_DAYS=30  # Default
```

---

## Restoration from Backups

### Restore from Daily Backup

1. Navigate to `{AdvisorName}/backups/{YYYY-MM-DD}/`
2. Find the backup files you need
3. Copy or download the backup file
4. Rename (remove `_backup` suffix if needed)
5. Move to current location in month folder

### Restore from Monthly Archive

1. Navigate to `{AdvisorName}/archive/{YYYY-MM}_archive/`
2. Find the file or folder you need
3. Copy to the desired location
4. Works best for restoring entire month's worth of data

### Restore from Archived Month Folder

If a month folder was automatically archived:
1. Navigate to `{AdvisorName}/archive/`
2. Find the month folder (e.g., `2026-01/`)
3. Browse to the file you need
4. Copy or download

---

## Version Tracking

### Creating Versions

When you need to preserve multiple iterations of the same file:

```python
from ai_assistant.integrations.drive_folder_manager import DriveFolderManager, AdvisorType

manager = DriveFolderManager(drive_manager, root_folder_id)

# First version
link_v1 = await manager.create_version(
    advisor_type=AdvisorType.DATA_ANALYST,
    output_name="Sales Report",
    file_path="/tmp/report_v1.pdf"
)

# Second version
link_v2 = await manager.create_version(
    advisor_type=AdvisorType.DATA_ANALYST,
    output_name="Sales Report",
    file_path="/tmp/report_v2.pdf"
)
```

**Result:**
```
Data Analysis/2026-08/
├── Sales Report_v1.pdf
└── Sales Report_v2.pdf
```

### Viewing Version History

1. Navigate to the month folder
2. Look for files with `_v{N}` suffix
3. Versions are stored in the same folder for easy comparison

---

## Automated Workflows

### GitHub Actions Integration

The system runs automated backup tasks via GitHub Actions:

#### Daily Backup Job
- **Trigger:** 23:00 UTC every day
- **Action:** Creates daily backup for all advisors
- **Config:** `drive-backup-scheduler.yml`

#### Monthly Archive Job
- **Trigger:** 23:30 UTC on days 28-31 (catches month end)
- **Action:** Creates monthly archives
- **Config:** `drive-backup-scheduler.yml`

#### Cleanup Job
- **Trigger:** 23:00 UTC on the 1st of each month
- **Actions:**
  - Archive files older than 30 days
  - Delete backup snapshots older than 7 days
- **Config:** `drive-backup-scheduler.yml`

### Environment Variables for CI/CD

Set these secrets in your GitHub repository:

```
GOOGLE_DRIVE_CREDENTIALS_JSON    # Service account JSON or OAuth credentials
GOOGLE_DRIVE_ROOT_FOLDER_ID      # Root folder ID
```

And these variables in `.env`:

```env
DRIVE_BACKUP_ENABLED=true
DRIVE_CREATE_DAILY_BACKUPS=true
DRIVE_CREATE_MONTHLY_ARCHIVES=true
DRIVE_ARCHIVE_OLDER_THAN_DAYS=30
DRIVE_BACKUP_RETENTION_DAYS=7
```

---

## Usage Examples

### Initialize Folder Structure

```python
from ai_assistant.integrations.drive_folder_manager import DriveFolderManager
from ai_assistant.integrations.google_drive_manager import GoogleDriveManager

drive_manager = GoogleDriveManager()
folder_manager = DriveFolderManager(drive_manager, "root_folder_id_here")

# Initialize all advisor folders
await folder_manager.initialize_folder_structure()
```

### Upload Advisor Output

```python
from ai_assistant.integrations.drive_folder_manager import AdvisorType

# Upload multiple files
files = {
    "report": "/tmp/report.pdf",
    "data": "/tmp/data.xlsx",
    "summary": "/tmp/summary.txt"
}

links = await folder_manager.upload_advisor_output(
    advisor_type=AdvisorType.DATA_ANALYST,
    output_name="Sales Analysis 2026-08-05",
    files=files
)

# Result: links = {
#   "report": "https://drive.google.com/file/d/...",
#   "data": "https://drive.google.com/file/d/...",
#   "summary": "https://drive.google.com/file/d/..."
# }
```

### Create Versioned Copy

```python
# Automatically creates v1, v2, v3... in the same month folder
link = await folder_manager.create_version(
    advisor_type=AdvisorType.DATA_ANALYST,
    output_name="Sales Report",
    file_path="/tmp/report.pdf"
)
```

### Get Folder Statistics

```python
stats = await folder_manager.get_folder_stats(AdvisorType.DATA_ANALYST)

print(f"Total files: {stats['total_files']}")
print(f"Total size: {stats['total_size_bytes']} bytes")
print(f"Created: {stats['created_at']}")
```

### Manual Backup Operations

```python
from ai_assistant.integrations.drive_folder_manager import DriveBackupManager

backup_manager = DriveBackupManager(drive_manager, folder_manager)

# Create daily backup
await backup_manager.create_daily_backup(AdvisorType.DATA_ANALYST)

# Create monthly archive
await backup_manager.create_monthly_archive(AdvisorType.DATA_ANALYST)

# Archive files older than 60 days
await backup_manager.archive_old_files(
    AdvisorType.DATA_ANALYST,
    older_than_days=60
)

# Clean up backup snapshots older than 14 days
await backup_manager.cleanup_old_backups(
    AdvisorType.DATA_ANALYST,
    keep_days=14
)
```

---

## Integration with Advisors

### Data Analyst Example

```python
from ai_assistant.advisors.data_analyst import DataAnalyst
from ai_assistant.integrations.drive_folder_manager import DriveFolderManager, AdvisorType

class DataAnalyst(BaseAdvisor):
    def __init__(self, ...):
        # ... existing init code ...
        self.folder_manager = DriveFolderManager(drive_manager, root_folder_id)
    
    async def generate_report(self, data: dict):
        # Generate report files
        report_pdf = self._write_pdf(data)
        report_xlsx = self._write_xlsx(data)
        report_txt = self._write_txt(data)
        
        # Save to Drive
        files = {
            "report": report_pdf,
            "data": report_xlsx,
            "summary": report_txt
        }
        
        links = await self.folder_manager.upload_advisor_output(
            advisor_type=AdvisorType.DATA_ANALYST,
            output_name=f"Analysis_{data['date']}",
            files=files
        )
        
        return {
            "status": "success",
            "drive_links": links,
            "timestamp": datetime.now().isoformat()
        }
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | - | Root folder ID (required) |
| `DRIVE_BACKUP_ENABLED` | true | Enable backup system |
| `DRIVE_CREATE_DAILY_BACKUPS` | true | Create daily backups |
| `DRIVE_CREATE_MONTHLY_ARCHIVES` | true | Create monthly archives |
| `DRIVE_ARCHIVE_OLDER_THAN_DAYS` | 30 | Archive files older than N days |
| `DRIVE_BACKUP_RETENTION_DAYS` | 7 | Keep daily backups for N days |

### Folder Structure Config

The `FOLDER_STRUCTURE` dictionary in `drive_folder_manager.py` defines:
- Advisor type mappings
- Display names
- Subfolders per advisor
- Date formats

Edit `FOLDER_STRUCTURE` to customize folder organization.

---

## Performance Considerations

### Large Folder Handling

When dealing with large numbers of files:
- Pagination is built in for file listing
- Caching reduces repeated API calls
- Concurrent uploads are supported

### API Rate Limits

The system respects Google Drive API rate limits:
- Batches operations where possible
- Implements exponential backoff for retries
- Logs all operations for monitoring

### Concurrent Operations

Safe for concurrent operations:
```python
import asyncio

tasks = []
for i in range(10):
    task = folder_manager.upload_advisor_output(...)
    tasks.append(task)

results = await asyncio.gather(*tasks)
```

---

## Troubleshooting

### Missing Root Folder

**Error:** `GOOGLE_DRIVE_ROOT_FOLDER_ID not configured`

**Solution:**
1. Get your root folder ID from Drive URL
2. Set in `.env`: `GOOGLE_DRIVE_ROOT_FOLDER_ID=your_id_here`
3. Restart the application

### Backup Not Running

**Error:** Backups missing on expected schedule

**Solutions:**
1. Check GitHub Actions status: Settings > Actions
2. Verify secrets are set: `GOOGLE_DRIVE_CREDENTIALS_JSON`, `GOOGLE_DRIVE_ROOT_FOLDER_ID`
3. Check logs in Actions workflow
4. Verify `.env` has `DRIVE_BACKUP_ENABLED=true`

### Folder Permissions

**Error:** `403 Forbidden` when accessing backups

**Solution:**
1. Ensure the service account/OAuth token has Drive access
2. Verify folder permissions: Share > Check access
3. Re-authenticate: `python -m ai_assistant.integrations.google_auth`

### Version Conflicts

**Issue:** Duplicate version numbers

**Solution:**
1. Versions are numbered sequentially in each month folder
2. If conflicts occur, check for files with same name
3. Manually rename duplicates or move to archive

---

## Best Practices

1. **Naming Conventions**
   - Use descriptive output names: "Sales Analysis 2026-08-05"
   - Keep file names simple and meaningful
   - Use consistent date formats (YYYY-MM-DD)

2. **Organization**
   - Create clear output folders for each analysis
   - Group related files together
   - Use versioning for iterative work

3. **Backups**
   - Rely on daily backups for short-term recovery (7 days)
   - Use monthly archives for long-term retention
   - Verify important backups monthly

4. **Cleanup**
   - Archive old files automatically (30+ days)
   - Clean up backup snapshots regularly (7 days)
   - Monitor storage usage periodically

5. **Security**
   - Never commit `GOOGLE_DRIVE_CREDENTIALS_JSON` to git
   - Use GitHub Secrets for CI/CD credentials
   - Limit share permissions on sensitive folders
   - Audit access logs monthly

---

## Related Files

- **Main Module:** `src/ai_assistant/integrations/drive_folder_manager.py`
- **CLI Scheduler:** `src/ai_assistant/integrations/drive_backup_scheduler.py`
- **Workflow:** `.github/workflows/drive-backup-scheduler.yml`
- **Tests:** `tests/test_drive_folder_manager.py`
- **Config:** `.env.example` (DRIVE_* variables)

---

## Support & Feedback

For issues or improvements:
1. Check logs in GitHub Actions
2. Review error messages in application logs
3. Refer to test suite for usage examples
4. Update environment variables as needed
