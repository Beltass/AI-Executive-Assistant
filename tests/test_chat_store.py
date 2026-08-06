"""Tests for the chat layer's ON-DISK memory — the thing that makes it work.

Every poll is a NEW PROCESS. The process that showed the menu is dead by the
time the answer arrives, so the cursor, the open orders and the saved templates
only exist if ``.assistant_state/chat_state.json`` is written AND carried over.
That file used to be written by the runner and then thrown away with it: the
cursor was empty on every run, so the poller re-processed the latest human
message and re-posted step one forever, and the user could never reach step two.

The regression test for that bug is
``test_a_second_process_does_not_reprocess_the_same_message``: it runs two
polls, each with its OWN ``ChatStore`` built from the same path, exactly like
two containers reading the same committed file.

Nothing here touches Slack: the client is a stub.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from ai_assistant.chat import poller as poller_mod
from ai_assistant.chat.session import SessionEngine
from ai_assistant.chat.slack_api import SlackMessage
from ai_assistant.chat.store import (
    DEFAULT_STATE_FILE,
    SESSION_TTL_ENV,
    STATE_FILE_ENV,
    ChatStore,
    session_key,
    session_ttl_minutes,
    state_file_path,
)
from ai_assistant.chat.spec import ReportSpec

CHANNEL = "C-CHAT"
USER = "U-BOSS"


@pytest.fixture()
def path(tmp_path):
    return str(tmp_path / "chat_state.json")


class FakeSlack:
    """A Slack channel that serves canned history and records every reply."""

    configured = True

    def __init__(self, messages):
        self.messages = list(messages)
        self.posted = []

    def history(self, channel, oldest="", limit=100):
        after = float(oldest) if oldest else 0.0
        return [m for m in self.messages if float(m.ts) > after]

    def post(self, channel, text):
        self.posted.append(text)
        return "9999.0"


def _message(ts, text):
    return SlackMessage(ts=ts, user=USER, text=text, channel=CHANNEL)


# --- the file ----------------------------------------------------------------


def test_the_default_path_is_the_committed_one(monkeypatch):
    """The workflow commits exactly this path back to the repository."""
    monkeypatch.delenv(STATE_FILE_ENV, raising=False)
    assert state_file_path() == DEFAULT_STATE_FILE
    assert DEFAULT_STATE_FILE == ".assistant_state/chat_state.json"


def test_the_path_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv(STATE_FILE_ENV, str(tmp_path / "elsewhere.json"))
    assert state_file_path().endswith("elsewhere.json")


def test_a_missing_file_is_an_empty_start_not_a_crash(path):
    store = ChatStore(path)
    assert store.cursors == {}
    assert store.sessions == {}
    assert store.cursor(CHANNEL) == ""


def test_a_corrupt_file_is_an_empty_start_not_a_crash(tmp_path):
    broken = tmp_path / "chat_state.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    store = ChatStore(str(broken))
    assert store.cursors == {}
    # And it can still be written over.
    store.set_cursor(CHANNEL, "10.0")
    assert store.save() is True
    assert ChatStore(str(broken)).cursor(CHANNEL) == "10.0"


def test_saving_creates_the_state_directory(tmp_path):
    nested = tmp_path / "deep" / "state" / "chat_state.json"
    store = ChatStore(str(nested))
    store.set_cursor(CHANNEL, "1.0")
    assert store.save() is True
    assert nested.exists()


def test_the_written_file_is_readable_json_with_a_version(path):
    store = ChatStore(path)
    store.set_cursor(CHANNEL, "5.0")
    store.save()
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["state_version"] == 1
    assert payload["cursors"] == {CHANNEL: "5.0"}
    assert "updated_at" in payload


def test_an_unwritable_path_is_reported_not_raised(tmp_path):
    store = ChatStore(str(tmp_path / "chat_state.json"))
    store.path = str(tmp_path / "missing-dir\x00" / "x.json")
    assert store.save() is False


# --- cursor round-trip -------------------------------------------------------


def test_the_cursor_survives_a_fresh_process(path):
    first = ChatStore(path)
    first.set_cursor(CHANNEL, "1700000000.000100")
    first.save()

    second = ChatStore(path)
    assert second.cursor(CHANNEL) == "1700000000.000100"


def test_the_cursor_never_moves_backwards(path):
    store = ChatStore(path)
    store.set_cursor(CHANNEL, "200.0")
    store.set_cursor(CHANNEL, "100.0")
    assert store.cursor(CHANNEL) == "200.0"


def test_cursors_are_per_channel(path):
    store = ChatStore(path)
    store.set_cursor(CHANNEL, "10.0")
    store.set_cursor("C-OTHER", "20.0")
    store.save()
    reloaded = ChatStore(path)
    assert reloaded.cursor(CHANNEL) == "10.0"
    assert reloaded.cursor("C-OTHER") == "20.0"


# --- sessions round-trip -----------------------------------------------------


def test_a_session_survives_a_fresh_process(path):
    first = ChatStore(path)
    first.put_session(
        CHANNEL, USER, {"step": "donem", "updated_at": "2026-08-04T10:00:00"}
    )
    first.save()

    second = ChatStore(path)
    assert second.get_session(CHANNEL, USER) == {
        "step": "donem",
        "updated_at": "2026-08-04T10:00:00",
    }


def test_two_users_in_one_channel_do_not_share_an_order(path):
    store = ChatStore(path)
    store.put_session(CHANNEL, USER, {"step": "donem"})
    store.put_session(CHANNEL, "U-OTHER", {"step": "kaynak"})
    store.save()
    reloaded = ChatStore(path)
    assert reloaded.get_session(CHANNEL, USER)["step"] == "donem"
    assert reloaded.get_session(CHANNEL, "U-OTHER")["step"] == "kaynak"
    assert session_key(CHANNEL, USER) != session_key(CHANNEL, "U-OTHER")


def test_dropping_a_session_is_idempotent(path):
    store = ChatStore(path)
    store.put_session(CHANNEL, USER, {"step": "donem"})
    assert store.drop_session(CHANNEL, USER) is True
    assert store.drop_session(CHANNEL, USER) is False


def test_a_stale_session_is_pruned(path, monkeypatch):
    monkeypatch.setenv(SESSION_TTL_ENV, "60")
    store = ChatStore(path)
    stale = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    fresh = datetime.now().isoformat(timespec="seconds")
    store.put_session(CHANNEL, USER, {"updated_at": stale})
    store.put_session(CHANNEL, "U-FRESH", {"updated_at": fresh})

    dropped = store.prune_sessions()

    assert dropped == [session_key(CHANNEL, USER)]
    assert store.get_session(CHANNEL, "U-FRESH") is not None


def test_a_broken_ttl_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(SESSION_TTL_ENV, "abc")
    assert session_ttl_minutes() == 120
    monkeypatch.setenv(SESSION_TTL_ENV, "-5")
    assert session_ttl_minutes() == 120


# --- templates and last-used round-trip --------------------------------------


def test_templates_and_last_choices_survive_a_fresh_process(path):
    first = ChatStore(path)
    first.user_templates(USER)["haftalik"] = {"name": "haftalık", "spec": {}}
    first.remember_source(USER, {"kind": "drive", "id": "file-1"})
    first.remember_spec(USER, ReportSpec(source="file-1").as_dict())
    first.save()

    second = ChatStore(path)
    assert second.user_templates(USER)["haftalik"]["name"] == "haftalık"
    assert second.last_source(USER)["id"] == "file-1"
    assert second.last_spec(USER)["source"] == "file-1"


# --- THE regression: a second process must not repeat itself -----------------


def test_a_second_process_does_not_reprocess_the_same_message(path, monkeypatch):
    """Two polls, two ``ChatStore`` objects, one committed file.

    This is the bug the persistence step fixes: without the cursor on disk the
    second run reads the same message again and posts step one a second time,
    which is what the user saw every five minutes forever.
    """
    monkeypatch.setenv(STATE_FILE_ENV, path)
    api = FakeSlack([_message("100.0", "eski"), _message("200.0", "rapor")])

    def _run():
        state = ChatStore(path)
        return poller_mod.run_once(
            client=api,
            store=state,
            engine=SessionEngine(store=state, source_lister=lambda: []),
            channel=CHANNEL,
        )

    first = _run()
    assert first.handled == 1
    said_first = list(api.posted)
    assert said_first  # the menu went out once

    second = _run()
    assert second.read == 0
    assert second.handled == 0
    assert api.posted == said_first  # nothing repeated

    # And the cursor really is on disk, where the workflow commits it from.
    assert ChatStore(path).cursor(CHANNEL) == "200.0"


def test_an_open_order_continues_in_the_next_process(path, monkeypatch):
    """Step two is only reachable because the session was written to disk."""
    monkeypatch.setenv(STATE_FILE_ENV, path)
    api = FakeSlack([_message("100.0", "rapor")])

    state = ChatStore(path)
    poller_mod.run_once(
        client=api,
        store=state,
        engine=SessionEngine(store=state, source_lister=lambda: []),
        channel=CHANNEL,
    )
    assert ChatStore(path).get_session(CHANNEL, USER) is not None

    # Five minutes later, a brand new container answers the menu.
    api.messages.append(_message("300.0", "1"))
    fresh = ChatStore(path)
    report = poller_mod.run_once(
        client=api,
        store=fresh,
        engine=SessionEngine(store=fresh, source_lister=lambda: []),
        channel=CHANNEL,
    )
    assert report.handled == 1
    # The order moved on instead of restarting at step one.
    assert ChatStore(path).get_session(CHANNEL, USER)["step"] != "kaynak"
