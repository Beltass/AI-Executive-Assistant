"""Tests for the SRE watchdog advisor.

``SreWatchdogAdvisor`` is the thin wrapper that brings ``ai_assistant.watchdog``
— the 24/7 technical watchdog — into the daily briefing. It must:

* be registered LAST in the roster, after every content advisor;
* degrade to ``skipped`` with a TURKISH explanation when the run has left no
  artefacts behind — never a traceback, never a failed run;
* report the machine's verdict with a headline, the findings and their
  remedies when there ARE artefacts;
* stay PRIVATE: it carries the system's internals, which the public dashboard
  never publishes.

Everything here runs OFFLINE: no LLM key, no network (feed probing is switched
off explicitly), no files written outside ``tmp_path``.
"""

from __future__ import annotations

import json

import pytest

from ai_assistant import reports, status_report, watchdog
from ai_assistant.advisors import Briefing, all_advisors
from ai_assistant.advisors import sre_watchdog as watchdog_module
from ai_assistant.advisors.sre_watchdog import SreWatchdogAdvisor
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED


@pytest.fixture()
def no_feeds(monkeypatch):
    """The only check that touches the network stays off in the suite."""
    monkeypatch.setenv("WATCHDOG_CHECK_FEEDS", "false")
    yield


def _write_status(payload: dict) -> None:
    """Write a status document where the advisor will look for it."""
    with open(status_report.status_file_path(), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


# --- registration -----------------------------------------------------------


def test_the_watchdog_is_registered_in_the_live_roster():
    keys = [advisor.key for advisor in all_advisors()]
    assert "sre_watchdog" in keys


def test_the_watchdog_closes_the_roster():
    """It watches the MACHINE, so it comes after every content advisor."""
    roster = all_advisors()
    assert roster[-1].key == "sre_watchdog"
    assert isinstance(roster[-1], SreWatchdogAdvisor)


def test_the_watchdog_has_presentation_metadata():
    meta = status_report.ADVISOR_META["sre_watchdog"]
    assert meta["title"] and meta["emoji"]


# --- privacy ----------------------------------------------------------------


def test_the_watchdog_declares_itself_private():
    assert SreWatchdogAdvisor.private is True


def test_the_watchdog_is_on_the_private_key_safety_net():
    assert "sre_watchdog" in reports.PRIVATE_ADVISOR_KEYS


def test_the_briefing_carries_the_private_flag():
    briefing = SreWatchdogAdvisor().generate_briefing()
    assert briefing.private is True


# --- graceful skip ----------------------------------------------------------


def test_skipped_with_a_turkish_note_without_artefacts(no_feeds):
    """No status file and no metrics history: nothing to watch yet."""
    briefing = SreWatchdogAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "status.json" in briefing.text
    assert "artefakt" in briefing.text


def test_skipped_when_no_check_produces_a_finding(no_feeds, monkeypatch):
    _write_status({"generated_at": "2026-08-01T06:00:00+00:00"})
    monkeypatch.setattr(watchdog_module.watchdog, "run_checks", lambda **_: [])

    briefing = SreWatchdogAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text


def test_unreadable_artefacts_are_an_empty_input(monkeypatch):
    def _boom():
        raise OSError("disk gitti")

    monkeypatch.setattr(watchdog_module.watchdog, "_load_inputs", _boom)
    assert watchdog_module.load_artefacts() == ({}, [])


def test_a_broken_watchdog_never_fails_the_run(no_feeds, monkeypatch):
    """A crash inside the watchdog degrades to ``failed``, never propagates."""
    _write_status({"generated_at": "2026-08-01T06:00:00+00:00"})

    def _boom(**_):
        raise RuntimeError("nöbetçi patladı")

    monkeypatch.setattr(watchdog_module.watchdog, "run_checks", _boom)

    briefing = SreWatchdogAdvisor().generate_briefing()
    assert isinstance(briefing, Briefing)
    assert briefing.status == STATUS_FAILED
    assert briefing.text


# --- the reported verdict ---------------------------------------------------


def test_findings_are_reported_with_their_remedy(no_feeds, monkeypatch):
    _write_status({"generated_at": "2026-08-01T06:00:00+00:00"})
    monkeypatch.setattr(
        watchdog_module.watchdog,
        "run_checks",
        lambda **_: [
            watchdog.Check(
                id="freshness",
                name="Çalıştırma tazeliği",
                severity=watchdog.SEVERITY_CRITICAL,
                detail="Son çalıştırma 40 saat önce.",
                remedy="İş akışını elle tetikle.",
            )
        ],
    )

    briefing = SreWatchdogAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert briefing.text.startswith("**Öne çıkan:**")
    assert "Çalıştırma tazeliği" in briefing.text
    assert "İş akışını elle tetikle." in briefing.text
    assert "panoya yazılmaz" in briefing.text


def test_a_clean_verdict_says_there_is_nothing_to_do():
    text = watchdog_module.format_briefing(
        [
            watchdog.Check(
                id="quota", name="Kota", severity=watchdog.SEVERITY_OK, detail="temiz"
            )
        ]
    )
    assert "yapılacak bir" in text
    assert "1 temiz · 0 uyarı · 0 kritik" in text


def test_only_the_first_findings_are_listed():
    checks = [
        watchdog.Check(
            id=f"check{index}",
            name=f"Kontrol {index}",
            severity=watchdog.SEVERITY_WARN,
            detail=f"bulgu {index}",
            remedy="bak",
        )
        for index in range(watchdog_module.MAX_FINDINGS + 2)
    ]
    text = watchdog_module.format_briefing(checks)
    assert "2 bulgu daha" in text


# --- cost -------------------------------------------------------------------


def test_the_watchdog_never_joins_the_batched_llm_call():
    """It reads files; a model call would be pure cost for no added answer."""
    assert SreWatchdogAdvisor().batch_section() is None


def test_the_watchdog_stays_quiet_on_incremental_runs():
    assert SreWatchdogAdvisor.incremental_source is False
