"""Tests for the Operations Manager supervisor and the daily digest.

These run offline with no credentials: every advisor should ``skip`` and the
supervisor must produce a well-formed summary without crashing. A simulated
failing advisor must be reported ``failed`` without breaking the run.
"""

from __future__ import annotations

import pytest

from ai_assistant import config
from ai_assistant.advisors import Advisor, Briefing
from ai_assistant.daily_digest import build_digest
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.operations_manager import OperationsManager

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "WEATHER_CITY",
    "WEATHER_COUNTRY",
    "WEATHER_LATITUDE",
    "WEATHER_LONGITUDE",
    "JOB_KEYWORDS",
    "JOB_LOCATION",
    "USER_SECTOR",
    "AI_NEWS_RSS_URL",
    "SECTOR_NEWS_RSS_URL",
    "ANKA_WEBHOOK_URL",
    "ANKA_API_URL",
    "ANKA_API_KEY",
    "ANKA_HTTP_METHOD",
    "BANKING_NEWS_RSS_URL",
    "ACCOUNTABILITY_STATE_FILE",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
    "GOOGLE_TOKEN_FILE",
]


@pytest.fixture()
def no_config(monkeypatch):
    """Simulate a completely blank setup: no env vars AND no built-in defaults.

    ``config.DEFAULT_SETTINGS`` normally pre-fills non-secret settings (city,
    sector, job keywords, RSS feeds) so the whole team is active out of the
    box; clearing it here keeps these tests offline and lets them assert the
    "nothing configured at all" invariant.
    """
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    yield


class _CrashingAdvisor(Advisor):
    key = "boom"
    title = "Patlayan Danışman"

    def _generate(self) -> Briefing:
        raise RuntimeError("intentional boom")


def test_manager_runs_all_advisors_offline(no_config):
    supervision = OperationsManager().run()
    assert [b.key for b in supervision.briefings] == [
        "morning_operations",
        "communications_calendar",
        "meeting_prep",
        "career_development",
        "market_intelligence",
        "complaint_radar",
        "linkedin_coach",
        "social_media_coach",
        "personal_assistant",
        "data_analyst",
        "ai_innovation",
        "kids_development",
        "executive_coaching",
        "work_analyst",
        "operations_director",
        "sre_watchdog",
    ]
    for b in supervision.briefings:
        assert b.status in {STATUS_OK, STATUS_FAILED, STATUS_SKIPPED}


def test_manager_all_skipped_offline(no_config):
    """With nothing configured every advisor skips — except the work analyst.

    It consolidates the others rather than calling out itself, so it returns a
    successful "no data yet" briefing even offline.
    """
    supervision = OperationsManager().run()
    counts = supervision.counts
    assert counts[STATUS_FAILED] == 0
    skipped = {b.key for b in supervision.briefings if b.status == STATUS_SKIPPED}
    assert skipped == {b.key for b in supervision.briefings} - {"work_analyst"}
    assert counts[STATUS_SKIPPED] == len(supervision.briefings) - 1
    assert counts[STATUS_OK] == 1
    total = counts[STATUS_OK] + counts[STATUS_FAILED] + counts[STATUS_SKIPPED]
    assert total == len(supervision.briefings)
    assert "skipped" in supervision.summary_line()


def test_failing_advisor_is_isolated(no_config):
    manager = OperationsManager(advisors=[_CrashingAdvisor()])
    supervision = manager.run()
    assert len(supervision.briefings) == 1
    assert supervision.briefings[0].status == STATUS_FAILED
    assert supervision.counts[STATUS_FAILED] == 1
    assert supervision.failures


def test_failure_does_not_break_other_advisors(no_config):
    from ai_assistant.advisors.weather import WeatherAdvisor

    manager = OperationsManager(advisors=[_CrashingAdvisor(), WeatherAdvisor()])
    supervision = manager.run()
    statuses = [b.status for b in supervision.briefings]
    assert STATUS_FAILED in statuses
    assert STATUS_SKIPPED in statuses  # weather still ran and skipped


def test_register_adds_advisor(no_config):
    manager = OperationsManager(advisors=[])
    manager.register(_CrashingAdvisor())
    assert len(manager.advisors) == 1


def test_build_digest_offline(no_config):
    digest = build_digest()
    assert digest.text
    assert "Günlük Brifing" in digest.text
    assert "Operasyon Yöneticisi" in digest.text
    assert digest.counts[STATUS_FAILED] == 0


# --- Integration distribution: the log must tell the TRUTH -------------------
#
# Every advisor used to log "Asana senkronizasyonu başarılı" even with no
# ASANA_TOKEN anywhere, which is exactly what hid the fact that the secret was
# never passed to the workflow at all. These pin the three honest states:
# unconfigured -> skip (naming the missing setting), ran-but-did-nothing ->
# say so, and success ONLY when work really happened.

_BRIEFING = Briefing(
    key="boom", title="Patlayan Danışman", status=STATUS_OK, text="metin"
)


@pytest.fixture()
def no_integrations(monkeypatch):
    """No Asana and no Drive credentials in the environment."""
    for var in ("ASANA_TOKEN", "ASANA_WORKSPACE_ID", "GOOGLE_DRIVE_FOLDER_ID"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_asana_sync_skipped_without_token(no_integrations):
    status = OperationsManager(advisors=[])._sync_to_asana(
        "boom", "Patlayan Danışman", _BRIEFING
    )
    assert status.startswith("skipped")
    assert "ASANA_TOKEN" in status


def test_asana_sync_skipped_without_workspace(no_integrations, monkeypatch):
    monkeypatch.setenv("ASANA_TOKEN", "tok")
    status = OperationsManager(advisors=[])._sync_to_asana(
        "boom", "Patlayan Danışman", _BRIEFING
    )
    assert status.startswith("skipped")
    assert "ASANA_WORKSPACE_ID" in status


def test_drive_archive_skipped_without_folder(no_integrations):
    status = OperationsManager(advisors=[])._archive_to_drive(
        "boom", "Patlayan Danışman", _BRIEFING, "2026-08-04"
    )
    assert status.startswith("skipped")
    assert "GOOGLE_DRIVE_FOLDER_ID" in status


def test_unconfigured_integration_logs_skip_not_success(no_integrations, caplog):
    """The headline regression: no credentials must NOT read as success."""
    manager = OperationsManager(advisors=[])
    with caplog.at_level("INFO"):
        manager._distribute_results(
            "boom", "Patlayan Danışman", _BRIEFING, "2026-08-04"
        )

    text = caplog.text
    assert "Asana senkronizasyonu başarılı" not in text
    assert "Google Drive arşivlemesi başarılı" not in text
    assert "Asana senkronizasyonu atlandı" in text
    assert "ASANA_TOKEN" in text
    assert "Google Drive arşivlemesi atlandı" in text
    assert "GOOGLE_DRIVE_FOLDER_ID" in text

    status = manager.distribution_status["boom"]
    assert status["asana"].startswith("skipped")
    assert status["drive"].startswith("skipped")


def test_integration_that_did_nothing_says_so(caplog, monkeypatch):
    manager = OperationsManager(advisors=[])
    monkeypatch.setattr(
        manager, "_sync_to_asana", lambda *a, **k: "no-op: yeni görev yok"
    )
    monkeypatch.setattr(
        manager, "_archive_to_drive", lambda *a, **k: "no-op: belge yüklenmedi"
    )
    with caplog.at_level("INFO"):
        manager._distribute_results(
            "boom", "Patlayan Danışman", _BRIEFING, "2026-08-04"
        )

    assert "Asana senkronizasyonu başarılı" not in caplog.text
    assert "Asana senkronizasyonu çalıştı ama hiçbir iş yapmadı" in caplog.text
    assert "Google Drive arşivlemesi çalıştı ama hiçbir iş yapmadı" in caplog.text


def test_success_is_logged_only_when_work_happened(caplog, monkeypatch):
    manager = OperationsManager(advisors=[])
    monkeypatch.setattr(
        manager, "_sync_to_asana", lambda *a, **k: "success: 1 görev oluşturuldu"
    )
    monkeypatch.setattr(
        manager, "_archive_to_drive", lambda *a, **k: "success: 1 belge yüklendi"
    )
    with caplog.at_level("INFO"):
        manager._distribute_results(
            "boom", "Patlayan Danışman", _BRIEFING, "2026-08-04"
        )

    assert "Asana senkronizasyonu başarılı: Patlayan Danışman" in caplog.text
    assert "Google Drive arşivlemesi başarılı: Patlayan Danışman" in caplog.text


def test_failing_integration_is_reported_as_failure(caplog, monkeypatch):
    manager = OperationsManager(advisors=[])

    def _boom(*_args, **_kwargs):
        raise RuntimeError("intentional boom")

    monkeypatch.setattr(manager, "_sync_to_asana", _boom)
    with caplog.at_level("INFO"):
        manager._distribute_results(
            "boom", "Patlayan Danışman", _BRIEFING, "2026-08-04"
        )

    assert "Asana senkronizasyonu başarısız" in caplog.text
    assert "intentional boom" in caplog.text
    assert manager.distribution_status["boom"]["asana"].startswith("error")


def test_distribution_summary_counts_only_real_successes(caplog):
    from ai_assistant.operations_manager import _save_distribution_status

    with caplog.at_level("INFO"):
        _save_distribution_status(
            {
                "a": {
                    "slack": "routed: C1",
                    "asana": "skipped: ASANA_TOKEN tanımlı değil",
                    "drive": "no-op: belge yüklenmedi",
                },
                "b": {
                    "slack": "routed: C2",
                    "asana": "success: 1 görev oluşturuldu",
                    "drive": "success: 1 belge yüklendi",
                },
            }
        )

    assert '"asana": 1' in caplog.text
    assert '"drive": 1' in caplog.text
    assert '"slack": 0' in caplog.text
