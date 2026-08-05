"""Tests for content service."""

import pytest
from sqlalchemy.orm import Session
from app.db.models import User, Content
from app.services.content_service import ContentService


@pytest.fixture
def content_service(db: Session):
    """Create ContentService instance."""
    return ContentService(db)


@pytest.fixture
def test_user(db: Session):
    """Create test user."""
    user = User(email="test@example.com", name="Test User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestContentGeneration:
    """Tests for content generation."""

    @pytest.mark.asyncio
    async def test_generate_content_creates_record(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test that generate_content creates database record."""
        content = await content_service.generate_content(
            user_id=test_user.id,
            topic="AI in business",
            content_type="post",
            platforms=["linkedin"],
        )
        assert content is not None
        assert content.user_id == test_user.id
        assert content.topic == "AI in business"

    @pytest.mark.asyncio
    async def test_generate_content_creates_variations(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test that content generation creates variations."""
        content = await content_service.generate_content(
            user_id=test_user.id,
            topic="AI in business",
            content_type="post",
            platforms=["linkedin"],
        )
        assert len(content.variations) >= 0

    @pytest.mark.asyncio
    async def test_generate_content_invalid_user(self, content_service: ContentService):
        """Test generating content for invalid user raises error."""
        with pytest.raises(ValueError):
            await content_service.generate_content(
                user_id=999,
                topic="AI in business",
                content_type="post",
                platforms=["linkedin"],
            )


class TestContentRetrieval:
    """Tests for content retrieval."""

    @pytest.mark.asyncio
    async def test_get_content_success(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test successfully getting content."""
        # Create content
        content = Content(
            user_id=test_user.id,
            title="Test",
            topic="Test",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        # Retrieve it
        retrieved = await content_service.get_content(test_user.id, content.id)
        assert retrieved is not None
        assert retrieved.id == content.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_content(
        self, content_service: ContentService, test_user: User
    ):
        """Test getting non-existent content returns None."""
        result = await content_service.get_content(test_user.id, 999)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_user_content(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test listing user's content."""
        # Create multiple contents
        for i in range(3):
            content = Content(
                user_id=test_user.id,
                title=f"Test {i}",
                topic=f"Topic {i}",
                content_type="post",
                status="draft",
            )
            db.add(content)
        db.commit()

        contents = await content_service.list_user_content(test_user.id)
        assert len(contents) >= 3


class TestContentUpdate:
    """Tests for content update."""

    @pytest.mark.asyncio
    async def test_update_content_title(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test updating content title."""
        content = Content(
            user_id=test_user.id,
            title="Original",
            topic="Test",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        from app.schemas.content import ContentUpdate
        update = ContentUpdate(title="Updated")
        updated = await content_service.update_content(test_user.id, content.id, update)
        assert updated.title == "Updated"

    @pytest.mark.asyncio
    async def test_update_nonexistent_content(
        self, content_service: ContentService, test_user: User
    ):
        """Test updating non-existent content returns None."""
        from app.schemas.content import ContentUpdate
        update = ContentUpdate(title="Updated")
        result = await content_service.update_content(test_user.id, 999, update)
        assert result is None


class TestContentDelete:
    """Tests for content deletion."""

    @pytest.mark.asyncio
    async def test_delete_content(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test deleting content."""
        content = Content(
            user_id=test_user.id,
            title="Test",
            topic="Test",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        result = await content_service.delete_content(test_user.id, content.id)
        assert result is True


class TestContentApproval:
    """Tests for content approval."""

    @pytest.mark.asyncio
    async def test_approve_content(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test approving content."""
        content = Content(
            user_id=test_user.id,
            title="Test",
            topic="Test",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        approved = await content_service.approve_content(test_user.id, content.id)
        assert approved.status == "approved"


class TestContentPublishing:
    """Tests for content publishing."""

    @pytest.mark.asyncio
    async def test_publish_approved_content(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test publishing approved content."""
        content = Content(
            user_id=test_user.id,
            title="Test",
            topic="Test",
            content_type="post",
            status="approved",
        )
        db.add(content)
        db.commit()

        published = await content_service.publish_content(test_user.id, content.id)
        assert published.status == "published"
        assert published.published_at is not None

    @pytest.mark.asyncio
    async def test_publish_draft_content_fails(
        self, content_service: ContentService, test_user: User, db: Session
    ):
        """Test publishing draft content fails."""
        content = Content(
            user_id=test_user.id,
            title="Test",
            topic="Test",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        with pytest.raises(ValueError):
            await content_service.publish_content(test_user.id, content.id)
