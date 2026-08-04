"""Tests for LinkedIn İmaj Koçu (LinkedIn Coach) advisor.

Comprehensive test suite for:
- Post generation and management
- Profile optimization
- Engagement tracking
- Job opportunity detection
- Approval workflow
- State persistence
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_assistant.advisors.linkedin_coach import (
    EngagementMetrics,
    JobOpportunity,
    LinkedInCoach,
    LinkedInPost,
    LinkedInProfile,
)
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED


class TestLinkedInPostDataclass:
    """Test LinkedInPost dataclass."""

    def test_post_creation(self):
        """Test creating a LinkedInPost."""
        post = LinkedInPost(
            id="post_001",
            date="2026-08-04",
            headline="Test Headline",
            body="Test body content",
            hashtags=["#test", "#linkedin"],
            cta="Share your thoughts",
            draft=True,
        )

        assert post.id == "post_001"
        assert post.headline == "Test Headline"
        assert post.draft is True
        assert post.approved is False
        assert post.posted_at is None

    def test_post_to_dict(self):
        """Test converting post to dictionary."""
        post = LinkedInPost(
            id="post_001",
            date="2026-08-04",
            headline="Test",
            body="Body",
            hashtags=["#test"],
            cta="Share",
        )

        data = post.to_dict()
        assert data["id"] == "post_001"
        assert data["headline"] == "Test"
        assert isinstance(data, dict)

    def test_post_from_dict(self):
        """Test creating post from dictionary."""
        data = {
            "id": "post_002",
            "date": "2026-08-04",
            "headline": "Test",
            "body": "Body",
            "hashtags": ["#test"],
            "cta": "Share",
            "draft": True,
            "approved": False,
            "posted_at": None,
            "edited_by_user": None,
            "performance": None,
        }

        post = LinkedInPost.from_dict(data)
        assert post.id == "post_002"
        assert post.headline == "Test"


class TestEngagementMetricsDataclass:
    """Test EngagementMetrics dataclass."""

    def test_metrics_creation(self):
        """Test creating EngagementMetrics."""
        metrics = EngagementMetrics(
            date="2026-08-04",
            followers=1500,
            impressions=500,
            engagements=75,
            posts_published=2,
            engagement_rate=0.15,
        )

        assert metrics.date == "2026-08-04"
        assert metrics.followers == 1500
        assert metrics.engagements == 75

    def test_metrics_to_dict(self):
        """Test converting metrics to dictionary."""
        metrics = EngagementMetrics(
            date="2026-08-04",
            followers=1500,
            impressions=500,
            engagements=75,
            posts_published=2,
        )

        data = metrics.to_dict()
        assert isinstance(data, dict)
        assert data["followers"] == 1500


class TestLinkedInCoachAdvisor:
    """Test LinkedInCoach advisor."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create temporary state directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_dir = Path(".assistant_state")
            with patch("ai_assistant.advisors.linkedin_coach.STATE_DIR", Path(tmpdir)):
                with patch("ai_assistant.advisors.linkedin_coach.DRAFTS_FILE", Path(tmpdir) / "linkedin_drafts.json"):
                    with patch("ai_assistant.advisors.linkedin_coach.METRICS_FILE", Path(tmpdir) / "linkedin_metrics.json"):
                        with patch("ai_assistant.advisors.linkedin_coach.PROFILE_FILE", Path(tmpdir) / "linkedin_profile.json"):
                            yield Path(tmpdir)

    @pytest.fixture
    def coach(self):
        """Create LinkedInCoach instance."""
        with patch("ai_assistant.advisors.linkedin_coach.setting") as mock_setting:

            def setting_side_effect(key, default=""):
                if key == "LINKEDIN_PROFILE_URL":
                    return "https://linkedin.com/in/testuser"
                elif key == "LINKEDIN_ACCESS_TOKEN":
                    return "mock_token"
                elif key == "LINKEDIN_AUTO_PUBLISH":
                    return "false"
                elif key == "LINKEDIN_APPROVAL_CHANNEL":
                    return ""
                elif key == "LINKEDIN_SECTOR":
                    return "yazılım & bulut teknolojileri"
                return default

            mock_setting.side_effect = setting_side_effect
            return LinkedInCoach()

    def test_coach_initialization(self, coach):
        """Test LinkedInCoach initialization."""
        assert coach.key == "linkedin_coach"
        assert coach.title == "LinkedIn İmaj Koçu"
        assert coach.incremental_source is False
        assert coach.profile_url == "https://linkedin.com/in/testuser"

    def test_generate_briefing_no_profile(self, coach):
        """Test briefing generation when profile URL is not configured."""
        with patch.object(coach, "profile_url", ""):
            briefing = coach.generate_briefing()
            assert briefing.status == STATUS_SKIPPED
            assert "yapılandırılmadı" in briefing.text

    def test_generate_briefing_with_profile(self, coach, temp_state_dir):
        """Test briefing generation with profile configured."""
        briefing = coach.generate_briefing()
        assert briefing.status == STATUS_OK
        assert briefing.key == "linkedin_coach"
        assert briefing.title == "LinkedIn İmaj Koçu"

    def test_generate_daily_posts(self, coach, temp_state_dir):
        """Test generating daily posts."""
        posts = coach.generate_daily_posts("Test sector news", "Test tech news")

        assert len(posts) > 0
        assert all(isinstance(p, LinkedInPost) for p in posts)
        assert all(p.draft is True for p in posts)
        assert all(p.headline for p in posts)
        assert all(p.body for p in posts)
        assert all(p.hashtags for p in posts)
        assert all(p.cta for p in posts)

    def test_mark_post_approved(self, coach, temp_state_dir):
        """Test marking a post as approved."""
        posts = coach.generate_daily_posts()
        assert len(posts) > 0

        post_id = posts[0].id
        result = coach.mark_post_approved(post_id)
        assert result is True

        approved_posts = coach._load_drafts()
        approved_post = next((p for p in approved_posts if p.id == post_id), None)
        assert approved_post is not None
        assert approved_post.approved is True

    def test_mark_post_rejected(self, coach, temp_state_dir):
        """Test rejecting a draft post."""
        posts = coach.generate_daily_posts()
        initial_count = len(posts)

        post_id = posts[0].id
        result = coach.mark_post_rejected(post_id)
        assert result is True

        remaining_posts = coach._load_drafts()
        assert len(remaining_posts) == initial_count - 1
        assert all(p.id != post_id for p in remaining_posts)

    def test_edit_post(self, coach, temp_state_dir):
        """Test editing a draft post."""
        posts = coach.generate_daily_posts()
        post_id = posts[0].id

        new_headline = "Edited Headline"
        new_body = "Edited body"
        new_hashtags = ["#edited", "#test"]
        new_cta = "Edited CTA"

        result = coach.edit_post(
            post_id,
            headline=new_headline,
            body=new_body,
            hashtags=new_hashtags,
            cta=new_cta,
        )
        assert result is True

        edited_post = next(
            (p for p in coach._load_drafts() if p.id == post_id), None
        )
        assert edited_post.headline == new_headline
        assert edited_post.body == new_body
        assert edited_post.hashtags == new_hashtags
        assert edited_post.cta == new_cta

    def test_publish_post(self, coach, temp_state_dir):
        """Test publishing an approved post."""
        posts = coach.generate_daily_posts()
        post_id = posts[0].id

        # Approve first
        coach.mark_post_approved(post_id)

        # Then publish
        result = coach.publish_post(post_id)
        assert result is True

        published_post = next(
            (p for p in coach._load_drafts() if p.id == post_id), None
        )
        assert published_post.draft is False
        assert published_post.posted_at is not None

    def test_get_pending_posts(self, coach, temp_state_dir):
        """Test getting posts awaiting approval."""
        coach.generate_daily_posts()
        pending = coach._get_pending_posts()

        assert len(pending) > 0
        assert all(p.draft is True for p in pending)
        assert all(p.posted_at is None for p in pending)

    def test_track_engagement(self, coach, temp_state_dir):
        """Test tracking engagement metrics."""
        metrics = coach.track_engagement()

        assert isinstance(metrics, EngagementMetrics)
        assert metrics.date == datetime.utcnow().date().isoformat()
        assert metrics.followers >= 0
        assert metrics.impressions >= 0
        assert metrics.engagements >= 0

    def test_track_engagement_persistence(self, coach, temp_state_dir):
        """Test that engagement metrics are persisted."""
        metrics1 = coach.track_engagement()
        metrics2 = coach.track_engagement()

        # Same day should return same metrics
        assert metrics1.date == metrics2.date

    def test_generate_weekly_summary(self, coach, temp_state_dir):
        """Test generating weekly summary."""
        # Create some metrics data
        today = datetime.utcnow().date()
        for i in range(7):
            date_str = (today - timedelta(days=i)).isoformat()
            metrics = EngagementMetrics(
                date=date_str,
                followers=1000 + i * 10,
                impressions=400 + i * 20,
                engagements=50 + i * 5,
                posts_published=1 if i % 2 == 0 else 0,
                engagement_rate=0.1 + i * 0.01,
            )
            all_metrics = coach._load_metrics()
            all_metrics.append(metrics)
            coach._save_metrics(all_metrics)

        summary = coach.generate_weekly_summary()
        assert "period" in summary
        assert "avg_followers" in summary
        assert "total_engagements" in summary

    def test_identify_job_opportunities(self, coach):
        """Test identifying job opportunities."""
        opportunities = coach.identify_job_opportunities()

        assert isinstance(opportunities, list)
        if len(opportunities) > 0:
            opp = opportunities[0]
            assert isinstance(opp, JobOpportunity)
            assert opp.company_name
            assert opp.opportunity_type in [
                "direct_posting",
                "leadership_change",
                "expansion",
                "product_launch",
            ]
            assert 1 <= opp.relevance_score <= 5

    def test_generate_profile_suggestions(self, coach, temp_state_dir):
        """Test generating profile optimization suggestions."""
        # Save a mock profile
        profile = LinkedInProfile(
            profile_url="https://linkedin.com/in/testuser",
            headline="Software Engineer",
            about="Test about",
            industry="Technology",
            followers_count=1000,
            last_updated=datetime.utcnow().isoformat(),
            optimization_score=75,
        )
        coach._save_profile(profile)

        suggestions = coach.generate_profile_suggestions()
        assert "headline" in suggestions
        assert "about" in suggestions

    def test_batch_section(self, coach):
        """Test batch section generation."""
        section = coach.batch_section()

        # Should return a batch section when configured
        if coach.profile_url and coach.access_token:
            assert section is not None
            assert section.key == coach.key
            assert section.title == coach.title

    def test_error_handling_in_drafts(self, coach):
        """Test error handling when loading drafts fails."""
        with patch("builtins.open", side_effect=IOError("File error")):
            drafts = coach._load_drafts()
            assert drafts == []

    def test_error_handling_in_metrics(self, coach):
        """Test error handling when loading metrics fails."""
        with patch("builtins.open", side_effect=IOError("File error")):
            metrics = coach._load_metrics()
            assert metrics == []

    def test_mock_post_generation(self, coach):
        """Test mock post data generation."""
        posts = coach._generate_mock_posts("Test news", "Test tech")

        assert len(posts) == 2
        for post in posts:
            assert post.date == datetime.utcnow().date().isoformat()
            assert post.draft is True
            assert len(post.hashtags) >= 3
            assert len(post.hashtags) <= 5

    def test_formatting_helpers(self, coach, temp_state_dir):
        """Test briefing formatting helpers."""
        profile = LinkedInProfile(
            profile_url="https://linkedin.com/in/testuser",
            headline="Tech Lead",
            about="Passionate about technology",
            industry="Software Development",
            followers_count=2500,
            optimization_score=85,
        )

        profile_section = coach._format_profile_section(profile)
        assert "👤" in profile_section
        assert "Tech Lead" in profile_section
        assert "85" in profile_section

    def test_multiple_posts_workflow(self, coach, temp_state_dir):
        """Test complete workflow with multiple posts."""
        # Generate posts
        posts = coach.generate_daily_posts()
        assert len(posts) >= 1

        # Approve first post
        if len(posts) > 0:
            first_post_id = posts[0].id
            coach.mark_post_approved(first_post_id)

            # Publish first post
            coach.publish_post(first_post_id)

            # Check published post
            all_posts = coach._load_drafts()
            published = next((p for p in all_posts if p.id == first_post_id), None)
            assert published.draft is False

        # Reject second post if exists
        if len(posts) > 1:
            second_post_id = posts[1].id
            coach.mark_post_rejected(second_post_id)

            # Verify rejected
            all_posts = coach._load_drafts()
            assert all(p.id != second_post_id for p in all_posts)


class TestLinkedInCoachIntegration:
    """Integration tests for LinkedIn Coach."""

    @pytest.fixture
    def coach_with_config(self):
        """Create coach with full configuration."""
        with patch("ai_assistant.advisors.linkedin_coach.setting") as mock_setting:

            def setting_side_effect(key, default=""):
                config = {
                    "LINKEDIN_PROFILE_URL": "https://linkedin.com/in/testuser",
                    "LINKEDIN_ACCESS_TOKEN": "test_token_123",
                    "LINKEDIN_AUTO_PUBLISH": "false",
                    "LINKEDIN_APPROVAL_CHANNEL": "#content",
                    "LINKEDIN_SECTOR": "yazılım geliştirme",
                }
                return config.get(key, default)

            mock_setting.side_effect = setting_side_effect
            return LinkedInCoach()

    def test_full_workflow_simulation(self, coach_with_config):
        """Simulate a complete workflow: generate, approve, publish, track."""
        # 1. Generate posts
        posts = coach_with_config.generate_daily_posts()
        assert len(posts) >= 1

        post_id = posts[0].id

        # 2. Approve post
        assert coach_with_config.mark_post_approved(post_id) is True

        # 3. Publish post
        assert coach_with_config.publish_post(post_id) is True

        # 4. Track engagement
        metrics = coach_with_config.track_engagement()
        assert metrics.posts_published >= 0

        # 5. Get weekly summary
        summary = coach_with_config.generate_weekly_summary()
        assert "recommendation" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
