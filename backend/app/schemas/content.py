"""Pydantic schemas for content-related endpoints."""

from datetime import datetime
from typing import List, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field


class ContentTypeEnum(str, Enum):
    """Content type options."""
    POST = "post"
    ARTICLE = "article"
    THREAD = "thread"


class ContentStatusEnum(str, Enum):
    """Content status options."""
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class VariationTypeEnum(str, Enum):
    """Variation type options."""
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    EMAIL = "email"


class ContentVariationBase(BaseModel):
    """Base content variation schema."""
    variation_type: VariationTypeEnum
    text: str
    tone: Optional[str] = None
    language: str = "en"
    extra_metadata: Optional[dict] = None


class ContentVariationCreate(ContentVariationBase):
    """Schema for creating content variation."""
    pass


class ContentVariation(ContentVariationBase):
    """Content variation response schema."""
    id: int
    content_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ContentBase(BaseModel):
    """Base content schema."""
    title: str
    topic: str
    content_type: ContentTypeEnum
    main_content: Optional[str] = None
    platforms: List[str] = []
    extra_metadata: Optional[dict] = None


class ContentCreate(ContentBase):
    """Schema for creating content."""
    pass


class ContentUpdate(BaseModel):
    """Schema for updating content."""
    title: Optional[str] = None
    topic: Optional[str] = None
    content_type: Optional[ContentTypeEnum] = None
    main_content: Optional[str] = None
    status: Optional[ContentStatusEnum] = None
    platforms: Optional[List[str]] = None
    extra_metadata: Optional[dict] = None


class Content(ContentBase):
    """Content response schema."""
    id: int
    user_id: int
    status: ContentStatusEnum
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    variations: List[ContentVariation] = []

    class Config:
        from_attributes = True


class ContentGenerateRequest(BaseModel):
    """Request schema for content generation."""
    topic: str = Field(..., description="Topic to generate content for")
    content_type: ContentTypeEnum = Field(default=ContentTypeEnum.POST)
    platforms: List[str] = Field(default=["linkedin"], description="Target platforms")
    tone: Optional[str] = Field(None, description="Tone of content (e.g., professional, casual)")
    language: str = Field(default="en", description="Language code")
    additional_context: Optional[str] = Field(None, description="Additional context for generation")


class ContentGenerateResponse(BaseModel):
    """Response schema for content generation."""
    content_id: int
    title: str
    main_content: str
    variations: List[ContentVariation]
    status: ContentStatusEnum
