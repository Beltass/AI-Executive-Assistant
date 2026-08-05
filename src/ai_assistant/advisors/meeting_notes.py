"""Meeting Notes Agent - Transcription, analysis, and reporting.

Handles:
- Audio transcription (Gemini, audio sent inline)
- Meeting analysis with LLM
- Action item extraction
- Report generation (PDF, Google Doc, Excel)
- Task creation and tracking
- Deadline reminders via Slack
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from . import Advisor, Briefing
from ..integrations import llm
from ..integrations.google_drive_manager import GoogleDriveManager
from ..integrations.task_tracker import Task, TaskTracker, TaskStatus
from ..integrations import STATUS_OK, STATUS_FAILED, STATUS_SKIPPED

logger = logging.getLogger(__name__)

#: What the model is told to do with a recording. Verbatim, in the language
#: actually spoken — a meeting held in Turkish must come back in Turkish, not
#: translated, because every downstream step (action items, owners, deadlines)
#: reads names and dates straight out of these words.
TRANSCRIPTION_SYSTEM_PROMPT = (
    "Sen bir toplantı kaydı deşifre uzmanısın. Sana verilen ses kaydını "
    "kelimesi kelimesine yazıya dök.\n"
    "Kurallar:\n"
    "- Kaydın dilini KORU. Türkçe konuşulduysa Türkçe yaz, çevirme.\n"
    "- Konuşmacıları ayırt edebiliyorsan her replikten önce 'Konuşmacı 1:' "
    "gibi bir etiket koy.\n"
    "- Özetleme, yorum ekleme, düzeltme yapma; sadece söyleneni yaz.\n"
    "- Anlaşılmayan yerler için [anlaşılmıyor] yaz.\n"
    "- Sadece deşifre metnini döndür, başka hiçbir açıklama ekleme."
)

TRANSCRIPTION_USER_PROMPT = "Bu toplantı kaydını deşifre et."

#: Transcripts are long: an hour of speech is well past the default 8k output
#: budget, and a truncated transcript silently loses the action items at the
#: end of a meeting — exactly the part this whole pipeline exists for.
DEFAULT_TRANSCRIPTION_MAX_OUTPUT_TOKENS = 32768


@dataclass
class ActionItem:
    """Represents an action item from a meeting.

    Attributes:
        id: Unique identifier
        description: What needs to be done
        owner: Person responsible
        deadline: Due date
        priority: Priority level (1-5)
        status: Current status
        created_at: When the item was created
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    owner: str = ""
    deadline: Optional[datetime] = None
    priority: int = 3
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CompetitiveAction:
    """Represents a competitive action identified in the meeting.

    Attributes:
        id: Unique identifier
        description: What the competitor is doing
        impact: Potential impact on our business
        urgency: How urgent is our response
        recommended_action: What we should do about it
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    impact: str = "medium"
    urgency: str = "medium"
    recommended_action: str = ""


@dataclass
class MeetingNotes:
    """Structured meeting notes with analysis.

    Attributes:
        meeting_id: Unique meeting identifier
        title: Meeting title
        date: When the meeting occurred
        attendees: List of participants
        audio_file_url: URL/path to audio file
        transcript_text: Speech-to-text output
        summary: High-level summary
        findings: Key findings from the meeting
        action_items: Tasks to be completed
        competitive_actions: Competitive intelligence
        next_steps: Follow-up actions
        drive_folder_id: Where this meeting's docs are stored
        created_at: When notes were created
    """

    meeting_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attendees: List[str] = field(default_factory=list)
    audio_file_url: str = ""

    transcript_text: str = ""
    summary: str = ""
    findings: List[str] = field(default_factory=list)
    action_items: List[ActionItem] = field(default_factory=list)
    competitive_actions: List[CompetitiveAction] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)

    drive_folder_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'meeting_id': self.meeting_id,
            'title': self.title,
            'date': self.date.isoformat(),
            'attendees': self.attendees,
            'audio_file_url': self.audio_file_url,
            'transcript_text': self.transcript_text,
            'summary': self.summary,
            'findings': self.findings,
            'action_items': [
                {
                    'id': ai.id,
                    'description': ai.description,
                    'owner': ai.owner,
                    'deadline': ai.deadline.isoformat() if ai.deadline else None,
                    'priority': ai.priority,
                    'status': ai.status,
                    'created_at': ai.created_at.isoformat(),
                }
                for ai in self.action_items
            ],
            'competitive_actions': [
                {
                    'id': ca.id,
                    'description': ca.description,
                    'impact': ca.impact,
                    'urgency': ca.urgency,
                    'recommended_action': ca.recommended_action,
                }
                for ca in self.competitive_actions
            ],
            'next_steps': self.next_steps,
            'drive_folder_id': self.drive_folder_id,
            'created_at': self.created_at.isoformat(),
        }


class MeetingNotesAgent(Advisor):
    """Agent for managing meeting notes, transcription, and action tracking.

    Key capabilities:
    - Transcribe audio files (mock implementation)
    - Analyze meeting transcript with LLM
    - Extract action items with owners and deadlines
    - Identify competitive intelligence
    - Generate reports (PDF, Google Doc, Excel)
    - Track action items with reminders
    """

    key = "meeting_notes"
    title = "Toplantı Notları"
    private = True
    incremental_source = True

    def __init__(self):
        """Initialize the Meeting Notes Agent."""
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.drive_manager = GoogleDriveManager()
        self.task_tracker = TaskTracker()
        self.state_dir = Path(".assistant_state")
        self.state_dir.mkdir(exist_ok=True)
        self.meetings_file = self.state_dir / "meetings.json"
        # Why the last transcript came back empty (skipped vs. failed), for
        # callers to log. ``None`` means "nothing has gone wrong yet".
        self.last_transcription_error: Optional[str] = None

    def _generate(self) -> Briefing:
        """Generate meeting notes briefing.

        Returns:
            Briefing with status and text
        """
        try:
            if not os.getenv("MEETING_NOTES_ENABLED", "true").lower() == "true":
                return self.skipped("toplantı notları aracı devre dışı")

            # Get upcoming reminders
            overdue_tasks = self.task_tracker.get_overdue_tasks()
            upcoming_tasks = self.task_tracker.get_upcoming_tasks(days=1)

            if not overdue_tasks and not upcoming_tasks:
                return self.nothing_new("toplantı görevlerinde güncelleme yok")

            text_parts = []

            if overdue_tasks:
                text_parts.append(f"⚠️ **Geçen Deadline ({len(overdue_tasks)}):**")
                for task in overdue_tasks:
                    text_parts.append(
                        f"- {task.title} (Sorumlu: {task.owner}, "
                        f"Deadline: {task.deadline.strftime('%Y-%m-%d') if task.deadline else 'N/A'})"
                    )
                text_parts.append("")

            if upcoming_tasks:
                text_parts.append(f"📅 **Yarın Deadline ({len(upcoming_tasks)}):**")
                for task in upcoming_tasks:
                    text_parts.append(
                        f"- {task.title} (Sorumlu: {task.owner}, "
                        f"Deadline: {task.deadline.strftime('%Y-%m-%d') if task.deadline else 'N/A'})"
                    )

            text = "\n".join(text_parts)
            return self.ok(text)

        except Exception as e:
            self.logger.error(f"Meeting notes generation failed: {e}")
            return self.failed(f"toplantı notları hatası: {e}")

    @staticmethod
    def _transcription_max_output_tokens() -> int:
        """Output budget for one transcript, read at call time."""
        try:
            tokens = int(
                os.getenv("MEETING_TRANSCRIPTION_MAX_OUTPUT_TOKENS")
                or DEFAULT_TRANSCRIPTION_MAX_OUTPUT_TOKENS
            )
        except ValueError:
            tokens = DEFAULT_TRANSCRIPTION_MAX_OUTPUT_TOKENS
        return tokens if tokens > 0 else DEFAULT_TRANSCRIPTION_MAX_OUTPUT_TOKENS

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/mpeg",
        source_label: str = "",
        thinking_budget: Optional[int] = None,
    ) -> str:
        """Transcribe a recording with Gemini.

        Takes BYTES, not a URL: the recording lives behind Gmail/Drive
        credentials this advisor does not hold, so downloading is the
        poller's job (``fetch_audio_bytes``) and transcription is this one's.

        Returns ``""`` when no transcript could be produced — never a
        placeholder. Anything downstream that treats an empty string as "keep
        going" would otherwise file action items invented out of thin air.
        The reason is left on :attr:`last_transcription_error` so the caller
        can log WHY (skipped for lack of a key vs. a failed request).

        Args:
            audio_bytes: Raw audio file contents.
            mime_type: Concrete audio MIME type, e.g. ``audio/mpeg``.
            source_label: Where the audio came from; logging only.
            thinking_budget: Passed through to Gemini; ``None`` leaves the
                model's own default alone.

        Returns:
            Transcript text, or ``""`` when transcription was skipped or failed.

        Raises:
            TypeError: when handed a URL/path instead of bytes.
        """
        self.last_transcription_error = None
        label = source_label or "audio"

        if isinstance(audio_bytes, str):
            raise TypeError(
                "transcribe_audio() takes audio BYTES, not a URL; download the "
                "recording first with "
                "ai_assistant.integrations.meeting_notes_poller.fetch_audio_bytes()"
            )

        if not audio_bytes:
            self.last_transcription_error = f"boş ses verisi ({label})"
            self.logger.error(self.last_transcription_error)
            return ""

        if not llm.is_configured():
            # Skipped, not failed: nothing is broken, a key is simply absent.
            self.last_transcription_error = (
                "transkripsiyon atlandı — missing env var(s): GEMINI_API_KEY "
                "or OPENAI_API_KEY"
            )
            self.logger.warning(self.last_transcription_error)
            return ""

        self.logger.info(
            f"Transcribing {len(audio_bytes)} bytes of {mime_type} from {label}"
        )

        try:
            # Off the event loop: this is a minutes-long blocking HTTP call.
            transcript = await asyncio.to_thread(
                llm.generate_from_audio,
                audio_bytes,
                mime_type,
                TRANSCRIPTION_SYSTEM_PROMPT,
                TRANSCRIPTION_USER_PROMPT,
                max_output_tokens=self._transcription_max_output_tokens(),
                thinking_budget=thinking_budget,
            )
        except Exception as e:
            self.last_transcription_error = f"transkripsiyon başarısız ({label}): {e}"
            self.logger.error(self.last_transcription_error)
            return ""

        transcript = (transcript or "").strip()
        if not transcript:
            self.last_transcription_error = (
                f"model boş transkript döndürdü ({label})"
            )
            self.logger.error(self.last_transcription_error)
            return ""

        self.logger.info(f"Transcribed {label}: {len(transcript)} characters")
        return transcript

    async def analyze_meeting(
        self,
        transcript: str,
        meeting_title: str = "Toplantı",
        attendees: List[str] = None,
    ) -> MeetingNotes:
        """Analyze meeting transcript with LLM.

        Extracts:
        - Key findings
        - Action items with owners and deadlines
        - Competitive intelligence
        - Next steps

        Args:
            transcript: Meeting transcript text
            meeting_title: Title of the meeting
            attendees: List of meeting attendees

        Returns:
            MeetingNotes object with analysis
        """
        try:
            self.logger.info(f"Analyzing meeting: {meeting_title}")

            attendees = attendees or ["Unknown"]
            meeting_notes = MeetingNotes(
                title=meeting_title,
                attendees=attendees,
                transcript_text=transcript,
            )

            # Mock implementation - in production would call LLM
            # For now, extract key phrases and generate mock analysis
            meeting_notes.summary = "Toplantıda Q3 stratejisi, ürün lansmanı ve rakip analizi tartışıldı."
            meeting_notes.findings = [
                "Pazarlama bütçesi %25 artırılmalı",
                "Yeni ürün lansmanı 2 hafta içinde yapılmalı",
                "Rakip XYZ önemli bir özellik çıkardı",
            ]
            meeting_notes.action_items = [
                ActionItem(
                    description="Pazarlama bütçesi planını hazırla",
                    owner="John",
                    deadline=datetime.now(timezone.utc) + timedelta(days=3),
                    priority=4,
                ),
                ActionItem(
                    description="Teknik specifikasyonları dokümante et",
                    owner="Sarah",
                    deadline=datetime.now(timezone.utc) + timedelta(days=5),
                    priority=4,
                ),
                ActionItem(
                    description="Yeni özelliği geliştir",
                    owner="Mike",
                    deadline=datetime.now(timezone.utc) + timedelta(days=14),
                    priority=5,
                ),
            ]
            meeting_notes.competitive_actions = [
                CompetitiveAction(
                    description="XYZ şirketi yeni AI özelliğini piyasaya sürdü",
                    impact="high",
                    urgency="high",
                    recommended_action="Benzer özelliği hızlıca geliştir",
                ),
            ]
            meeting_notes.next_steps = [
                "Pazarlama planını önümüzdeki pazartesi sunmak",
                "Ürün lansmanı için geri sayımı başlatmak",
            ]

            self.logger.info(f"Meeting analysis completed: {len(meeting_notes.action_items)} action items")
            return meeting_notes

        except Exception as e:
            self.logger.error(f"Meeting analysis failed: {e}")
            return MeetingNotes()

    async def generate_report(self, meeting_notes: MeetingNotes) -> Dict[str, str]:
        """Generate meeting reports (PDF, Google Doc, Excel).

        Args:
            meeting_notes: MeetingNotes object

        Returns:
            Dictionary with file IDs/URLs
        """
        try:
            self.logger.info(f"Generating reports for meeting: {meeting_notes.title}")

            # Create or get meeting folder in Drive
            meeting_folder_name = f"Meeting_{meeting_notes.meeting_id}_{meeting_notes.date.strftime('%Y%m%d')}"
            meeting_folder_id = self.drive_manager.get_or_create_folder(
                meeting_folder_name,
                parent_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID"),
            )

            if meeting_folder_id:
                meeting_notes.drive_folder_id = meeting_folder_id

            reports = {}

            # Generate and upload markdown summary
            summary_doc_id = await self._generate_summary_doc(meeting_notes, meeting_folder_id)
            if summary_doc_id:
                reports['summary_doc'] = summary_doc_id
                self.logger.info(f"Created summary doc: {summary_doc_id}")

            # Generate and upload task list
            tasks_doc_id = await self._generate_tasks_doc(meeting_notes, meeting_folder_id)
            if tasks_doc_id:
                reports['tasks_doc'] = tasks_doc_id
                self.logger.info(f"Created tasks doc: {tasks_doc_id}")

            return reports

        except Exception as e:
            self.logger.error(f"Report generation failed: {e}")
            return {}

    async def _generate_summary_doc(
        self,
        meeting_notes: MeetingNotes,
        folder_id: str,
    ) -> Optional[str]:
        """Generate summary document."""
        try:
            content = f"""# {meeting_notes.title}

**Tarih:** {meeting_notes.date.strftime('%Y-%m-%d %H:%M')}

**Katılımcılar:** {', '.join(meeting_notes.attendees)}

## Özet

{meeting_notes.summary}

## Bulgular

"""
            for finding in meeting_notes.findings:
                content += f"- {finding}\n"

            content += "\n## Rakip Aksiyon Öğeleri\n\n"
            for ca in meeting_notes.competitive_actions:
                content += f"- **{ca.description}** (Aciliyet: {ca.urgency})\n"
                content += f"  Tavsiye: {ca.recommended_action}\n\n"

            content += "\n## Sonraki Adımlar\n\n"
            for step in meeting_notes.next_steps:
                content += f"- {step}\n"

            doc_id = self.drive_manager.create_google_doc(
                f"Meeting_Summary_{meeting_notes.meeting_id}",
                folder_id,
                content,
            )
            return doc_id

        except Exception as e:
            self.logger.error(f"Failed to generate summary doc: {e}")
            return None

    async def _generate_tasks_doc(
        self,
        meeting_notes: MeetingNotes,
        folder_id: str,
    ) -> Optional[str]:
        """Generate tasks document."""
        try:
            content = f"""# Aksiyon Öğeleri - {meeting_notes.title}

| Görev | Sorumlu | Deadline | Öncelik | Durum |
|-------|---------|----------|---------|-------|
"""
            for item in meeting_notes.action_items:
                deadline_str = item.deadline.strftime('%Y-%m-%d') if item.deadline else 'TBD'
                content += f"| {item.description} | {item.owner} | {deadline_str} | {item.priority} | {item.status} |\n"

            doc_id = self.drive_manager.create_google_doc(
                f"ActionItems_{meeting_notes.meeting_id}",
                folder_id,
                content,
            )
            return doc_id

        except Exception as e:
            self.logger.error(f"Failed to generate tasks doc: {e}")
            return None

    async def create_tasks_in_tracker(
        self,
        action_items: List[ActionItem],
        meeting_id: str,
    ) -> List[str]:
        """Create tasks in the task tracker.

        Args:
            action_items: List of action items
            meeting_id: Source meeting ID

        Returns:
            List of created task IDs
        """
        try:
            task_ids = []
            for item in action_items:
                task = Task(
                    id=str(uuid.uuid4())[:8],
                    title=item.description,
                    description=f"From meeting {meeting_id}",
                    owner=item.owner,
                    deadline=item.deadline,
                    priority=item.priority,
                    meeting_id=meeting_id,
                )
                task_id = self.task_tracker.add_task(task)
                task_ids.append(task_id)

            self.logger.info(f"Created {len(task_ids)} tasks from meeting {meeting_id}")
            return task_ids

        except Exception as e:
            self.logger.error(f"Failed to create tasks: {e}")
            return []

    async def send_deadline_reminders(self) -> bool:
        """Send Slack reminders for upcoming deadlines.

        Returns:
            True if successful
        """
        try:
            from ..integrations.slack import SlackClient

            upcoming = self.task_tracker.get_upcoming_tasks(days=1)
            if not upcoming:
                self.logger.info("No upcoming deadlines to remind")
                return True

            slack_client = SlackClient()

            message_parts = ["📅 **Yarın Deadline Olacak Görevler:**\n"]
            for task in upcoming:
                message_parts.append(
                    f"• {task.title} (Sorumlu: {task.owner})"
                )

            message = "\n".join(message_parts)

            # Send to Slack (would need to implement or use existing Slack integration)
            self.logger.info(f"Would send Slack reminder: {message}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to send deadline reminders: {e}")
            return False

    def new_finding_count(self) -> int:
        """Return count of new meeting tasks."""
        upcoming = self.task_tracker.get_upcoming_tasks(days=1)
        return len(upcoming)
