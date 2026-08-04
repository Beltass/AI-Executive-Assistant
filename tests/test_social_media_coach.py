"""Tests for Social Media Coach advisor."""

import pytest
from ai_assistant.advisors.social_media_coach import (
    SocialMediaCoachAdvisor,
    ProfileAnalysis,
    PROFILES_FILE,
)


class TestSocialMediaCoachAdvisor:
    """Test the Social Media Coach advisor."""

    def test_advisor_attributes(self):
        """Test advisor has correct attributes."""
        advisor = SocialMediaCoachAdvisor()
        assert advisor.key == "social_media_coach"
        assert advisor.title == "Sosyal Medya İmaj Koçu"
        assert advisor.private is True

    def test_skipped_when_no_config(self):
        """Test advisor returns skipped when no profiles configured."""
        advisor = SocialMediaCoachAdvisor()
        briefing = advisor.generate_briefing()
        assert briefing.skipped

    def test_profile_analysis_dataclass(self):
        """Test ProfileAnalysis dataclass."""
        analysis = ProfileAnalysis(
            platform="instagram",
            handle="@testuser",
            analyzed_at="2024-08-04T10:00:00",
            strengths=["Good engagement"],
            bio_score=75,
        )
        assert analysis.platform == "instagram"
        assert analysis.handle == "@testuser"
        assert analysis.bio_score == 75
        assert len(analysis.strengths) == 1

    def test_analyze_instagram(self):
        """Test Instagram profile analysis."""
        advisor = SocialMediaCoachAdvisor()
        analysis = advisor._analyze_instagram("@testuser", "professional")
        assert analysis.platform == "instagram"
        assert analysis.handle == "@testuser"
        assert analysis.bio_score > 0
        assert len(analysis.strengths) > 0
        assert len(analysis.improvements) > 0

    def test_analyze_twitter(self):
        """Test Twitter profile analysis."""
        advisor = SocialMediaCoachAdvisor()
        analysis = advisor._analyze_twitter("@testuser", "professional")
        assert analysis.platform == "twitter"
        assert analysis.handle == "@testuser"
        assert analysis.bio_score > 0
        assert len(analysis.content_ideas) > 0

    def test_profile_analysis_has_required_fields(self):
        """Test ProfileAnalysis has all required fields."""
        analysis = ProfileAnalysis(
            platform="instagram",
            handle="@test",
            analyzed_at="2024-08-04T10:00:00",
        )
        assert hasattr(analysis, "platform")
        assert hasattr(analysis, "handle")
        assert hasattr(analysis, "analyzed_at")
        assert hasattr(analysis, "strengths")
        assert hasattr(analysis, "improvements")
        assert hasattr(analysis, "bio_score")
        assert hasattr(analysis, "recommendations")
