"""Tests for the Slack "summarise my meeting notes" capability.

``ai_assistant.chat.ask`` is the sibling of ``chat.templates``: it inspects one
message, and either OWNS it (``handled``) or stays out of the way so the report
state machine sees it. It must:

* recognise the Turkish ways of asking for it — "toplantı notlarını özetle",
  "toplantıya hazırla", "geçen toplantıda ne konuştuk" — in any casing, with or
  without Turkish letters, and NOT hijack a report order;
* ask which note when several are plausible, using the SAME numbered menu as
  the rest of the chat, and remember that menu ACROSS PROCESSES (the poller
  runs in a fresh container every five minutes);
* degrade in Turkish at every step (no model key, no Google credentials, no
  notes folder, no notes, an unreadable folder, an insufficient OAuth scope, an
  empty note, a failing model) and never raise;
* say the scope problem OUT LOUD: with the shared `drive.metadata.readonly`
  token the file NAME is visible but the body is not, and the user has to
  re-consent — an empty summary would hide that.

Everything here runs OFFLINE: Drive, the LLM and Slack are all stubbed.
"""

from __future__ import annotations

import pytest

from ai_assistant.advisors import meeting_prep as prep_mod
from ai_assistant.chat import ask as ask_mod
from ai_assistant.chat.store import ChatStore
from ai_assistant.integrations.google_drive import DriveError, DrivePermissionError

CHANNEL = "C-CHAT"
USER = "U-BOSS"

FILES = [
    {
        "id": "note-1",
        "name": "Tahsilat operasyonu - 30 Temmuz",
        "modifiedTime": "2026-07-30T09:00:00Z",
        "mimeType": "application/vnd.google-apps.document",
        "webViewLink": "https://drive.example/note-1",
    },
    {
        "id": "note-2",
        "name": "Bütçe planlama notlari",
        "modifiedTime": "2026-07-28T09:00:00Z",
        "mimeType": "text/plain",
    },
]


class FakeDrive:
    """A Drive that lists canned files and serves canned bodies."""

    def __init__(self, files=None, bodies=None, error=None, read_error=None):
        self.files = FILES if files is None else files
        self.bodies = bodies or {}
        self.error = error
        self.read_error = read_error
        self.listed = []
        self.read = []

    def list_documents_in_folder(self, folder_id, max_results=100):
        self.listed.append((folder_id, max_results))
        if self.error is not None:
            raise self.error
        return list(self.files)

    def read_file_text(self, file_id, mime_type=None, max_chars=0):
        self.read.append(file_id)
        if self.read_error is not None:
            raise self.read_error
        return self.bodies.get(file_id, "")


@pytest.fixture()
def store(tmp_path):
    return ChatStore(str(tmp_path / "chat_state.json"))


@pytest.fixture()
def ready(monkeypatch):
    """Model key and Google credentials present, notes folder configured."""
    monkeypatch.setattr(ask_mod.llm, "is_configured", lambda: True)
    monkeypatch.setattr(ask_mod.google_auth, "google_configured", lambda: True)
    monkeypatch.setenv("MEETING_PREP_NOTES_FOLDER_ID", "notes-folder")
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    yield


def _handle(store, text, drive=None, generator=None, notify=None, **kwargs):
    return ask_mod.handle(
        text,
        store,
        USER,
        channel=CHANNEL,
        client_factory=(lambda: drive) if drive is not None else None,
        generator=generator,
        notify=notify,
        **kwargs,
    )


# --- trigger recognition -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "toplantı notlarını özetle",
        "toplanti notlarini ozetle",
        "Toplantı Notlarını Özetle",
        "TOPLANTI NOTLARINI ÖZETLE",
        "lütfen toplantı notlarını özetler misin",
        "toplantıya hazırla",
        "toplantıya hazırlan",
        "toplantı hazırlığı yap",
        "geçen toplantıda ne konuştuk",
        "geçen toplantıda ne konuşduk",
        "gecen toplantida ne konusuldu",
        "geçen toplantıda neler konuşuldu",
        "son toplantının özeti",
        "tahsilat toplantısının notlarını özetle",
    ],
)
def test_the_turkish_ways_of_asking_are_recognised(text):
    assert ask_mod.is_summary_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "merhaba",
        "rapor",
        "son 3 ay vardiya bazında SLA raporu, Excel",
        "şablonlar",
        "haftalık SLA raporu çalıştır",
        "toplantı odası rezervasyonu lazım",
        "1",
        "iptal",
    ],
)
def test_unrelated_messages_are_left_to_the_report_flow(text):
    assert ask_mod.is_summary_request(text) is False


def test_an_unrelated_message_is_not_handled(store):
    result = _handle(store, "son 3 ay SLA raporu")
    assert result.handled is False
    assert result.messages == []


# --- degradation paths -------------------------------------------------------


def test_without_a_model_key_it_says_so_in_turkish(store, monkeypatch):
    monkeypatch.setattr(ask_mod.llm, "is_configured", lambda: False)
    result = _handle(store, "toplantı notlarını özetle")
    assert result.handled is True
    assert result.messages == [ask_mod.NO_LLM]
    assert "GEMINI_API_KEY" in result.messages[0]


def test_without_google_credentials_it_says_so_in_turkish(store, monkeypatch):
    monkeypatch.setattr(ask_mod.llm, "is_configured", lambda: True)
    monkeypatch.setattr(ask_mod.google_auth, "google_configured", lambda: False)
    result = _handle(store, "toplantı notlarını özetle")
    assert result.messages == [ask_mod.NO_GOOGLE]


def test_without_a_notes_folder_it_names_the_variable(store, monkeypatch, ready):
    monkeypatch.delenv("MEETING_PREP_NOTES_FOLDER_ID", raising=False)
    result = _handle(store, "toplantı notlarını özetle")
    assert result.messages == [ask_mod.NO_FOLDER]
    assert "MEETING_PREP_NOTES_FOLDER_ID" in result.messages[0]


def test_an_empty_folder_is_explained_not_ignored(store, ready):
    result = _handle(store, "toplantı notlarını özetle", drive=FakeDrive(files=[]))
    assert result.messages == [ask_mod.NO_NOTES]


def test_a_broken_drive_never_raises(store, ready):
    drive = FakeDrive(error=DriveError("403 forbidden"))
    result = _handle(store, "toplantı notlarını özetle", drive=drive)
    assert result.handled is True
    assert "DriveError" in result.messages[0]


def test_an_insufficient_scope_names_the_scope_and_the_fix(store, ready):
    """The most likely production failure: metadata scope, no content."""
    drive = FakeDrive(
        files=[FILES[0]], read_error=DrivePermissionError("403 insufficientPermissions")
    )
    result = _handle(store, "toplantı notlarını özetle", drive=drive)
    assert result.messages == [ask_mod.SCOPE_PROBLEM]
    assert "drive.readonly" in result.messages[0]
    assert "GOOGLE_REFRESH_TOKEN" in result.messages[0]
    assert result.summarised is False


def test_an_unreadable_note_is_reported_with_its_name(store, ready):
    drive = FakeDrive(files=[FILES[0]], read_error=DriveError("dosya bulunamadı"))
    result = _handle(store, "toplantı notlarını özetle", drive=drive)
    assert "Tahsilat operasyonu - 30 Temmuz" in result.messages[0]
    assert result.summarised is False


def test_an_empty_note_is_not_summarised(store, ready):
    drive = FakeDrive(files=[FILES[0]], bodies={"note-1": "   "})
    result = _handle(store, "toplantı notlarını özetle", drive=drive)
    assert "boş" in result.messages[0]
    assert result.summarised is False


def test_a_failing_model_call_answers_instead_of_raising(store, ready):
    drive = FakeDrive(files=[FILES[0]], bodies={"note-1": "Karar: ödeme planı."})

    def boom(system, user):
        raise RuntimeError("gemini 503")

    result = _handle(store, "toplantı notlarını özetle", drive=drive, generator=boom)
    assert result.handled is True
    assert "RuntimeError" in result.messages[0]
    assert result.summarised is False


# --- the happy path ----------------------------------------------------------


def test_a_single_note_is_summarised_without_a_menu(store, ready):
    drive = FakeDrive(files=[FILES[0]], bodies={"note-1": "Karar: ödeme planı."})
    seen = {}

    def generate(system, user):
        seen["system"] = system
        seen["user"] = user
        return "Özet gövdesi"

    result = _handle(
        store, "toplantı notlarını özetle", drive=drive, generator=generate
    )

    assert result.summarised is True
    assert len(result.messages) == 1
    assert "Tahsilat operasyonu - 30 Temmuz" in result.messages[0]
    assert "Özet gövdesi" in result.messages[0]
    assert "https://drive.example/note-1" in result.messages[0]
    # The advisor's persona and contract are reused, not re-invented.
    assert seen["system"] == prep_mod.SYSTEM_PROMPT
    assert "Karar: ödeme planı." in seen["user"]
    assert "Alınan kararlar" in seen["user"]
    assert "Senin görevlerin" in seen["user"]
    assert "Ekibin görevleri" in seen["user"]
    assert "gündem" in seen["user"]
    # Nothing is left waiting: no menu was shown.
    assert store.sessions == {}


def test_the_user_hears_about_the_request_before_the_long_call(store, ready):
    """Five-minute polling: the acknowledgement must not wait for the model."""
    posted = []
    drive = FakeDrive(files=[FILES[0]], bodies={"note-1": "içerik"})

    def generate(system, user):
        # By the time the model is called the user has already been told.
        assert posted == [ask_mod.ACK]
        return "Özet"

    _handle(
        store,
        "toplantı notlarını özetle",
        drive=drive,
        generator=generate,
        notify=posted.append,
    )
    assert posted == [ask_mod.ACK]


def test_a_named_meeting_skips_the_menu(store, ready):
    """ "tahsilat toplantısı" points at exactly one file — do not ask."""
    drive = FakeDrive(bodies={"note-1": "içerik"})
    result = _handle(
        store,
        "tahsilat toplantısının notlarını özetle",
        drive=drive,
        generator=lambda s, u: "Özet",
    )
    assert result.summarised is True
    assert drive.read == ["note-1"]


def test_a_spreadsheet_is_not_a_meeting_note(store, ready):
    """The report flow owns spreadsheets; a note is a document."""
    files = [
        {
            "id": "sheet-1",
            "name": "SLA verileri",
            "mimeType": "application/vnd.google-apps.spreadsheet",
        },
        FILES[0],
    ]
    drive = FakeDrive(files=files, bodies={"note-1": "içerik"})
    result = _handle(
        store, "toplantı notlarını özetle", drive=drive, generator=lambda s, u: "Özet"
    )
    assert drive.read == ["note-1"]
    assert result.summarised is True


# --- disambiguation ----------------------------------------------------------


def test_several_notes_produce_a_numbered_menu(store, ready):
    drive = FakeDrive()
    result = _handle(store, "toplantı notlarını özetle", drive=drive)

    assert result.handled is True
    assert result.summarised is False
    body = result.messages[0]
    assert "Hangi toplantı notunu özetleyeyim?" in body
    assert "`1` Tahsilat operasyonu - 30 Temmuz" in body
    assert "`2` Bütçe planlama notlari" in body
    # Nothing was read yet — the choice is the user's.
    assert drive.read == []


def test_the_menu_survives_a_fresh_process(tmp_path, ready):
    """The poller that shows the menu is dead when the number arrives."""
    path = str(tmp_path / "chat_state.json")
    first = ChatStore(path)
    _handle(first, "toplantı notlarını özetle", drive=FakeDrive())

    # New container, new process, same repository file.
    second = ChatStore(path)
    drive = FakeDrive(bodies={"note-2": "Bütçe kararları"})
    result = _handle(second, "2", drive=drive, generator=lambda s, u: "Özet")

    assert result.summarised is True
    assert drive.read == ["note-2"]
    assert "Bütçe planlama notlari" in result.messages[0]
    # The menu is consumed exactly once.
    assert ChatStore(path).sessions == {}


def test_a_note_can_be_chosen_by_name(store, ready):
    _handle(store, "toplantı notlarını özetle", drive=FakeDrive())
    drive = FakeDrive(bodies={"note-2": "Bütçe kararları"})
    result = _handle(
        store, "Bütçe planlama notlari", drive=drive, generator=lambda s, u: "Ö"
    )
    assert result.summarised is True
    assert drive.read == ["note-2"]


def test_an_unusable_answer_reshows_the_menu(store, ready):
    _handle(store, "toplantı notlarını özetle", drive=FakeDrive())
    result = _handle(store, "9", drive=FakeDrive())
    assert result.handled is True
    assert "Hangi toplantı notunu özetleyeyim?" in result.messages[0]
    # Still waiting: the choice was not guessed.
    assert store.sessions


def test_cancel_closes_the_menu(store, ready):
    _handle(store, "toplantı notlarını özetle", drive=FakeDrive())
    result = _handle(store, "iptal")
    assert result.handled is True
    assert result.messages == ["Tamam, not özetini bıraktım."]
    assert store.sessions == {}


def test_asking_again_replaces_the_open_menu(store, ready):
    _handle(store, "toplantı notlarını özetle", drive=FakeDrive())
    result = _handle(store, "toplantı notlarını özetle", drive=FakeDrive())
    assert "Hangi toplantı notunu özetleyeyim?" in result.messages[0]
    assert len(store.sessions) == 1


def test_the_pending_menu_does_not_collide_with_a_report_order(store, ready):
    """The report state machine must not see the note menu as its session."""
    _handle(store, "toplantı notlarını özetle", drive=FakeDrive())
    assert store.get_session(CHANNEL, USER) is None
    assert ask_mod.pending_key(CHANNEL, USER) in store.sessions


def test_a_forgotten_menu_expires_like_any_session(store, ready, monkeypatch):
    from datetime import datetime, timedelta

    old = datetime.now() - timedelta(hours=5)
    _handle(store, "toplantı notlarını özetle", drive=FakeDrive(), now=old)
    assert store.sessions
    store.prune_sessions()
    assert store.sessions == {}


# --- wiring into the session engine -----------------------------------------


def test_the_session_engine_routes_the_request_to_this_module(
    store, ready, monkeypatch
):
    from ai_assistant.chat.session import SessionEngine

    drive = FakeDrive(files=[FILES[0]], bodies={"note-1": "içerik"})
    monkeypatch.setattr(ask_mod, "_default_client", lambda: drive)
    # ``**kw`` because the real call now passes ``thinking_budget``: the summary
    # is lifted out of the note, so it pays for no "thinking" tokens.
    monkeypatch.setattr(ask_mod.llm, "generate_text", lambda s, u, **kw: "Özet gövdesi")

    posted = []
    engine = SessionEngine(store=store, notifier=posted.append)
    turn = engine.handle(CHANNEL, USER, "toplantı notlarını özetle")

    assert posted == [ask_mod.ACK]
    assert "Özet gövdesi" in turn.messages[0]
    # No report order was opened by the summary request.
    assert turn.spec is None
    assert store.get_session(CHANNEL, USER) is None


def test_the_report_flow_is_untouched_by_the_new_module(store, ready):
    from ai_assistant.chat.session import SessionEngine

    engine = SessionEngine(store=store, source_lister=lambda: [])
    turn = engine.handle(CHANNEL, USER, "rapor")
    assert turn.messages
    assert store.get_session(CHANNEL, USER) is not None
