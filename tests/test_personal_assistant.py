"""Tests for Personal Assistant advisor."""

import pytest
from ai_assistant.advisors.personal_assistant import (
    PersonalAssistantAdvisor,
    PersonalAssistantState,
    STATE_FILE,
)


class TestPersonalAssistantAdvisor:
    """Test the Personal Assistant advisor."""

    def test_advisor_attributes(self):
        """Test advisor has correct attributes."""
        advisor = PersonalAssistantAdvisor()
        assert advisor.key == "personal_assistant"
        assert advisor.title == "Kişisel Asistan"
        assert advisor.private is True

    def test_state_dataclass(self):
        """Test PersonalAssistantState dataclass."""
        state = PersonalAssistantState(
            last_briefing="Test briefing",
            weekly_goals=["Goal 1", "Goal 2"],
            goal_progress={"Goal 1": 0.5},
        )
        assert state.last_briefing == "Test briefing"
        assert len(state.weekly_goals) == 2
        assert state.goal_progress["Goal 1"] == 0.5

    def test_state_default_values(self):
        """Test PersonalAssistantState has default values."""
        state = PersonalAssistantState()
        assert state.last_briefing is None
        assert state.weekly_goals == []
        assert state.goal_progress == {}
        assert state.recent_networks == []
        assert state.urgent_deadlines == []
        assert state.updated_at is not None

    def test_load_state_empty(self):
        """Test loading empty state."""
        advisor = PersonalAssistantAdvisor()
        state = advisor._load_state()
        assert isinstance(state, PersonalAssistantState)
        assert state.weekly_goals == []

    def test_get_calendar_summary(self):
        """Test calendar summary method."""
        advisor = PersonalAssistantAdvisor()
        summary = advisor._get_calendar_summary()
        assert isinstance(summary, str)

    def test_get_urgent_tasks(self):
        """Test urgent tasks method."""
        advisor = PersonalAssistantAdvisor()
        tasks = advisor._get_urgent_tasks()
        assert isinstance(tasks, str)

    def test_get_weekly_goals(self):
        """Test weekly goals method."""
        advisor = PersonalAssistantAdvisor()
        goals = advisor._get_weekly_goals()
        assert isinstance(goals, str)

    def test_get_urgent_emails(self):
        """Test urgent emails method."""
        advisor = PersonalAssistantAdvisor()
        emails = advisor._get_urgent_emails()
        assert isinstance(emails, str)

    def test_advisor_has_batch_section_method(self):
        """Test advisor has batch_section method."""
        advisor = PersonalAssistantAdvisor()
        assert hasattr(advisor, "batch_section")
        assert callable(advisor.batch_section)

    def test_state_has_required_fields(self):
        """Test PersonalAssistantState has required fields."""
        state = PersonalAssistantState()
        assert hasattr(state, "last_briefing")
        assert hasattr(state, "weekly_goals")
        assert hasattr(state, "goal_progress")
        assert hasattr(state, "recent_networks")
        assert hasattr(state, "urgent_deadlines")
        assert hasattr(state, "updated_at")
