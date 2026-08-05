"""Service for content generation and management."""

import logging
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.models import (
    Content,
    ContentVariation,
    ScheduledPost,
    EngagementMetric,
    User,
)
from app.services.gemini_service import GeminiService
from app.schemas.content import (
    ContentCreate,
    ContentUpdate,
    ContentStatusEnum,
    VariationTypeEnum,
)

logger = logging.getLogger(__name__)


class ContentService:
    """Service for managing content generation and storage."""

    def __init__(self, db: Session):
        """Initialize content service."""
        self.db = db
        self.gemini = GeminiService()

    async def generate_content(
        self,
        user_id: int,
        topic: str,
        content_type: str,
        platforms: List[str],
        tone: Optional[str] = None,
        language: str = "en",
        additional_context: Optional[str] = None,
    ) -> Content:
        """
        Generate new content and create database record.

        Args:
            user_id: ID of user requesting content
            topic: Topic for content generation
            content_type: Type of content (post, article, thread)
            platforms: Target platforms
            tone: Content tone
            language: Language code
            additional_context: Additional context

        Returns:
            Created Content object
        """
        # Verify user exists
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Generate content variations using Gemini
        generated = await self.gemini.generate_content_variations(
            topic=topic,
            platform=platforms[0] if platforms else "linkedin",
            language=language or user.language,
            tone=tone,
            additional_context=additional_context,
        )

        # Create content record
        content = Content(
            user_id=user_id,
            title=topic,
            topic=topic,
            content_type=content_type,
            main_content=generated.get("main_content", ""),
            platforms=platforms,
            status="draft",
            extra_metadata={
                "tone": tone,
                "language": language,
                "generated_at": datetime.utcnow().isoformat(),
            },
        )

        self.db.add(content)
        self.db.flush()

        # Create variations
        for variation_data in generated.get("variations", []):
            for var_type, var_content in variation_data.items():
                # Map platform to variation type
                variation_type = self._get_variation_type(
                    platforms[0] if platforms else "linkedin"
                )

                variation = ContentVariation(
                    content_id=content.id,
                    variation_type=variation_type,
                    text=var_content.get("text", ""),
                    tone=var_content.get("tone", tone),
                    language=language or user.language,
                    extra_metadata={
                        "hooks": var_content.get("hooks", []),
                    },
                )
                self.db.add(variation)

        self.db.commit()
        return content

    async def get_content(self, user_id: int, content_id: int) -> Optional[Content]:
        """Get content by ID."""
        return (
            self.db.query(Content)
            .filter(Content.id == content_id, Content.user_id == user_id)
            .first()
        )

    async def list_user_content(
        self, user_id: int, skip: int = 0, limit: int = 10, status: Optional[str] = None
    ) -> List[Content]:
        """List user's content with optional filtering."""
        query = self.db.query(Content).filter(Content.user_id == user_id)

        if status:
            query = query.filter(Content.status == status)

        return query.offset(skip).limit(limit).all()

    async def update_content(
        self, user_id: int, content_id: int, update_data: ContentUpdate
    ) -> Optional[Content]:
        """Update content."""
        content = await self.get_content(user_id, content_id)
        if not content:
            return None

        update_dict = update_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(content, key, value)

        self.db.commit()
        return content

    async def delete_content(self, user_id: int, content_id: int) -> bool:
        """Delete content (soft delete by archiving)."""
        content = await self.get_content(user_id, content_id)
        if not content:
            return False

        content.status = ContentStatusEnum.ARCHIVED
        self.db.commit()
        return True

    async def approve_content(self, user_id: int, content_id: int) -> Optional[Content]:
        """Approve content for publishing."""
        content = await self.get_content(user_id, content_id)
        if not content:
            return None

        content.status = ContentStatusEnum.APPROVED
        self.db.commit()
        return content

    async def publish_content(self, user_id: int, content_id: int) -> Optional[Content]:
        """Publish content."""
        content = await self.get_content(user_id, content_id)
        if not content:
            return None

        if content.status != ContentStatusEnum.APPROVED:
            raise ValueError("Content must be approved before publishing")

        content.status = ContentStatusEnum.PUBLISHED
        content.published_at = datetime.utcnow()
        self.db.commit()
        return content

    async def schedule_post(
        self,
        content_id: int,
        platform: str,
        scheduled_time: datetime,
    ) -> ScheduledPost:
        """Schedule content for posting."""
        scheduled_post = ScheduledPost(
            content_id=content_id,
            platform=platform,
            scheduled_time=scheduled_time,
            status="pending",
        )

        self.db.add(scheduled_post)
        self.db.commit()
        return scheduled_post

    async def record_engagement(
        self,
        content_id: int,
        platform: str,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        clicks: int = 0,
    ) -> EngagementMetric:
        """Record engagement metrics for content."""
        metric = EngagementMetric(
            content_id=content_id,
            platform=platform,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            clicks=clicks,
        )

        self.db.add(metric)
        self.db.commit()
        return metric

    def _get_variation_type(self, platform: str) -> str:
        """Map platform to variation type."""
        mapping = {
            "linkedin": VariationTypeEnum.LINKEDIN,
            "twitter": VariationTypeEnum.TWITTER,
            "instagram": VariationTypeEnum.INSTAGRAM,
            "email": VariationTypeEnum.EMAIL,
        }
        return mapping.get(platform, VariationTypeEnum.LINKEDIN)
