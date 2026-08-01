"""Tests for the Slack channel provisioning script.

Two properties matter more than anything else here:

* **dry run by default** — running the script must never touch a workspace
  unless ``--apply`` was passed. Nobody gets eleven surprise channels;
* **idempotency** — running it twice must not create anything twice, whether
  the channel is recognised by name or already pinned by id in ``.env``.

Everything is offline: :meth:`SlackApi.call` is the module's single network
seam and every test replaces it.
"""

from __future__ import annotations

import pytest

from ai_assistant.integrations import slack_setup
from ai_assistant.integrations.channel_config import ADVISOR_KEYS


class FakeApi(slack_setup.SlackApi):
    """A Slack workspace in a dict. Records every call, creates real-looking ids."""

    def __init__(self, existing=None, fail=None):
        super().__init__("xoxb-fake")
        #: name -> id
        self.channels = dict(existing or {})
        self.calls = []
        #: method -> Slack error code to raise for it
        self.fail = dict(fail or {})
        self._next = 100

    def call(self, method, payload=None):
        payload = dict(payload or {})
        self.calls.append((method, payload))

        if method in self.fail:
            code = self.fail[method]
            raise slack_setup.SlackApiError(
                method, code, slack_setup.explain(method, {"error": code, "needed": "channels:manage"})
            )

        if method == "auth.test":
            return {"ok": True, "team": "Acme", "user": "ai-asistan"}
        if method == "conversations.list":
            return {
                "ok": True,
                "channels": [
                    {"id": cid, "name": name} for name, cid in self.channels.items()
                ],
                "response_metadata": {"next_cursor": ""},
            }
        if method == "conversations.create":
            name = payload["name"]
            if name in self.channels:
                raise slack_setup.SlackApiError(method, "name_taken", "zaten var")
            self._next += 1
            cid = f"C{self._next:09d}"
            self.channels[name] = cid
            return {"ok": True, "channel": {"id": cid, "name": name}}
        if method in ("conversations.join", "conversations.setPurpose", "conversations.setTopic"):
            return {"ok": True}
        raise AssertionError(f"unexpected method: {method}")

    def methods(self, name):
        return [p for m, p in self.calls if m == name]


# --- the spec ---------------------------------------------------------------


def test_one_channel_per_advisor_plus_one_main_channel():
    specs = slack_setup.all_specs()
    assert len(specs) == len(ADVISOR_KEYS) + 1
    assert specs[0].env_key == "SLACK_MAIN_CHANNEL"
    assert specs[0].advisor_key == ""


def test_specs_cover_exactly_the_live_advisor_roster():
    assert slack_setup.covered_advisor_keys() == tuple(ADVISOR_KEYS)


def test_env_keys_match_what_channel_config_reads():
    from ai_assistant.integrations.channel_config import advisor_channel_env

    for spec in slack_setup.all_specs()[1:]:
        assert spec.env_key == advisor_channel_env(spec.advisor_key)


def test_channel_names_are_acceptable_to_slack():
    for spec in slack_setup.all_specs():
        assert spec.name == spec.name.lower()
        assert " " not in spec.name and "." not in spec.name
        assert len(spec.name) <= slack_setup.MAX_CHANNEL_NAME
        assert spec.name.replace("-", "").replace("_", "").isalnum()


def test_purposes_and_topics_are_turkish_and_within_limits():
    for spec in slack_setup.all_specs():
        assert spec.purpose and len(spec.purpose) <= slack_setup.MAX_PURPOSE
        assert spec.topic and len(spec.topic) <= slack_setup.MAX_PURPOSE


def test_personal_data_advisors_default_to_private_channels():
    from ai_assistant.reports import PRIVATE_ADVISOR_KEYS

    private = {s.advisor_key for s in slack_setup.all_specs() if s.private}
    assert private == {k for k in PRIVATE_ADVISOR_KEYS if k in ADVISOR_KEYS}


def test_all_public_flag_drops_the_private_channels():
    assert not any(s.private for s in slack_setup.all_specs(all_public=True))


def test_prefix_option_renames_every_channel():
    specs = slack_setup.all_specs(prefix="asistan-")
    assert all(s.name.startswith("asistan-") for s in specs)


def test_channel_name_normalisation_folds_turkish_letters():
    assert slack_setup.normalize_channel_name("AI Çocuk Gelişimi") == "ai-cocuk-gelisimi"
    assert slack_setup.normalize_channel_name("İş Analisti!") == "is-analisti"


# --- dry run ----------------------------------------------------------------


def test_dry_run_creates_absolutely_nothing():
    api = FakeApi()
    result = slack_setup.provision(api, apply=False, env={})

    assert result.dry_run is True
    assert api.methods("conversations.create") == []
    assert api.methods("conversations.join") == []
    assert api.methods("conversations.setPurpose") == []
    assert all(o.action == "would-create" for o in result.outcomes)
    assert result.env_lines == [], "there is no id to paste before anything exists"


def test_dry_run_reports_which_channels_already_exist():
    api = FakeApi(existing={"ai-hava-durumu": "C111"})
    result = slack_setup.provision(api, apply=False, env={})

    by_name = {o.spec.name: o for o in result.outcomes}
    assert by_name["ai-hava-durumu"].action == "would-reuse"
    assert by_name["ai-hava-durumu"].channel_id == "C111"
    assert by_name["ai-asistan-genel"].action == "would-create"
    assert api.methods("conversations.create") == []


def test_cli_defaults_to_dry_run(monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    api = FakeApi()
    monkeypatch.setattr(slack_setup, "SlackApi", lambda token: api)

    code = slack_setup.main([])

    assert code == 0
    assert api.methods("conversations.create") == []
    out = capsys.readouterr().out
    assert "PROVA" in out
    assert "--apply" in out


def test_cli_refuses_write_env_without_apply(monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    code = slack_setup.main(["--write-env"])
    assert code == 2
    assert "--apply" in capsys.readouterr().err


def test_cli_without_a_token_explains_the_scopes(monkeypatch, capsys):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    code = slack_setup.main([])
    err = capsys.readouterr().err
    assert code == 2
    assert "SLACK_BOT_TOKEN" in err
    assert "channels:manage" in err


# --- apply + idempotency ----------------------------------------------------


def test_apply_creates_every_channel_once():
    api = FakeApi()
    result = slack_setup.provision(api, apply=True, env={})

    assert result.created == len(ADVISOR_KEYS) + 1
    assert not result.failed
    created = [p["name"] for p in api.methods("conversations.create")]
    assert len(created) == len(set(created)) == len(ADVISOR_KEYS) + 1
    assert all(o.channel_id.startswith("C") for o in result.outcomes)


def test_apply_sets_a_turkish_purpose_and_topic_on_each_channel():
    api = FakeApi()
    slack_setup.provision(api, apply=True, env={})

    purposes = api.methods("conversations.setPurpose")
    topics = api.methods("conversations.setTopic")
    assert len(purposes) == len(topics) == len(ADVISOR_KEYS) + 1
    assert any("danışman" in p["purpose"].lower() for p in purposes)


def test_apply_invites_the_bot_to_every_channel():
    api = FakeApi()
    slack_setup.provision(api, apply=True, env={})
    assert len(api.methods("conversations.join")) == len(ADVISOR_KEYS) + 1


def test_rerunning_creates_nothing_new(capsys):
    """Idempotency, the way a user hits it: run it twice."""
    api = FakeApi()
    first = slack_setup.provision(api, apply=True, env={})
    creates_after_first = len(api.methods("conversations.create"))

    second = slack_setup.provision(api, apply=True, env={})

    assert len(api.methods("conversations.create")) == creates_after_first
    assert second.created == 0
    assert second.reused == len(first.outcomes)
    assert second.env_lines == first.env_lines


def test_an_id_already_in_the_environment_is_never_recreated():
    """Idempotency the other way: .env is already filled in."""
    api = FakeApi()
    env = {"SLACK_MAIN_CHANNEL": "CPINNED", "SLACK_CHANNEL_WEATHER": "CWPINNED"}

    result = slack_setup.provision(api, apply=True, env=env)

    created = [p["name"] for p in api.methods("conversations.create")]
    assert "ai-asistan-genel" not in created
    assert "ai-hava-durumu" not in created
    by_key = {o.spec.env_key: o for o in result.outcomes}
    assert by_key["SLACK_MAIN_CHANNEL"].channel_id == "CPINNED"
    assert by_key["SLACK_CHANNEL_WEATHER"].channel_id == "CWPINNED"


def test_existing_channel_is_adopted_not_duplicated():
    api = FakeApi(existing={"ai-anka-koprusu": "CEXIST"})
    result = slack_setup.provision(api, apply=True, env={})

    outcome = next(o for o in result.outcomes if o.spec.name == "ai-anka-koprusu")
    assert outcome.action == "exists"
    assert outcome.channel_id == "CEXIST"
    assert "ai-anka-koprusu" not in [p["name"] for p in api.methods("conversations.create")]
    # ...and it is still described and joined, so an adopted channel is usable.
    assert {"channel": "CEXIST"} in api.methods("conversations.join")


def test_name_taken_race_is_recovered_by_looking_again(monkeypatch):
    """Another run created the channel between our listing and our create."""
    api = FakeApi()
    real_create = api.call

    def racy(method, payload=None):
        if method == "conversations.create" and payload["name"] == "ai-hava-durumu":
            api.channels["ai-hava-durumu"] = "CRACE"
            api.calls.append((method, dict(payload)))
            raise slack_setup.SlackApiError(method, "name_taken", "zaten var")
        return real_create(method, payload)

    monkeypatch.setattr(api, "call", racy)
    result = slack_setup.provision(api, apply=True, env={})

    outcome = next(o for o in result.outcomes if o.spec.name == "ai-hava-durumu")
    assert outcome.action == "exists"
    assert outcome.channel_id == "CRACE"


# --- failure handling -------------------------------------------------------


def test_missing_scope_on_listing_stops_with_an_actionable_message():
    api = FakeApi(fail={"conversations.list": "missing_scope"})
    result = slack_setup.provision(api, apply=True, env={})

    assert result.outcomes == []
    assert "channels:manage" in result.error
    assert "YENİDEN KUR" in result.error


def test_missing_scope_on_create_is_reported_per_channel_not_raised():
    api = FakeApi(fail={"conversations.create": "missing_scope"})
    result = slack_setup.provision(api, apply=True, env={})

    assert len(result.failed) == len(ADVISOR_KEYS) + 1
    assert all("channels:manage" in o.detail for o in result.failed)


def test_a_failed_purpose_is_only_a_note_not_a_failure():
    api = FakeApi(fail={"conversations.setPurpose": "missing_scope"})
    result = slack_setup.provision(api, apply=True, env={})

    assert not result.failed
    assert all(o.notes for o in result.outcomes)
    assert result.created == len(ADVISOR_KEYS) + 1


def test_explain_names_the_scope_slack_asked_for():
    message = slack_setup.explain(
        "conversations.create",
        {"error": "missing_scope", "needed": "channels:manage", "provided": "chat:write"},
    )
    assert "channels:manage" in message
    assert "chat:write" in message


def test_explain_falls_back_to_the_methods_own_scope():
    message = slack_setup.explain("conversations.join", {"error": "not_in_channel"})
    assert "channels:join" in message


def test_cli_reports_a_broken_token(monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-bad")
    api = FakeApi(fail={"auth.test": "invalid_auth"})
    monkeypatch.setattr(slack_setup, "SlackApi", lambda token: api)

    code = slack_setup.main(["--apply"])

    assert code == 1
    assert "SLACK_BOT_TOKEN" in capsys.readouterr().err


# --- .env writing -----------------------------------------------------------


def test_env_block_is_ready_to_paste():
    api = FakeApi()
    result = slack_setup.provision(api, apply=True, env={})
    block = slack_setup.render_env_block(result)

    assert "SLACK_MAIN_CHANNEL=C" in block
    for key in ADVISOR_KEYS:
        assert f"SLACK_CHANNEL_{key.upper()}=C" in block


def test_write_env_appends_to_a_file_that_has_no_slack_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")

    api = FakeApi()
    result = slack_setup.provision(api, apply=True, env={})
    changed = slack_setup.write_env_file(result, str(env_file))

    body = env_file.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=abc" in body, "existing settings survive"
    assert "SLACK_MAIN_CHANNEL=C" in body
    assert len(changed) == len(ADVISOR_KEYS) + 1


def test_write_env_replaces_in_place_and_never_duplicates_a_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SLACK_BOT_TOKEN=xoxb-x\nSLACK_CHANNEL_WEATHER=COLD\n", encoding="utf-8"
    )

    api = FakeApi()
    result = slack_setup.provision(api, apply=True, env={})
    slack_setup.write_env_file(result, str(env_file))
    slack_setup.write_env_file(result, str(env_file))  # twice on purpose

    lines = env_file.read_text(encoding="utf-8").splitlines()
    keys = [line.split("=")[0] for line in lines if "=" in line]
    assert len(keys) == len(set(keys)), "a rerun must not duplicate a key"
    assert "SLACK_CHANNEL_WEATHER=COLD" not in lines
    assert "SLACK_BOT_TOKEN=xoxb-x" in lines


def test_write_env_creates_the_file_when_missing(tmp_path):
    env_file = tmp_path / "brand-new.env"
    api = FakeApi()
    result = slack_setup.provision(api, apply=True, env={})

    slack_setup.write_env_file(result, str(env_file))

    assert "SLACK_MAIN_CHANNEL=C" in env_file.read_text(encoding="utf-8")


def test_write_env_is_a_no_op_when_the_ids_already_match(tmp_path):
    env_file = tmp_path / ".env"
    api = FakeApi()
    result = slack_setup.provision(api, apply=True, env={})
    slack_setup.write_env_file(result, str(env_file))

    assert slack_setup.write_env_file(result, str(env_file)) == []


def test_cli_end_to_end_apply_and_write_env(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    for key in ADVISOR_KEYS:
        monkeypatch.delenv(f"SLACK_CHANNEL_{key.upper()}", raising=False)
    monkeypatch.delenv("SLACK_MAIN_CHANNEL", raising=False)

    api = FakeApi()
    monkeypatch.setattr(slack_setup, "SlackApi", lambda token: api)
    env_file = tmp_path / ".env"

    code = slack_setup.main(["--apply", "--write-env", "--env-file", str(env_file)])

    assert code == 0
    out = capsys.readouterr().out
    assert "UYGULAMA" in out
    assert "SLACK_CHANNEL_WEATHER=C" in out
    body = env_file.read_text(encoding="utf-8")
    assert "SLACK_MAIN_CHANNEL=C" in body
    assert body.count("SLACK_CHANNEL_WEATHER=") == 1
