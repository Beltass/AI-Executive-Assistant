"""Tests for database models."""

import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.models import (
    User,
    Content,
    ContentVariation,
    ScheduledPost,
    LinkedInNetwork,
    SpeakingOpportunity,
    EngagementMetric,
    Template,
)


class TestUserModel:
    """Tests for User model."""

    def test_create_user(self, db: Session):
        """Test creating a user."""
        user = User(
            email="test@example.com",
            name="Test User",
            language="en",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.is_active is True

    def test_user_unique_email(self, db: Session):
        """Test that user email is unique."""
        user1 = User(email="test@example.com", name="User 1")
        user2 = User(email="test@example.com", name="User 2")

        db.add(user1)
        db.commit()
        db.add(user2)

        with pytest.raises(Exception):  # Integrity error
            db.commit()

    def test_user_settings_json(self, db: Session):
        """Test that user settings are stored as JSON."""
        user = User(
            email="test@example.com",
            name="Test User",
            settings={"theme": "dark", "notifications": True},
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.settings["theme"] == "dark"


class TestContentModel:
    """Tests for Content model."""

    def test_create_content(self, db: Session):
        """Test creating content."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        content = Content(
            user_id=user.id,
            title="Test Content",
            topic="AI",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()
        db.refresh(content)

        assert content.id is not None
        assert content.status == "draft"

    def test_content_relationships(self, db: Session):
        """Test content relationships."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        content = Content(
            user_id=user.id,
            title="Test",
            topic="AI",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        assert content.user is not None
        assert content.user.email == "test@example.com"


class TestContentVariationModel:
    """Tests for ContentVariation model."""

    def test_create_variation(self, db: Session):
        """Test creating content variation."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        content = Content(
            user_id=user.id,
            title="Test",
            topic="AI",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        variation = ContentVariation(
            content_id=content.id,
            variation_type="linkedin",
            text="LinkedIn version",
            tone="professional",
        )
        db.add(variation)
        db.commit()
        db.refresh(variation)

        assert variation.id is not None
        assert variation.variation_type == "linkedin"


class TestScheduledPostModel:
    """Tests for ScheduledPost model."""

    def test_create_scheduled_post(self, db: Session):
        """Test creating scheduled post."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        content = Content(
            user_id=user.id,
            title="Test",
            topic="AI",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        post = ScheduledPost(
            content_id=content.id,
            platform="linkedin",
            scheduled_time=datetime.utcnow(),
            status="pending",
        )
        db.add(post)
        db.commit()
        db.refresh(post)

        assert post.id is not None
        assert post.status == "pending"


class TestLinkedInNetworkModel:
    """Tests for LinkedInNetwork model."""

    def test_create_network(self, db: Session):
        """Test creating LinkedIn network record."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        network = LinkedInNetwork(
            user_id=user.id,
            contact_id="linkedin_123",
            name="John Doe",
            current_title="Engineer",
            company="TechCorp",
        )
        db.add(network)
        db.commit()
        db.refresh(network)

        assert network.id is not None
        assert network.name == "John Doe"


class TestSpeakingOpportunityModel:
    """Tests for SpeakingOpportunity model."""

    def test_create_opportunity(self, db: Session):
        """Test creating speaking opportunity."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        opportunity = SpeakingOpportunity(
            user_id=user.id,
            conference_name="TechConf 2024",
            topic="AI in Business",
            event_date=datetime.utcnow(),
            fit_score=0.85,
            status="discovered",
        )
        db.add(opportunity)
        db.commit()
        db.refresh(opportunity)

        assert opportunity.id is not None
        assert opportunity.fit_score == 0.85


class TestEngagementMetricModel:
    """Tests for EngagementMetric model."""

    def test_create_metric(self, db: Session):
        """Test creating engagement metric."""
        user = User(email="test@example.com", name="Test")
        db.add(user)
        db.commit()

        content = Content(
            user_id=user.id,
            title="Test",
            topic="AI",
            content_type="post",
            status="published",
        )
        db.add(content)
        db.commit()

        metric = EngagementMetric(
            content_id=content.id,
            platform="linkedin",
            views=100,
            likes=10,
            comments=5,
            shares=2,
        )
        db.add(metric)
        db.commit()
        db.refresh(metric)

        assert metric.id is not None
        assert metric.views == 100


class TestTemplateModel:
    """Tests for Template model."""

    def test_create_template(self, db: Session):
        """Test creating template."""
        template = Template(
            name="LinkedIn Post Template",
            category="content",
            content_type="post",
            language="en",
            system_prompt="You are a content expert...",
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        assert template.id is not None
        assert template.is_active is True

    def test_template_examples_json(self, db: Session):
        """Test that template examples are stored as JSON."""
        template = Template(
            name="Test Template",
            category="content",
            content_type="post",
            language="en",
            system_prompt="Prompt",
            examples=[
                {"input": "Topic", "output": "Content"},
                {"input": "Topic 2", "output": "Content 2"},
            ],
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        assert len(template.examples) == 2
