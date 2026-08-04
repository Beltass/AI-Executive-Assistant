"""Tests for the Toplantı Hazırlık & Takip advisor.

``MeetingPrepAdvisor`` reads the upcoming meetings from Google Calendar, tries
to match each one to a past note in Google Drive and hands the collected FACTS
to the shared batched model call. It must:

* keep only the events a human actually prepares for — no all-day blocks, no
  attendee-less focus time;
* match notes on title tokens and attendee names, with Turkish letters folded
  so "Şikayet"/"sikayet" are the same word;
* fall back to ``GOOGLE_DRIVE_FOLDER_ID`` when no dedicated notes folder is set;
* degrade to ``skipped`` with a TURKISH explanation on every missing piece (no
  Google credentials, an auth failure, an unreachable calendar, no meetings, no
  model key) — never a traceback, never a failed run;
* stay PRIVATE: calendar entries and document content never reach the public
  dashboard.

Everything here runs OFFLINE: the Google clients are stubbed in every test, so
no test touches the network or reads a credential.
"""

from __future__ import annotations

import pytest

from ai_assistant import reports
from ai_assistant.advisors import meeting_prep as prep_module
from ai_assistant.advisors.meeting_prep import (
    CAVEAT,
    METADATA_ONLY_NOTE,
    SKIP_NO_GOOGLE,
    SKIP_NO_LLM,
    Meeting,
    MeetingPrepAdvisor,
    notes_folder_id,
    parse_event,
    score_note,
)
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-654321"

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_DRIVE_FOLDER_ID",
    "MEETING_PREP_NOTES_FOLDER_ID",
    "MEETING_PREP_LOOKAHEAD_DAYS",
    "MEETING_PREP_MAX_NOTES",
]

EVENT = {
    "summary": "Tahsilat operasyonu değerlendirme",
    "start": {"dateTime": "2026-08-05T14:00:00+03:00"},
    "end": {"dateTime": "2026-08-05T15:00:00+03:00"},
    "attendees": [
        {"email": "ayse.yilmaz@example.com"},
        {"email": "kaynak@example.com", "resource": True},
    ],
    "location": "Toplantı Odası 3",
    "description": "Geçen ayın devir oranları konuşulacak.",
}


@pytest.fixture()
def blank_env(monkeypatch, tmp_path):
    """No credentials at all, and a Google token path that cannot exist."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    yield


@pytest.fixture()
def google_ok(monkeypatch, blank_env):
    """Google auth answers yes; nothing is actually contacted."""
    monkeypatch.setattr(prep_module.google_auth, "google_configured", lambda: True)
    monkeypatch.setattr(prep_module.google_auth, "get_credentials", lambda: object())
    yield


def _calendar(monkeypatch, events):
    """Serve canned calendar events instead of calling Google."""
    seen = {}

    def fake_fetch(self, creds, days):
        seen["days"] = days
        return list(events)

    monkeypatch.setattr(MeetingPrepAdvisor, "_fetch_events", fake_fetch)
    return seen


# --- registration and privacy ------------------------------------------------


def test_the_advisor_is_registered_in_the_live_roster():
    from ai_assistant.advisors import all_advisors

    assert "meeting_prep" in [advisor.key for advisor in all_advisors()]


def test_the_advisor_declares_itself_private():
    assert MeetingPrepAdvisor.private is True


def test_the_advisor_is_on_the_private_key_safety_net():
    assert "meeting_prep" in reports.PRIVATE_ADVISOR_KEYS


# --- parse_event -------------------------------------------------------------


def test_parse_event_reads_a_normal_meeting():
    meeting = parse_event(EVENT)
    assert meeting is not None
    assert meeting.summary == "Tahsilat operasyonu değerlendirme"
    assert meeting.location == "Toplantı Odası 3"
    assert meeting.when_label == "05.08.2026 14:00"
    # A meeting ROOM is not a participant.
    assert meeting.attendees == ["ayse.yilmaz@example.com"]


def test_parse_event_drops_all_day_blocks():
    """An all-day entry has a ``date``, not a ``dateTime``: nothing to prepare."""
    assert parse_event({"summary": "Yıllık izin", "start": {"date": "2026-08-05"}}) is None


def test_parse_event_drops_attendee_less_focus_blocks():
    event = {
        "summary": "Odaklanma zamanı",
        "start": {"dateTime": "2026-08-05T09:00:00+03:00"},
        "end": {"dateTime": "2026-08-05T11:00:00+03:00"},
    }
    assert parse_event(event) is None


def test_parse_event_survives_a_meeting_without_a_title():
    event = dict(EVENT, summary="")
    assert parse_event(event).summary == "Başlıksız toplantı"


# --- score_note --------------------------------------------------------------


def _meeting(summary="Tahsilat operasyonu değerlendirme", attendees=None):
    return Meeting(
        summary=summary,
        start="2026-08-05T14:00:00+03:00",
        attendees=attendees if attendees is not None else ["ayse.yilmaz@example.com"],
    )


def test_score_note_rewards_shared_title_words():
    assert score_note(_meeting(), "Tahsilat operasyonu notlari.docx") == 4


def test_score_note_rewards_an_attendee_named_in_the_file():
    scored = score_note(_meeting(), "ayse ile gorusme")
    assert scored >= 3


def test_score_note_folds_turkish_letters():
    """`Şikâyet`/`sikayet` and `İtibar`/`itibar` must match each other."""
    meeting = _meeting(summary="ŞİKAYET İTİBAR değerlendirmesi", attendees=[])
    assert score_note(meeting, "sikayet itibar notu.txt") == 4


def test_score_note_ignores_generic_note_words():
    """Every file is called "toplantı notları" — that is not a match."""
    assert score_note(_meeting(summary="Bütçe planı", attendees=[]), "toplanti notlari") == 0


def test_score_note_of_an_unrelated_file_is_zero():
    assert score_note(_meeting(), "kedi fotograflari") == 0


# --- notes_folder_id ---------------------------------------------------------


def test_notes_folder_id_is_empty_without_configuration(blank_env):
    assert notes_folder_id() == ""


def test_notes_folder_id_falls_back_to_the_drive_folder(blank_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "drive-root")
    assert notes_folder_id() == "drive-root"


def test_the_dedicated_notes_folder_wins(blank_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "drive-root")
    monkeypatch.setenv("MEETING_PREP_NOTES_FOLDER_ID", "notes-folder")
    assert notes_folder_id() == "notes-folder"


def test_a_blank_folder_secret_falls_through(blank_env, monkeypatch):
    """GitHub Actions expands an unset secret to an empty string."""
    monkeypatch.setenv("MEETING_PREP_NOTES_FOLDER_ID", "   ")
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "drive-root")
    assert notes_folder_id() == "drive-root"


# --- graceful skips ----------------------------------------------------------


def test_skipped_without_google_credentials(blank_env):
    briefing = MeetingPrepAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == SKIP_NO_GOOGLE


def test_skipped_when_google_auth_fails(monkeypatch, blank_env):
    monkeypatch.setattr(prep_module.google_auth, "google_configured", lambda: True)

    def boom():
        raise prep_module.google_auth.GoogleAuthError("token süresi doldu")

    monkeypatch.setattr(prep_module.google_auth, "get_credentials", boom)

    briefing = MeetingPrepAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "token süresi doldu" in briefing.text


def test_skipped_when_the_calendar_cannot_be_read(monkeypatch, google_ok):
    def boom(self, creds, days):
        raise RuntimeError("calendar 503")

    monkeypatch.setattr(MeetingPrepAdvisor, "_fetch_events", boom)

    briefing = MeetingPrepAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "Takvim verisi alınamadı" in briefing.text
    assert "calendar 503" in briefing.text


def test_skipped_when_there_is_no_meeting_to_prepare(monkeypatch, google_ok):
    """Only all-day and focus blocks ahead: nothing to prepare for."""
    _calendar(monkeypatch, [{"summary": "Yıllık izin", "start": {"date": "2026-08-05"}}])

    briefing = MeetingPrepAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "yaklaşan toplantı yok" in briefing.text
    assert "3 gün" in briefing.text  # the default lookahead


def test_skipped_without_a_model_key(monkeypatch, google_ok):
    _calendar(monkeypatch, [EVENT])

    briefing = MeetingPrepAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == SKIP_NO_LLM


def test_no_batch_section_without_a_model_key(monkeypatch, google_ok):
    _calendar(monkeypatch, [EVENT])
    assert MeetingPrepAdvisor().batch_section() is None


def test_no_batch_section_when_the_run_is_skipped(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert MeetingPrepAdvisor().batch_section() is None


def test_a_failing_llm_is_a_failure_not_a_crash(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _calendar(monkeypatch, [EVENT])

    def boom(*_args, **_kwargs):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(prep_module.llm, "generate_text", boom)

    briefing = MeetingPrepAdvisor().generate_briefing()
    assert briefing.status == STATUS_FAILED
    assert "kota doldu" in briefing.text


# --- the collected facts -----------------------------------------------------


def test_the_lookahead_window_is_configurable(monkeypatch, google_ok):
    monkeypatch.setenv("MEETING_PREP_LOOKAHEAD_DAYS", "7")
    seen = _calendar(monkeypatch, [])

    MeetingPrepAdvisor().generate_briefing()
    assert seen["days"] == 7


def test_the_prompt_carries_the_meeting_facts(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _calendar(monkeypatch, [EVENT])

    section = MeetingPrepAdvisor().batch_section()
    assert section is not None
    assert section.key == "meeting_prep"
    assert "Tahsilat operasyonu değerlendirme" in section.user_prompt
    assert "05.08.2026 14:00" in section.user_prompt
    assert "ayse.yilmaz@example.com" in section.user_prompt
    # No note was found, so the model is told to say so instead of inventing one.
    assert "Geçmiş not: YOK." in section.user_prompt


def test_only_the_first_meetings_are_prepared(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    events = [dict(EVENT, summary=f"Toplantı {index}") for index in range(5)]
    _calendar(monkeypatch, events)

    section = MeetingPrepAdvisor().batch_section()
    assert "[TOPLANTI 1]" in section.user_prompt
    assert f"[TOPLANTI {prep_module.MAX_MEETINGS}]" in section.user_prompt
    assert f"[TOPLANTI {prep_module.MAX_MEETINGS + 1}]" not in section.user_prompt


def test_matched_drive_notes_reach_the_prompt(monkeypatch, google_ok):
    """A Drive note whose name matches the meeting is attached, title-level."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "drive-root")
    _calendar(monkeypatch, [EVENT])

    class FakeDriveClient:
        def __init__(self):
            # The shared OAuth scope only sees file METADATA, so reading the
            # body fails exactly as it does in production.
            self.service = None

        def list_documents_in_folder(self, folder, max_results=100):
            assert folder == "drive-root"
            return [
                {
                    "id": "note-1",
                    "name": "Tahsilat operasyonu - 10 Temmuz notlari",
                    "modifiedTime": "2026-07-10T09:00:00Z",
                    "webViewLink": "https://drive.example/note-1",
                },
                {"id": "note-2", "name": "kedi fotograflari"},
            ]

    from ai_assistant.integrations import google_drive

    monkeypatch.setattr(google_drive, "DriveClient", FakeDriveClient)

    section = MeetingPrepAdvisor().batch_section()
    assert "Tahsilat operasyonu - 10 Temmuz notlari" in section.user_prompt
    assert "https://drive.example/note-1" in section.user_prompt
    assert "10.07.2026" in section.user_prompt
    assert "kedi fotograflari" not in section.user_prompt
    # Body unreadable -> the model is warned to stay at title level.
    assert METADATA_ONLY_NOTE in section.user_prompt


def test_a_broken_drive_never_takes_the_section_down(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "drive-root")
    _calendar(monkeypatch, [EVENT])

    from ai_assistant.integrations import google_drive

    def boom():
        raise RuntimeError("drive 403")

    monkeypatch.setattr(google_drive, "DriveClient", boom)

    section = MeetingPrepAdvisor().batch_section()
    assert section is not None
    assert "Geçmiş not: YOK." in section.user_prompt


def test_the_batched_answer_carries_the_caveat_and_the_private_flag(monkeypatch, google_ok):
    briefing = MeetingPrepAdvisor().briefing_from_batch("  Hazırlık notu  ")
    assert briefing.status == STATUS_OK
    assert briefing.text.startswith("Hazırlık notu")
    assert briefing.text.endswith(CAVEAT)
    assert briefing.private is True
