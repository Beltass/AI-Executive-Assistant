"""Tests for the dashboard's status report producer.

The status file is committed to a PUBLIC repository and read by a static site,
so these tests pin the three things that actually matter: the shape is valid
JSON the dashboard can render, no secret and no briefing content can leak into
it, and writing it can never raise (a monitoring artefact must never cost us
the briefing it monitors).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from ai_assistant import status_report
from ai_assistant.advisors import Briefing
from ai_assistant.integrations import (
    CheckResult,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
)
from ai_assistant.operations_manager import Supervision

FIXED_NOW = datetime(2026, 7, 30, 7, 4, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """No secrets, no inherited state file, no accidental writes to the repo."""
    for name in status_report.SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(status_report.STATUS_FILE_ENV, raising=False)
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(tmp_path / "missing.json"))


def _supervision() -> Supervision:
    return Supervision(
        briefings=[
            Briefing(key="weather", title="Hava Durumu", status=STATUS_OK, text="x" * 120),
            Briefing(
                key="career_development",
                title="Kariyer Gelişimi",
                status=STATUS_FAILED,
                text="gemini hatası: HTTP 429",
            ),
            Briefing(
                key="anka_bridge",
                title="Anka Köprüsü",
                status=STATUS_SKIPPED,
                text="ANKA_WEBHOOK_URL tanımlı değil",
            ),
        ]
    )


# --- shape ------------------------------------------------------------------


def test_writes_valid_json_with_expected_shape(tmp_path):
    target = tmp_path / "frontend" / "status.json"
    path = status_report.write_status_report(
        _supervision(),
        slack_result=CheckResult("Slack Notifier", STATUS_OK, "webhook — HTTP 200"),
        duration_seconds=12.34,
        path=str(target),
        now=FIXED_NOW,
    )

    assert path == str(target)
    data = json.loads(target.read_text(encoding="utf-8"))

    assert data["generated_at"].startswith("2026-07-30T07:04:12")
    # 07:04 UTC is 10:04 in Istanbul — the time the user actually thinks in.
    assert data["generated_at_istanbul"] == "30.07.2026 10:04"

    run = data["run"]
    assert (run["ok"], run["failed"], run["skipped"], run["total"]) == (1, 1, 1, 3)
    assert run["conclusion"] == "partial"
    assert run["duration_seconds"] == 12.3
    assert set(run["batch"]) >= {"used", "sections_requested", "sections_produced", "model"}

    assert data["slack"]["status"] == STATUS_OK
    assert "accountability" in data
    assert len(data["history"]) == 1
    assert data["history"][0]["ok"] == 1


def test_advisor_entries_carry_name_status_category_and_size(tmp_path):
    target = tmp_path / "status.json"
    status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)
    advisors = {a["id"]: a for a in json.loads(target.read_text(encoding="utf-8"))["advisors"]}

    weather = advisors["weather"]
    assert weather["name"] == "Hava Durumu"
    assert weather["status"] == STATUS_OK
    assert weather["category"] == status_report.CATEGORY_OPS
    assert weather["content_length"] == 120
    assert weather["emoji"]

    assert advisors["career_development"]["category"] == status_report.CATEGORY_CAREER
    assert advisors["career_development"]["detail"] == "gemini hatası: HTTP 429"
    assert advisors["anka_bridge"]["status"] == STATUS_SKIPPED


def test_ok_advisor_content_is_never_written(tmp_path):
    secret_text = "Bugün İstanbul'da 31 derece — ÇOK ÖZEL BRİFİNG METNİ"
    supervision = Supervision(
        briefings=[Briefing(key="weather", title="Hava", status=STATUS_OK, text=secret_text)]
    )
    target = tmp_path / "status.json"
    status_report.write_status_report(supervision, path=str(target), now=FIXED_NOW)

    raw = target.read_text(encoding="utf-8")
    assert "ÇOK ÖZEL" not in raw
    entry = json.loads(raw)["advisors"][0]
    assert entry["detail"] == ""
    assert entry["content_length"] == len(secret_text)


def test_every_advisor_key_has_presentation_metadata():
    from ai_assistant.advisors import all_advisors

    for advisor in all_advisors():
        assert advisor.key in status_report.ADVISOR_META, advisor.key
        meta = status_report.ADVISOR_META[advisor.key]
        assert meta["emoji"], advisor.key
        assert meta["title"], advisor.key
        assert meta["category"] in {
            status_report.CATEGORY_CAREER,
            status_report.CATEGORY_FAMILY,
            status_report.CATEGORY_SECTOR,
            status_report.CATEGORY_GROWTH,
            status_report.CATEGORY_OPS,
        }, advisor.key


def test_retired_advisors_are_marked_retired_rather_than_deleted():
    """The manifest catalogues EVERY advisor; ``status`` says who still runs.

    The table used to hold live advisors only, which meant "is this module
    still in service?" had no answer anywhere in the codebase. It now holds all
    of them, so the answer is a field rather than an archaeology exercise — and
    the running roster is the ``live`` subset.
    """
    from ai_assistant.advisors import all_advisors

    live = set(status_report.live_advisor_keys())
    assert {a.key for a in all_advisors()} <= live
    assert "weather" in status_report.retired_advisor_keys()
    assert status_report.is_live("weather") is False
    assert status_report.is_live("sre_watchdog") is True


# --- secrets ----------------------------------------------------------------


def test_sanitize_redacts_configured_secret_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTOPSECRETVALUE123456")
    cleaned = status_report.sanitize("gemini hatası: key AIzaSyTOPSECRETVALUE123456 reddedildi")
    assert "AIzaSyTOPSECRETVALUE123456" not in cleaned
    assert status_report.REDACTED in cleaned


@pytest.mark.parametrize(
    "secret",
    [
        "AIzaSyA1B2C3D4E5F6G7H8I9J0",
        "sk-proj-abcdefghijklmnopqrstuvwxyz",
        "xoxb-1234567890-abcdefghij",
        "ghp_abcdefghijklmnopqrstuvwxyz012345",
        "https://hooks.slack.com/services/T00/B00/XXXXXXXXXXXX",
        "api_key=supersecretvalue",
    ],
)
def test_sanitize_redacts_wellknown_key_shapes(secret):
    assert secret not in status_report.sanitize("hata: " + secret)


def test_secrets_never_reach_the_written_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-9999999999-zzzzzzzzzz")
    supervision = Supervision(
        briefings=[
            Briefing(
                key="career_hr",
                title="Kariyer",
                status=STATUS_FAILED,
                text="çağrı reddedildi (token xoxb-9999999999-zzzzzzzzzz)",
            )
        ]
    )
    target = tmp_path / "status.json"
    status_report.write_status_report(
        supervision,
        slack_result=CheckResult("Slack", STATUS_FAILED, "xoxb-9999999999-zzzzzzzzzz geçersiz"),
        path=str(target),
        now=FIXED_NOW,
    )

    raw = target.read_text(encoding="utf-8")
    assert "xoxb-9999999999-zzzzzzzzzz" not in raw
    assert raw.count(status_report.REDACTED) >= 2


def test_sanitize_caps_runaway_messages():
    cleaned = status_report.sanitize("x" * 5000)
    assert len(cleaned) <= status_report.MAX_DETAIL_CHARS + 1


# --- history ----------------------------------------------------------------


def test_history_is_preserved_and_appended(tmp_path):
    target = tmp_path / "status.json"
    target.write_text(
        json.dumps({"history": [{"at": "2026-07-28T07:00:00+00:00", "ok": 9}]}),
        encoding="utf-8",
    )
    status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)

    history = json.loads(target.read_text(encoding="utf-8"))["history"]
    assert len(history) == 2
    assert history[0]["ok"] == 9  # the old entry survived, oldest first
    assert history[-1]["at"].startswith("2026-07-30")


def test_history_is_trimmed_to_the_rolling_window(tmp_path):
    target = tmp_path / "status.json"
    old = [{"at": "2026-01-%02dT07:00:00+00:00" % (i + 1), "ok": i} for i in range(40)]
    target.write_text(json.dumps({"history": old}), encoding="utf-8")

    status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)
    history = json.loads(target.read_text(encoding="utf-8"))["history"]

    assert len(history) == status_report.HISTORY_LIMIT
    assert history[-1]["at"].startswith("2026-07-30")  # newest kept
    assert history[0]["ok"] == 40 - status_report.HISTORY_LIMIT + 1  # oldest dropped


def test_corrupt_previous_file_is_ignored_not_fatal(tmp_path):
    target = tmp_path / "status.json"
    target.write_text("{not json at all", encoding="utf-8")

    assert status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)
    assert json.loads(target.read_text(encoding="utf-8"))["history"]


# --- accountability ---------------------------------------------------------


def test_accountability_snapshot_read_from_state_file(tmp_path, monkeypatch):
    state = tmp_path / "accountability.json"
    state.write_text(
        json.dumps({"streak": 7, "last_date": "2026-07-30", "last_tasks": ["a", "b", "c"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state))

    target = tmp_path / "status.json"
    status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)
    acc = json.loads(target.read_text(encoding="utf-8"))["accountability"]

    assert acc == {
        "available": True,
        "streak": 7,
        "today_task_count": 3,
        "last_date": "2026-07-30",
        # The task TEXT is published now, so the dashboard's İşler tab has
        # something to render. Everything in it already lives in
        # ``frontend/reports/`` — except a private advisor's, which is filtered
        # out below.
        "tasks": ["a", "b", "c"],
        "history_days": 0,
    }


def test_a_private_advisors_task_is_never_published(tmp_path, monkeypatch):
    """The coach collects EVERY advisor's task, including the private one.

    The Gmail/Calendar briefing can name a person or a meeting, and this file
    is committed to a public repository, so its task must not travel with the
    rest.
    """
    state = tmp_path / "accountability.json"
    state.write_text(
        json.dumps(
            {
                "streak": 2,
                "last_date": "2026-07-30",
                "last_tasks": [
                    "*Liderlik Koçu* — bir görevi delege et",
                    "*Gün Başı Operasyon Brifingi* — Ayşe ile 14:00 toplantısına hazırlan",
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state))

    supervision = _supervision()
    supervision.briefings.append(
        Briefing(
            key="daily_ops_briefing",
            title="Gün Başı Operasyon Brifingi",
            status=STATUS_OK,
            text="kişisel",
            private=True,
        )
    )

    target = tmp_path / "status.json"
    status_report.write_status_report(supervision, path=str(target), now=FIXED_NOW)
    raw = target.read_text(encoding="utf-8")
    acc = json.loads(raw)["accountability"]

    assert acc["tasks"] == ["*Liderlik Koçu* — bir görevi delege et"]
    assert acc["today_task_count"] == 1
    assert "Ayşe" not in raw


def test_published_tasks_are_scrubbed_of_secrets(tmp_path, monkeypatch):
    secret = "AIzaSyFAKEKEYFAKEKEYFAKEKEYFAKEKEY123"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    state = tmp_path / "accountability.json"
    state.write_text(
        json.dumps({"streak": 1, "last_tasks": [f"*X* — key={secret} ile dene"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state))

    target = tmp_path / "status.json"
    status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)
    assert secret not in target.read_text(encoding="utf-8")


def test_missing_accountability_state_is_a_fresh_start(tmp_path):
    target = tmp_path / "status.json"
    status_report.write_status_report(_supervision(), path=str(target), now=FIXED_NOW)
    acc = json.loads(target.read_text(encoding="utf-8"))["accountability"]

    assert acc["available"] is False
    assert acc["streak"] == 0


# --- fail-safety ------------------------------------------------------------


def test_unwritable_path_returns_none_and_never_raises(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    # Writing "inside" a regular file is an OSError at makedirs/open time.
    assert status_report.write_status_report(
        _supervision(), path=str(blocker / "deep" / "status.json"), now=FIXED_NOW
    ) is None


def test_broken_supervision_object_never_raises(tmp_path):
    class Broken:
        @property
        def briefings(self):
            raise RuntimeError("boom")

    target = tmp_path / "status.json"
    assert status_report.write_status_report(Broken(), path=str(target)) is None


def test_default_path_and_env_override(monkeypatch):
    assert status_report.status_file_path() == status_report.DEFAULT_STATUS_FILE
    monkeypatch.setenv(status_report.STATUS_FILE_ENV, "custom/where.json")
    assert status_report.status_file_path() == "custom/where.json"


def test_conclusions_cover_every_outcome():
    def conclusion(ok, failed, skipped):
        return status_report._conclusion(
            {STATUS_OK: ok, STATUS_FAILED: failed, STATUS_SKIPPED: skipped}
        )

    assert conclusion(5, 0, 1) == STATUS_OK
    assert conclusion(3, 2, 0) == "partial"
    assert conclusion(0, 4, 0) == STATUS_FAILED
    assert conclusion(0, 0, 13) == "idle"


# --- integration with the notifier -----------------------------------------


def test_notifier_writes_the_status_file(tmp_path, monkeypatch):
    """A normal run must leave a status file behind, without changing its exit code."""
    from ai_assistant.notifiers import slack_notifier

    target = tmp_path / "frontend" / "status.json"
    monkeypatch.setenv(status_report.STATUS_FILE_ENV, str(target))
    for name in ("SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "SLACK_CHANNEL"):
        monkeypatch.delenv(name, raising=False)

    supervision = _supervision()
    supervision.briefings = [b for b in supervision.briefings if b.status != STATUS_FAILED]
    monkeypatch.setattr(
        slack_notifier,
        "build_digest",
        lambda: __import__(
            "ai_assistant.daily_digest", fromlist=["build_digest"]
        ).build_digest(supervision),
    )

    assert slack_notifier.main() == 0
    assert os.path.exists(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["slack"]["status"] == STATUS_SKIPPED
    assert data["run"]["duration_seconds"] is not None
