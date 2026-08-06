"""Tests for the Slack advisor CLI entrypoints, mention routing and personas.

Covers three regressions:

1. Both ``slack_advisor_bridge`` and ``advisor_daily_scheduler`` are invoked by
   the ``advisor-slack-bridge`` workflow with ``python -m``. Neither had a
   ``main()`` / ``__main__`` block, so both exited 0 having done nothing. These
   tests assert the entrypoints exist and actually do work.
2. The bridge documented ``@advisor_key`` mentions but never parsed one.
3. The ``linkedin_coach`` and ``personal_assistant`` system prompts were
   generic placeholders instead of the personas the user asked for.
"""

from __future__ import annotations

import runpy
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_assistant.advisors import linkedin_coach as linkedin_coach_module
from ai_assistant.advisors import personal_assistant as personal_assistant_module
from ai_assistant.integrations import advisor_daily_scheduler as scheduler_module
from ai_assistant.integrations import slack_advisor_bridge as bridge_module
from ai_assistant.integrations.slack_advisor_bridge import (
    ADVISOR_NAMES,
    SlackAdvisorBridge,
    build_advisor_help_message,
    parse_advisor_mention,
    resolve_advisor_key,
)


# ============================================================================
# BROKEN 1 — entrypoints exist and are not silent no-ops
# ============================================================================


class TestEntrypointsExist:
    """Both workflow-invoked modules must be runnable with ``python -m``."""

    def test_bridge_has_main(self):
        assert callable(bridge_module.main)

    def test_scheduler_has_main(self):
        assert callable(scheduler_module.main)

    @pytest.mark.parametrize(
        "path",
        [
            "src/ai_assistant/integrations/slack_advisor_bridge.py",
            "src/ai_assistant/integrations/advisor_daily_scheduler.py",
        ],
    )
    def test_module_has_main_guard(self, path):
        """The workflow runs these with ``python -m``; without the guard the
        process exits 0 without executing anything."""
        source = open(path, encoding="utf-8").read()
        assert 'if __name__ == "__main__":' in source

    def test_bridge_runs_as_module_and_reports_skip(self, monkeypatch, caplog):
        """``python -m ... --process-requests`` must run real code, not no-op."""
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        with caplog.at_level("WARNING"):
            exit_code = bridge_module.main(["--process-requests"])
        assert exit_code == 0
        # Explicit "skipped", not a silent success.
        assert "SKIPPED" in caplog.text

    def test_scheduler_runs_as_module_and_reports_skip(self, monkeypatch, caplog):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        with caplog.at_level("WARNING"):
            exit_code = scheduler_module.main([])
        assert exit_code == 0
        assert "SKIPPED" in caplog.text

    def test_bridge_without_action_exits_nonzero(self, monkeypatch):
        """No action requested is a configuration error, not a silent success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        fake_client = MagicMock()
        with patch.object(
            bridge_module, "build_slack_client", return_value=fake_client
        ):
            assert bridge_module.main([]) == 1

    def test_bridge_main_returns_one_on_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        with patch.object(
            bridge_module, "build_slack_client", side_effect=RuntimeError("boom")
        ):
            assert bridge_module.main(["--process-requests"]) == 1

    def test_scheduler_main_returns_one_on_error(self, monkeypatch):
        with patch.object(
            scheduler_module, "build_slack_bridge", side_effect=RuntimeError("boom")
        ):
            assert scheduler_module.main([]) == 1

    def test_bridge_module_executes_under_runpy(self, monkeypatch):
        """Run the module the way the workflow does and assert it exits 0."""
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.setattr(
            sys, "argv", ["slack_advisor_bridge", "--process-requests"]
        )
        with pytest.raises(SystemExit) as exc:
            runpy.run_module(
                "ai_assistant.integrations.slack_advisor_bridge",
                run_name="__main__",
            )
        assert exc.value.code == 0


class TestProcessPendingRequests:
    """``--process-requests`` must actually dispatch pending requests."""

    @pytest.mark.asyncio
    async def test_pending_requests_are_dispatched(self):
        bridge = SlackAdvisorBridge(slack_client=MagicMock())
        bridge.request_manager._load_requests = MagicMock(
            return_value={
                "r1": {
                    "request_id": "r1",
                    "user_id": "U1",
                    "advisor_key": "data_analyst",
                    "message": "satış verisini özetle",
                    "status": "pending",
                    "thread_ts": "111.222",
                    "created_at": "2026-01-01T00:00:00",
                }
            }
        )
        bridge.handle_advisor_request = AsyncMock(return_value="req-1")

        processed = await bridge_module.process_pending_requests(bridge)

        assert processed == 1
        bridge.handle_advisor_request.assert_awaited_once()
        kwargs = bridge.handle_advisor_request.await_args.kwargs
        assert kwargs["advisor_key"] == "data_analyst"
        assert kwargs["user_id"] == "U1"

    @pytest.mark.asyncio
    async def test_no_pending_requests_is_zero(self):
        bridge = SlackAdvisorBridge(slack_client=MagicMock())
        bridge.request_manager._load_requests = MagicMock(return_value={})
        assert await bridge_module.process_pending_requests(bridge) == 0

    @pytest.mark.asyncio
    async def test_daily_updates_are_sent(self):
        bridge = SlackAdvisorBridge(slack_client=MagicMock())
        bridge.send_daily_advisor_update = AsyncMock(return_value={"ok": True})

        sent = await bridge_module.send_daily_updates(bridge, ["data_analyst"])

        assert sent == 1
        bridge.send_daily_advisor_update.assert_awaited_once()


# ============================================================================
# BROKEN 2 — @advisor mention parsing and routing
# ============================================================================


class TestMentionParsing:
    def test_parses_canonical_key(self):
        key, raw, remainder = parse_advisor_mention("@data_analyst merhaba")
        assert key == "data_analyst"
        assert raw == "data_analyst"
        assert remainder == "merhaba"

    @pytest.mark.parametrize("advisor_key", sorted(ADVISOR_NAMES))
    def test_every_advisor_can_be_mentioned(self, advisor_key):
        key, _raw, _rest = parse_advisor_mention(f"@{advisor_key} bir şey yap")
        assert key == advisor_key

    def test_parses_turkish_alias(self):
        key, _raw, remainder = parse_advisor_mention("@kişisel_asistan bugün ne var?")
        assert key == "personal_assistant"
        assert remainder == "bugün ne var?"

    def test_mention_mid_message(self):
        key, _raw, remainder = parse_advisor_mention("lütfen @linkedin profilime bak")
        assert key == "linkedin_coach"
        assert "profilime bak" in remainder

    def test_slack_bot_mention_is_ignored(self):
        key, _raw, _rest = parse_advisor_mention("<@U12345> @data_analyst özet ver")
        assert key == "data_analyst"

    def test_unknown_advisor_reports_raw_name(self):
        key, raw, _rest = parse_advisor_mention("@muhasebeci fatura kes")
        assert key is None
        assert raw == "muhasebeci"

    def test_no_mention(self):
        key, raw, remainder = parse_advisor_mention("selam nasılsın")
        assert key is None
        assert raw is None
        assert remainder == "selam nasılsın"

    def test_empty_text(self):
        assert parse_advisor_mention("") == (None, None, "")

    def test_resolve_advisor_key_is_case_insensitive(self):
        assert resolve_advisor_key("Data_Analyst") == "data_analyst"

    def test_help_message_lists_every_advisor(self):
        message = build_advisor_help_message("muhasebeci")
        assert "muhasebeci" in message
        for key in ADVISOR_NAMES:
            assert key in message


class TestMentionRouting:
    @pytest.mark.asyncio
    async def test_mention_routes_to_advisor(self):
        bridge = SlackAdvisorBridge(slack_client=MagicMock())
        bridge.handle_advisor_request = AsyncMock(return_value="req-9")

        result = await bridge.handle_mention("U1", "@data_analyst merhaba", "C1")

        assert result == "req-9"
        kwargs = bridge.handle_advisor_request.await_args.kwargs
        assert kwargs["advisor_key"] == "data_analyst"
        assert kwargs["message"] == "merhaba"
        assert kwargs["channel"] == "C1"

    @pytest.mark.asyncio
    async def test_unknown_advisor_gets_help_message(self):
        client = MagicMock()
        client.chat_postMessage = AsyncMock(return_value={"ok": True})
        bridge = SlackAdvisorBridge(slack_client=client)
        bridge.handle_advisor_request = AsyncMock()

        result = await bridge.handle_mention("U1", "@muhasebeci fatura kes", "C1")

        assert result is None
        bridge.handle_advisor_request.assert_not_awaited()
        client.chat_postMessage.assert_awaited_once()
        text = client.chat_postMessage.await_args.kwargs["text"]
        assert "muhasebeci" in text
        assert "data_analyst" in text

    @pytest.mark.asyncio
    async def test_reply_goes_to_thread_when_given(self):
        client = MagicMock()
        client.chat_postMessage = AsyncMock(return_value={"ok": True})
        bridge = SlackAdvisorBridge(slack_client=client)

        await bridge.handle_mention("U1", "@yok bir şey", "C1", thread_ts="9.9")

        assert client.chat_postMessage.await_args.kwargs["thread_ts"] == "9.9"

    @pytest.mark.asyncio
    async def test_message_without_mention_is_not_routed(self):
        bridge = SlackAdvisorBridge(slack_client=MagicMock())
        bridge.handle_advisor_request = AsyncMock()

        assert await bridge.handle_mention("U1", "selam", "C1") is None
        bridge.handle_advisor_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bare_mention_gets_capabilities(self):
        client = MagicMock()
        client.chat_postMessage = AsyncMock(return_value={"ok": True})
        bridge = SlackAdvisorBridge(slack_client=client)
        bridge.handle_advisor_request = AsyncMock()

        assert await bridge.handle_mention("U1", "@data_analyst", "C1") is None
        bridge.handle_advisor_request.assert_not_awaited()
        client.chat_postMessage.assert_awaited_once()


# ============================================================================
# BROKEN 3 — the two personas
# ============================================================================


class TestLinkedInRecruiterPersona:
    """Regression: the prompt must speak HR / CV / recruiting, not generic
    content coaching."""

    @pytest.mark.parametrize(
        "concept",
        ["İK", "CV", "özgeçmiş", "işe alım", "recruiter", "ATS"],
    )
    def test_prompt_mentions_recruiting_concept(self, concept):
        assert concept in linkedin_coach_module.LINKEDIN_SYSTEM_PROMPT

    def test_prompt_covers_profile_cv_consistency(self):
        prompt = linkedin_coach_module.LINKEDIN_SYSTEM_PROMPT
        assert "tutarlılığı" in prompt
        assert "zayıf" in prompt

    def test_prompt_states_no_publishing(self):
        assert "PAYLAŞMAZ" in linkedin_coach_module.LINKEDIN_SYSTEM_PROMPT

    def test_headline_suggestion_uses_llm(self):
        coach = linkedin_coach_module.LinkedInCoach()
        profile = linkedin_coach_module.LinkedInProfile(
            profile_url="https://linkedin.com/in/x",
            headline="Yazılım Mühendisi",
            about="10 yıl deneyim",
            industry="Yazılım",
        )
        with patch.object(linkedin_coach_module.llm, "is_configured", return_value=True):
            with patch.object(
                linkedin_coach_module.llm,
                "generate_text",
                return_value="1. Analiz\n2. ATS boşluğu",
            ) as generate:
                result = coach._suggest_headline(profile)

        generate.assert_called_once()
        system_prompt, user_prompt = generate.call_args[0][:2]
        assert system_prompt == linkedin_coach_module.LINKEDIN_SYSTEM_PROMPT
        assert "Yazılım Mühendisi" in user_prompt
        assert "ATS" in result

    def test_headline_suggestion_without_llm_does_not_invent(self):
        coach = linkedin_coach_module.LinkedInCoach()
        profile = linkedin_coach_module.LinkedInProfile(
            profile_url="", headline="Yazılım Mühendisi", about="", industry=""
        )
        with patch.object(
            linkedin_coach_module.llm, "is_configured", return_value=False
        ):
            result = coach._suggest_headline(profile)

        assert "LLM yapılandırılmadı" in result
        # The old implementation invented this suffix out of thin air.
        assert "Teknoloji Lider & Danışman" not in result


class TestPersonalAssistantPersona:
    """Regression: proactive, loyal, and explicitly non-sycophantic."""

    def test_prompt_is_proactive(self):
        assert "PROAKTİF" in personal_assistant_module.SYSTEM_PROMPT

    def test_prompt_is_loyal(self):
        prompt = personal_assistant_module.SYSTEM_PROMPT
        assert "sadık" in prompt
        assert "başarı" in prompt

    def test_prompt_forbids_sycophancy(self):
        prompt = personal_assistant_module.SYSTEM_PROMPT
        assert "yaltaklanma" in prompt.lower()
        assert "övgü" in prompt

    def test_prompt_demands_honesty_about_bad_news(self):
        prompt = personal_assistant_module.SYSTEM_PROMPT
        assert "açıkça söyle" in prompt
        assert "Uydurmazsın" in prompt

    def test_prompt_covers_work_and_social_data(self):
        prompt = personal_assistant_module.SYSTEM_PROMPT
        for source in ["Takvim", "e-posta", "görev", "toplantı"]:
            assert source in prompt
