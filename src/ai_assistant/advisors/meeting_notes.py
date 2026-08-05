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
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from . import Advisor, Briefing
from ._turkish_dates import parse_iso_date, parse_turkish_date
from ..action_center import ActionItem
from ..integrations import llm
from ..integrations.google_drive_manager import GoogleDriveManager
from ..integrations.task_tracker import Task, TaskTracker, TaskStatus
from ..integrations import STATUS_OK, STATUS_FAILED, STATUS_SKIPPED
from ..integrations.slack_advisor_bridge import SlackAdvisorBridge

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

#: What the model is asked to pull OUT of a transcript. The schema below is the
#: contract between this prompt and :func:`_apply_analysis`: every key names a
#: field that actually exists on :class:`MeetingNotes`, :class:`ActionItem` or
#: :class:`CompetitiveAction`, so a well-formed answer maps across with no
#: guesswork and an ill-formed one is REJECTED rather than half-applied.
#:
#: Deadlines are asked for TWICE on purpose: ``deadline_text`` is the phrase as
#: it was actually spoken ("cuma gününe kadar"), which
#: :mod:`ai_assistant.advisors._turkish_dates` resolves deterministically
#: against the meeting's own date; ``deadline_iso`` is the model's own guess and
#: is used only when the grammar does not recognise the phrase. Models miscount
#: days silently, so the guess is the fallback, never the primary.
MEETING_ANALYSIS_SYSTEM_PROMPT = (
    "Sen bir toplantı analistisin. Sana verilen toplantı deşifre metnini "
    "okuyup yapılandırılmış JSON çıkarırsın.\n"
    "\n"
    "Kurallar:\n"
    "- SADECE deşifre metninde geçenleri yaz. Bilgi UYDURMA; metinde yoksa "
    "ilgili listeyi boş bırak.\n"
    "- Metnin dilinde yaz (Türkçe toplantı → Türkçe çıktı).\n"
    "- İsimleri metinde geçtiği gibi kullan. Örnek isim veya yer tutucu isim "
    "KULLANMA.\n"
    "- 'deadline_text' alanına tarihi konuşmada söylendiği HÂLİYLE yaz "
    "(\"cuma gününe kadar\", \"iki hafta içinde\", \"ayın 15'i\"). Tarih "
    "söylenmediyse boş string bırak.\n"
    "- 'deadline_iso' alanına aynı tarihin YYYY-MM-DD tahminini yaz; emin "
    "değilsen boş string bırak.\n"
    "- 'priority' 1 (düşük) ile 5 (kritik) arası bir tam sayıdır.\n"
    "- 'impact' ve 'urgency' yalnızca \"low\", \"medium\" veya \"high\" "
    "olabilir.\n"
    "- 'competitive_actions' yalnızca RAKİPLERLE ilgili bir şey konuşulduysa "
    "doldurulur; konuşulmadıysa boş liste döndür.\n"
    "\n"
    "Yanıtın SADECE şu şemadaki JSON nesnesi olsun, başka hiçbir metin ekleme:\n"
    "{\n"
    '  "summary": "toplantının birkaç cümlelik özeti",\n'
    '  "findings": ["önemli bulgu", ...],\n'
    '  "action_items": [\n'
    "    {\n"
    '      "description": "yapılacak iş",\n'
    '      "owner": "sorumlu kişi",\n'
    '      "deadline_text": "konuşmada geçtiği hâliyle tarih ifadesi",\n'
    '      "deadline_iso": "YYYY-MM-DD",\n'
    '      "priority": 3\n'
    "    }\n"
    "  ],\n"
    '  "competitive_actions": [\n'
    "    {\n"
    '      "description": "rakibin yaptığı şey",\n'
    '      "impact": "medium",\n'
    '      "urgency": "medium",\n'
    '      "recommended_action": "bizim ne yapmamız gerektiği"\n'
    "    }\n"
    "  ],\n"
    '  "next_steps": ["sonraki adım", ...]\n'
    "}"
)

#: An hour of meeting yields a page of JSON, not a book; 8k is the provider
#: default and has room to spare. Overridable for unusually long recordings.
DEFAULT_ANALYSIS_MAX_OUTPUT_TOKENS = 8192

#: Structured extraction, not advice. The answer is copied out of the
#: transcript against a fixed schema, so paying for a "thinking" pass buys
#: nothing but billed tokens and latency — and the one genuinely hard part
#: (turning "cuma gününe kadar" into a date) is done in code, not by the model.
ANALYSIS_THINKING_BUDGET = 0

#: Levels the downstream report renderer understands. Anything else the model
#: invents ("critical", "çok yüksek") falls back to ``medium``.
ANALYSIS_LEVELS = ("low", "medium", "high")

_JSON_FENCE_RE = re.compile(r"\A\s*```[a-zA-Z]*\s*|\s*```\s*\Z")


def _strip_json_fence(text: str) -> str:
    """Remove a ```json … ``` wrapper the model may have added."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = _JSON_FENCE_RE.sub("", stripped).strip()
    return stripped


def _parse_analysis_json(raw: str) -> Dict[str, Any]:
    """Read the model's answer into a dict, or raise ``ValueError``.

    Raising rather than returning ``{}`` is the point: a response that cannot
    be read is a FAILURE, and the caller has to be able to say so instead of
    quietly filing an empty meeting.
    """
    text = _strip_json_fence(raw)
    if not text:
        raise ValueError("model boş yanıt döndürdü")

    try:
        payload = json.loads(text)
    except ValueError:
        # Some models still wrap the object in a sentence; take the outermost
        # braces and try once more. A second failure propagates.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("yanıtta JSON nesnesi bulunamadı")
        payload = json.loads(text[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError(f"JSON nesnesi bekleniyordu, {type(payload).__name__} geldi")
    return payload


def _text(value: Any) -> str:
    """A trimmed string, whatever the model put in the field."""
    if value is None or isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _string_list(value: Any) -> List[str]:
    """Non-empty strings from a list field; anything else yields ``[]``."""
    if not isinstance(value, list):
        return []
    return [item for item in (_text(entry) for entry in value) if item]


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _coerce_priority(value: Any) -> int:
    """Clamp the model's priority into the 1-5 range ``ActionItem`` documents."""
    try:
        priority = int(float(value))
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, priority))


def _coerce_level(value: Any) -> str:
    level = _text(value).lower()
    return level if level in ANALYSIS_LEVELS else "medium"


def _resolve_deadline(item: Dict[str, Any], anchor: datetime) -> Optional[datetime]:
    """Turn one action item's date fields into a real ``datetime`` or ``None``.

    The spoken phrase is resolved in code first (deterministic, testable
    offline); the model's ISO guess is consulted only when the grammar does
    not recognise the phrase. When neither works the deadline stays ``None`` —
    an empty deadline beats an invented one.
    """
    spoken = _text(item.get("deadline_text"))
    if spoken:
        resolved = parse_turkish_date(spoken, anchor)
        if resolved is not None:
            return resolved

    guess = _text(item.get("deadline_iso")) or _text(item.get("deadline"))
    if guess:
        return parse_iso_date(guess, anchor)
    return None


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
    - Transcribe audio files with Gemini
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
        self.slack_bridge = SlackAdvisorBridge()
        self.state_dir = Path(".assistant_state")
        self.state_dir.mkdir(exist_ok=True)
        self.meetings_file = self.state_dir / "meetings.json"
        # Why the last transcript came back empty (skipped vs. failed), for
        # callers to log. ``None`` means "nothing has gone wrong yet".
        self.last_transcription_error: Optional[str] = None
        # Same, for the last analysis: why the notes came back without action
        # items (no key, no transcript, failed request, unreadable answer).
        self.last_analysis_error: Optional[str] = None

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

    @staticmethod
    def _analysis_max_output_tokens() -> int:
        """Output budget for one analysis, read at call time."""
        try:
            tokens = int(
                os.getenv("MEETING_ANALYSIS_MAX_OUTPUT_TOKENS")
                or DEFAULT_ANALYSIS_MAX_OUTPUT_TOKENS
            )
        except ValueError:
            tokens = DEFAULT_ANALYSIS_MAX_OUTPUT_TOKENS
        return tokens if tokens > 0 else DEFAULT_ANALYSIS_MAX_OUTPUT_TOKENS

    @staticmethod
    def _analysis_user_prompt(
        transcript: str,
        meeting_title: str,
        attendees: List[str],
        meeting_date: datetime,
    ) -> str:
        """The turn's text: what meeting this is, plus the words themselves."""
        people = ", ".join(name for name in attendees if name) or "belirtilmemiş"
        return (
            f"Toplantı başlığı: {meeting_title}\n"
            f"Toplantı tarihi: {meeting_date.strftime('%Y-%m-%d')}\n"
            f"Katılımcılar: {people}\n"
            "\n"
            "Deşifre metni:\n"
            f"{transcript}"
        )

    async def analyze_meeting(
        self,
        transcript: str,
        meeting_title: str = "Toplantı",
        attendees: List[str] = None,
    ) -> MeetingNotes:
        """Analyze a meeting transcript with the LLM.

        Everything in the returned notes is derived from THIS transcript:
        summary, findings, action items (owner, priority, deadline),
        competitive intelligence and next steps. Deadlines are resolved from
        the phrase as it was spoken by :mod:`._turkish_dates`, anchored on the
        meeting's own date, and fall back to the model's ISO guess only when
        that grammar does not recognise the phrase.

        Nothing is invented when the analysis cannot run. Without a provider
        key, without a transcript, or after a failed/unreadable response the
        notes come back EMPTY — the transcript and the title are kept, the
        analysis fields are not filled in, and the reason is left on
        :attr:`last_analysis_error` so the caller can log WHY. A plausible but
        fabricated action item would be filed as a real task, chased in a real
        Slack reminder, and trusted; an empty one is visibly empty.

        Args:
            transcript: Meeting transcript text.
            meeting_title: Title of the meeting.
            attendees: List of meeting attendees.

        Returns:
            MeetingNotes object with analysis, or with the analysis fields left
            empty when the analysis was skipped or failed.
        """
        self.last_analysis_error = None
        attendees = attendees or ["Unknown"]
        meeting_notes = MeetingNotes(
            title=meeting_title,
            attendees=attendees,
            transcript_text=transcript or "",
        )

        body = (transcript or "").strip()
        if not body:
            self.last_analysis_error = "boş transkript — analiz atlandı"
            self.logger.info(self.last_analysis_error)
            return meeting_notes

        if not llm.is_configured():
            # Skipped, not failed: nothing is broken, a key is simply absent.
            self.last_analysis_error = (
                "analiz atlandı — missing env var(s): GEMINI_API_KEY "
                "or OPENAI_API_KEY"
            )
            self.logger.info(
                "LLM yapılandırılmamış, analiz atlandı (%s)", meeting_title
            )
            return meeting_notes

        self.logger.info(
            f"Analyzing meeting: {meeting_title} ({len(body)} characters)"
        )

        try:
            # Off the event loop: a blocking HTTP call with retries behind it.
            raw = await asyncio.to_thread(
                llm.generate_text,
                MEETING_ANALYSIS_SYSTEM_PROMPT,
                self._analysis_user_prompt(
                    body, meeting_title, attendees, meeting_notes.date
                ),
                max_output_tokens=self._analysis_max_output_tokens(),
                thinking_budget=ANALYSIS_THINKING_BUDGET,
            )
        except Exception as e:
            self.last_analysis_error = f"analiz isteği başarısız ({meeting_title}): {e}"
            self.logger.error(self.last_analysis_error)
            return meeting_notes

        try:
            payload = _parse_analysis_json(raw)
        except ValueError as e:
            self.last_analysis_error = (
                f"analiz yanıtı okunamadı ({meeting_title}): {e}"
            )
            self.logger.error(
                "%s — ham yanıt %d karakter", self.last_analysis_error, len(raw or "")
            )
            return meeting_notes

        self._apply_analysis(meeting_notes, payload)

        self.logger.info(
            "Meeting analysis completed: %d action items, %d findings",
            len(meeting_notes.action_items),
            len(meeting_notes.findings),
        )
        return meeting_notes

    @staticmethod
    def _apply_analysis(
        meeting_notes: MeetingNotes,
        payload: Dict[str, Any],
    ) -> None:
        """Copy a parsed analysis onto the notes, field by field.

        Every value is coerced to the type its dataclass field promises, and
        entries without a description are dropped: an owner and a deadline
        attached to nothing is not a task anybody can do.
        """
        anchor = meeting_notes.date

        meeting_notes.summary = _text(payload.get("summary"))
        meeting_notes.findings = _string_list(payload.get("findings"))
        meeting_notes.next_steps = _string_list(payload.get("next_steps"))

        action_items: List[ActionItem] = []
        for raw_item in _dict_list(payload.get("action_items")):
            description = _text(raw_item.get("description"))
            if not description:
                continue
            action_items.append(
                ActionItem(
                    description=description,
                    owner=_text(raw_item.get("owner")),
                    deadline=_resolve_deadline(raw_item, anchor),
                    priority=_coerce_priority(raw_item.get("priority")),
                )
            )
        meeting_notes.action_items = action_items

        competitive_actions: List[CompetitiveAction] = []
        for raw_action in _dict_list(payload.get("competitive_actions")):
            description = _text(raw_action.get("description"))
            if not description:
                continue
            competitive_actions.append(
                CompetitiveAction(
                    description=description,
                    impact=_coerce_level(raw_action.get("impact")),
                    urgency=_coerce_level(raw_action.get("urgency")),
                    recommended_action=_text(raw_action.get("recommended_action")),
                )
            )
        meeting_notes.competitive_actions = competitive_actions

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
        """Send Slack reminders for upcoming deadlines using Block Kit formatting.

        Returns:
            True if sent successfully or Slack unconfigured, False if send failed
        """
        try:
            upcoming = self.task_tracker.get_upcoming_tasks(days=1)
            if not upcoming:
                self.logger.info("No upcoming deadlines to remind")
                return True

            # Check if Slack is configured
            if not self.slack_bridge.slack_client:
                self.logger.info("Slack atlandı")
                return True

            # Build Block Kit message with upcoming deadlines
            blocks = self._build_deadline_reminder_blocks(upcoming)

            # Send to Slack (default to user DM, can be configured)
            response = await self.slack_bridge.slack_client.chat_postMessage(
                channel="@user_dm",
                blocks=blocks,
                text="📅 Yarın deadline olacak görevler",
            )

            if response.get("ok"):
                self.logger.info(
                    f"Deadline reminders sent for {len(upcoming)} tasks"
                )
                return True
            else:
                self.logger.error(
                    f"Failed to send deadline reminders: {response.get('error')}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Failed to send deadline reminders: {e}")
            return False

    def _build_deadline_reminder_blocks(self, tasks: List[Task]) -> List[Dict[str, Any]]:
        """Build Block Kit message for deadline reminders.

        Args:
            tasks: List of upcoming tasks

        Returns:
            List of Block Kit block dictionaries
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📅 Yarın Deadline Olacak Görevler",
                },
            },
            {"type": "divider"},
        ]

        for task in tasks:
            deadline_str = (
                task.deadline.strftime("%Y-%m-%d")
                if task.deadline
                else "TBD"
            )
            priority_emoji = self._get_priority_emoji(task.priority)

            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Görev:*\n{task.title}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Sorumlu:*\n{task.owner}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Deadline:*\n{deadline_str}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Öncelik:*\n{priority_emoji} {task.priority}/5",
                        },
                    ],
                }
            )
            blocks.append({"type": "divider"})

        return blocks

    @staticmethod
    def _get_priority_emoji(priority: int) -> str:
        """Get emoji representation for priority level.

        Args:
            priority: Priority level (1-5)

        Returns:
            Emoji string
        """
        if priority >= 5:
            return "🔴"  # Critical
        elif priority >= 4:
            return "🟠"  # High
        elif priority >= 3:
            return "🟡"  # Medium
        else:
            return "🟢"  # Low

    def new_finding_count(self) -> int:
        """Return count of new meeting tasks."""
        upcoming = self.task_tracker.get_upcoming_tasks(days=1)
        return len(upcoming)
