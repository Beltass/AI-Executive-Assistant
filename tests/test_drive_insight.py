"""Tests for the Drive Dosya Analisti advisor.

``DriveInsightAdvisor`` lists a Google Drive folder, keeps only the files that
are BOTH recent and not yet reported, reads them and hands the collected FACTS
to the shared batched model call. It must:

* ignore the things that are not "a file the user dropped in": sub-folders and
  the assistant's OWN ``<advisor>.md`` report archive (otherwise the advisor
  ends up summarising its own output);
* respect the lookback window and the per-run file cap;
* remember what it already said through :mod:`ai_assistant.memory`, so the same
  document is never analysed twice — and mark ONLY the files it actually
  reported, never the ones the cap cut off;
* degrade to ``skipped`` with a TURKISH explanation on every missing piece (no
  Google credentials, no folder, an unreadable folder, no new files, no model
  key) — never a traceback, never a failed run;
* produce NO analysis at all when there is no LLM key: an invented summary of a
  file nobody read is worse than silence;
* stay PRIVATE: file names and document content never reach the public
  dashboard.

Everything here runs OFFLINE: the Drive client is stubbed in every test, so no
test touches the network or reads a credential.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_assistant import memory, reports, status_report
from ai_assistant.advisors import drive_insight as insight_module
from ai_assistant.advisors.drive_insight import (
    CAVEAT,
    DEFAULT_LOOKBACK_DAYS,
    METADATA_ONLY_NOTE,
    SKIP_NO_FOLDER,
    SKIP_NO_GOOGLE,
    SKIP_NO_LLM,
    DriveInsightAdvisor,
    insight_folder_id,
    is_own_report,
    is_recent,
    parse_file,
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
    "DRIVE_INSIGHT_FOLDER_ID",
    "DRIVE_INSIGHT_LOOKBACK_DAYS",
    "DRIVE_INSIGHT_MAX_FILES",
    "DRIVE_INSIGHT_MAX_CHARS",
]


def _stamp(days_ago: float = 0) -> str:
    """An RFC-3339 ``modifiedTime`` this many days in the past."""
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.isoformat().replace("+00:00", "Z")


def _entry(name: str, file_id: str = "", **extra) -> dict:
    """One Drive listing record, recent by default."""
    record = {
        "id": file_id or f"id-{name}",
        "name": name,
        "mimeType": "application/pdf",
        "modifiedTime": _stamp(1),
        "webViewLink": f"https://drive.google.com/file/d/{file_id or name}/view",
    }
    record.update(extra)
    return record


@pytest.fixture()
def blank_env(monkeypatch, tmp_path):
    """No credentials at all, and a Google token path that cannot exist."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    yield


@pytest.fixture()
def google_ok(monkeypatch, blank_env):
    """Google auth answers yes and a folder is configured; nothing is contacted."""
    monkeypatch.setattr(insight_module.google_auth, "google_configured", lambda: True)
    monkeypatch.setattr(insight_module.google_auth, "get_credentials", lambda: object())
    monkeypatch.setenv("DRIVE_INSIGHT_FOLDER_ID", "folder-123")
    yield


class FakeDrive:
    """A Drive client that serves canned listings and canned file text."""

    def __init__(self, listing, texts=None, list_error=None, read_error=None):
        self.listing = list(listing)
        self.texts = dict(texts or {})
        self.list_error = list_error
        self.read_error = read_error
        self.listed = []
        self.read = []

    def list_documents_in_folder(self, folder_id, query_prefix="", max_results=100):
        self.listed.append((folder_id, max_results))
        if self.list_error:
            raise self.list_error
        return list(self.listing)

    def read_file_text(self, file_id, mime_type=None, max_chars=0):
        self.read.append((file_id, max_chars))
        if self.read_error:
            raise self.read_error
        body = self.texts.get(file_id, "")
        return body[:max_chars] if max_chars else body


def _drive(monkeypatch, **kwargs) -> FakeDrive:
    """Serve a canned Drive instead of building a real client."""
    fake = FakeDrive(**kwargs)
    monkeypatch.setattr(DriveInsightAdvisor, "_client", lambda self: fake)
    return fake


# --- registration, manifest and privacy --------------------------------------


def test_the_advisor_is_on_the_live_roster():
    from ai_assistant.advisors import all_advisors

    assert "drive_insight" in [advisor.key for advisor in all_advisors()]


def test_the_manifest_runs_it_only_when_drive_changed():
    """Its material is the FOLDER, so a daily slot would burn quota for nothing."""
    assert status_report.advisor_trigger("drive_insight") == status_report.TRIGGER_DATA
    assert status_report.advisor_data_owner("drive_insight") == "drive_files"


def test_the_advisor_declares_itself_private():
    assert DriveInsightAdvisor.private is True


def test_the_advisor_is_on_the_private_key_safety_net():
    assert "drive_insight" in reports.PRIVATE_ADVISOR_KEYS


def test_the_advisor_has_its_own_slack_channel():
    from ai_assistant.integrations import slack_setup

    assert "drive_insight" in slack_setup.covered_advisor_keys()


# --- folder resolution --------------------------------------------------------


def test_the_folder_falls_back_to_the_shared_drive_folder(monkeypatch, blank_env):
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "shared-folder")
    assert insight_folder_id() == "shared-folder"


def test_a_dedicated_folder_wins_over_the_shared_one(monkeypatch, blank_env):
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "shared-folder")
    monkeypatch.setenv("DRIVE_INSIGHT_FOLDER_ID", "own-folder")
    assert insight_folder_id() == "own-folder"


def test_no_folder_configured_is_an_empty_string(blank_env):
    assert insight_folder_id() == ""


# --- parse_file ---------------------------------------------------------------


def test_parse_file_reads_a_normal_upload():
    parsed = parse_file(_entry("Vendor teklifi.pdf", "abc"))
    assert parsed is not None
    assert parsed.title == "Vendor teklifi.pdf"
    assert parsed.file_id == "abc"
    assert parsed.kind == "PDF"
    assert parsed.link.startswith("https://drive.google.com/")


def test_parse_file_drops_sub_folders():
    """The listing query returns folders too; a folder is not a document."""
    entry = _entry("2026-08-06", mimeType=insight_module.FOLDER_MIME)
    assert parse_file(entry) is None


def test_parse_file_drops_the_assistants_own_report_archive():
    """Otherwise the advisor analyses yesterday's briefing and calls it a finding."""
    assert parse_file(_entry("market_intelligence.md")) is None
    assert parse_file(_entry("sre_watchdog.md")) is None


def test_a_users_own_markdown_note_is_not_mistaken_for_a_report():
    assert is_own_report("toplanti-notlari.md") is False
    assert parse_file(_entry("toplanti-notlari.md")) is not None


def test_parse_file_survives_junk_records():
    assert parse_file({}) is None
    assert parse_file({"id": "x"}) is None
    assert parse_file("not a dict") is None


def test_an_unknown_mime_type_is_reported_as_itself():
    """ "Bilmiyorum" beats a wrong guess in a prompt that forbids invention."""
    parsed = parse_file(_entry("garip.xyz", mimeType="application/x-weird"))
    assert parsed.kind == "application/x-weird"


# --- is_recent ----------------------------------------------------------------


def test_is_recent_accepts_a_file_inside_the_window():
    assert is_recent(_stamp(2), 7) is True


def test_is_recent_rejects_an_old_file():
    assert is_recent(_stamp(30), 7) is False


def test_an_unparsable_timestamp_counts_as_recent():
    """Missing a genuinely new file is worse than one extra ledger entry."""
    assert is_recent("", 7) is True
    assert is_recent("dün", 7) is True


# --- graceful degradation -----------------------------------------------------


def test_skipped_without_google_credentials(blank_env):
    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == SKIP_NO_GOOGLE


def test_skipped_without_a_folder(monkeypatch, blank_env):
    monkeypatch.setattr(insight_module.google_auth, "google_configured", lambda: True)
    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == SKIP_NO_FOLDER


def test_an_unreadable_folder_is_skipped_not_crashed(monkeypatch, google_ok):
    _drive(monkeypatch, listing=[], list_error=RuntimeError("403 yetkisiz"))
    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "403 yetkisiz" in briefing.text


def test_skipped_when_nothing_new_landed(monkeypatch, google_ok):
    """An empty folder must not reach the model at all."""
    _drive(monkeypatch, listing=[])
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    called = []
    monkeypatch.setattr(
        insight_module.llm, "generate_text", lambda *a, **k: called.append(1)
    )

    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "yeni dosya yok" in briefing.text.lower()
    assert not called


def test_only_old_files_means_nothing_new(monkeypatch, google_ok):
    _drive(monkeypatch, listing=[_entry("eski rapor.pdf", modifiedTime=_stamp(40))])
    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert str(DEFAULT_LOOKBACK_DAYS) in briefing.text


def test_no_analysis_is_invented_without_a_model_key(monkeypatch, google_ok):
    """The whole point of the section is READING the file. No key, no claims."""
    _drive(
        monkeypatch,
        listing=[_entry("Vendor teklifi.pdf", "abc")],
        texts={"abc": "Yıllık bedel 1.200.000 TL."},
    )
    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == SKIP_NO_LLM
    # Not one word of the document leaked into the skip note either.
    assert "1.200.000" not in briefing.text


def test_a_failing_llm_is_a_failure_not_a_crash(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _drive(monkeypatch, listing=[_entry("Vendor teklifi.pdf", "abc")])

    def boom(*_args, **_kwargs):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(insight_module.llm, "generate_text", boom)

    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_FAILED
    assert "kota doldu" in briefing.text


# --- the happy path -----------------------------------------------------------


def test_a_new_file_becomes_a_briefing(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _drive(
        monkeypatch,
        listing=[_entry("Vendor teklifi.pdf", "abc")],
        texts={"abc": "Yıllık bedel 1.200.000 TL."},
    )
    seen = {}

    def fake_generate(system_prompt, user_prompt, **kwargs):
        seen["user"] = user_prompt
        seen["kwargs"] = kwargs
        return "Analiz gövdesi."

    monkeypatch.setattr(insight_module.llm, "generate_text", fake_generate)

    briefing = DriveInsightAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert briefing.private is True
    assert briefing.text.startswith("Analiz gövdesi.")
    assert CAVEAT in briefing.text
    # The FACTS reached the model: name, type and the document's own text.
    assert "Vendor teklifi.pdf" in seen["user"]
    assert "PDF" in seen["user"]
    assert "1.200.000" in seen["user"]
    # Structured inference: nothing to reason out, so no billed thinking pass.
    assert seen["kwargs"]["thinking_budget"] == 0


def test_the_batched_section_carries_the_same_facts(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _drive(
        monkeypatch,
        listing=[_entry("Q3 butce.xlsx", "b1")],
        texts={"b1": "Personel gideri %12 arttı."},
    )
    section = DriveInsightAdvisor().batch_section()
    assert section is not None
    assert section.key == "drive_insight"
    assert "Q3 butce.xlsx" in section.user_prompt
    assert "Personel gideri %12 arttı." in section.user_prompt


def test_no_batch_section_without_a_model_key(monkeypatch, google_ok):
    fake = _drive(monkeypatch, listing=[_entry("Vendor teklifi.pdf", "abc")])
    assert DriveInsightAdvisor().batch_section() is None
    # …and Drive was never even listed: no key means no work at all.
    assert not fake.listed


def test_no_batch_section_when_there_is_nothing_new(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _drive(monkeypatch, listing=[])
    assert DriveInsightAdvisor().batch_section() is None


def test_an_unreadable_file_is_still_reported_by_name(monkeypatch, google_ok):
    """A file that landed matters even when the scope cannot open it."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _drive(
        monkeypatch,
        listing=[_entry("Gizli sozlesme.pdf", "abc")],
        read_error=RuntimeError("insufficient scope"),
    )
    section = DriveInsightAdvisor().batch_section()
    assert section is not None
    assert "Gizli sozlesme.pdf" in section.user_prompt
    assert METADATA_ONLY_NOTE in section.user_prompt


def test_the_content_budget_is_passed_to_drive(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("DRIVE_INSIGHT_MAX_CHARS", "50")
    fake = _drive(
        monkeypatch,
        listing=[_entry("uzun.pdf", "abc")],
        texts={"abc": "x" * 500},
    )
    section = DriveInsightAdvisor().batch_section()
    assert fake.read == [("abc", 50)]
    assert "x" * 51 not in section.user_prompt


# --- the file cap and the ledger ----------------------------------------------


def test_at_most_max_files_are_analysed_in_one_run(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("DRIVE_INSIGHT_MAX_FILES", "2")
    _drive(
        monkeypatch,
        listing=[_entry(f"dosya-{i}.pdf", f"id{i}") for i in range(5)],
    )
    advisor = DriveInsightAdvisor()
    section = advisor.batch_section()
    assert advisor.new_finding_count() == 2
    assert "dosya-0.pdf" in section.user_prompt
    assert "dosya-1.pdf" in section.user_prompt
    assert "dosya-2.pdf" not in section.user_prompt


def test_the_files_the_cap_cut_off_are_reported_on_the_next_run(monkeypatch, google_ok):
    """Staging the whole listing would burn files nobody was ever told about."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("DRIVE_INSIGHT_MAX_FILES", "2")
    listing = [_entry(f"dosya-{i}.pdf", f"id{i}") for i in range(4)]
    _drive(monkeypatch, listing=listing)

    first = DriveInsightAdvisor().batch_section()
    assert "dosya-0.pdf" in first.user_prompt
    memory.shared().commit()

    second = DriveInsightAdvisor().batch_section()
    assert "dosya-0.pdf" not in second.user_prompt
    assert "dosya-2.pdf" in second.user_prompt
    assert "dosya-3.pdf" in second.user_prompt


def test_a_file_already_reported_is_never_analysed_twice(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _drive(monkeypatch, listing=[_entry("Vendor teklifi.pdf", "abc")])

    assert DriveInsightAdvisor().batch_section() is not None
    memory.shared().commit()

    repeat = DriveInsightAdvisor()
    assert repeat.batch_section() is None
    assert repeat.generate_briefing().status == STATUS_SKIPPED


def test_new_finding_count_reflects_what_will_be_reported(monkeypatch, google_ok):
    _drive(monkeypatch, listing=[_entry("a.pdf", "a"), _entry("b.pdf", "b")])
    advisor = DriveInsightAdvisor()
    assert advisor.new_finding_count() == 2
    # Gathering is memoised: asking twice must not double the ledger's count.
    assert advisor.new_finding_count() == 2
    assert memory.shared().new_count("drive_insight") == 2


def test_the_folder_is_read_once_per_run(monkeypatch, google_ok):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    fake = _drive(monkeypatch, listing=[_entry("Vendor teklifi.pdf", "abc")])
    advisor = DriveInsightAdvisor()
    advisor.batch_section()
    advisor.new_finding_count()
    advisor.batch_section()
    assert len(fake.listed) == 1
