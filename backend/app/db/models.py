"""SQLAlchemy models for the Content Creation Platform."""

from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Float,
    Boolean,
    JSON,
    ForeignKey,
    Index,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from app.db.database import Base


class ContentTypeEnum(str, Enum):
    """Content type enumeration."""
    POST = "post"
    ARTICLE = "article"
    THREAD = "thread"


class ContentStatusEnum(str, Enum):
    """Content status enumeration."""
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class VariationTypeEnum(str, Enum):
    """Content variation type enumeration."""
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    EMAIL = "email"


class PostStatusEnum(str, Enum):
    """Scheduled post status enumeration."""
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"


class OpportunityStatusEnum(str, Enum):
    """Speaking opportunity status enumeration."""
    DISCOVERED = "discovered"
    INTERESTED = "interested"
    PITCHED = "pitched"
    CONFIRMED = "confirmed"


class User(Base):
    """User model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    language = Column(String(5), default="en", nullable=False)
    linkedin_profile_url = Column(String(500))
    slack_id = Column(String(100), index=True)
    google_token = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default={})

    # Relationships
    contents = relationship("Content", back_populates="user", cascade="all, delete-orphan")
    networks = relationship("LinkedInNetwork", back_populates="user", cascade="all, delete-orphan")
    opportunities = relationship("SpeakingOpportunity", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_user_email", "email"),
        Index("idx_user_slack_id", "slack_id"),
    )


class Content(Base):
    """Content model."""
    __tablename__ = "contents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    topic = Column(String(255), nullable=False)
    content_type = Column(SQLEnum(ContentTypeEnum), nullable=False)
    status = Column(SQLEnum(ContentStatusEnum), default=ContentStatusEnum.DRAFT)
    main_content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime)
    platforms = Column(JSON, default=[])
    # ``metadata`` is reserved on SQLAlchemy's Declarative Base (it holds the
    # MetaData registry), so a mapped attribute of that name makes the whole
    # module fail to import and takes the entire test suite down with it.
    # The Python attribute is renamed; the DB column keeps its old name.
    extra_metadata = Column("metadata", JSON, default={})

    # Relationships
    user = relationship("User", back_populates="contents")
    variations = relationship("ContentVariation", back_populates="content", cascade="all, delete-orphan")
    scheduled_posts = relationship("ScheduledPost", back_populates="content", cascade="all, delete-orphan")
    metrics = relationship("EngagementMetric", back_populates="content", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_content_user_id", "user_id"),
        Index("idx_content_status", "status"),
        Index("idx_content_created_at", "created_at"),
    )


class ContentVariation(Base):
    """Content variation model for multi-platform content."""
    __tablename__ = "content_variations"

    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey("contents.id"), nullable=False, index=True)
    variation_type = Column(SQLEnum(VariationTypeEnum), nullable=False)
    text = Column(Text, nullable=False)
    tone = Column(String(100))
    language = Column(String(5), default="en")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # ``metadata`` is reserved on SQLAlchemy's Declarative Base (it holds the
    # MetaData registry), so a mapped attribute of that name makes the whole
    # module fail to import and takes the entire test suite down with it.
    # The Python attribute is renamed; the DB column keeps its old name.
    extra_metadata = Column("metadata", JSON, default={})

    # Relationships
    content = relationship("Content", back_populates="variations")

    __table_args__ = (
        Index("idx_variation_content_id", "content_id"),
        Index("idx_variation_type", "variation_type"),
    )


class ScheduledPost(Base):
    """Scheduled post model."""
    __tablename__ = "scheduled_posts"

    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey("contents.id"), nullable=False, index=True)
    platform = Column(String(100), nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    status = Column(SQLEnum(PostStatusEnum), default=PostStatusEnum.PENDING)
    posted_at = Column(DateTime)
    engagement_metrics = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    content = relationship("Content", back_populates="scheduled_posts")

    __table_args__ = (
        Index("idx_scheduled_post_content_id", "content_id"),
        Index("idx_scheduled_post_platform", "platform"),
        Index("idx_scheduled_post_scheduled_time", "scheduled_time"),
    )


class LinkedInNetwork(Base):
    """LinkedIn network contacts model."""
    __tablename__ = "linkedin_networks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    current_title = Column(String(255))
    company = Column(String(255))
    job_change_date = Column(DateTime)
    last_contacted = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # ``metadata`` is reserved on SQLAlchemy's Declarative Base (it holds the
    # MetaData registry), so a mapped attribute of that name makes the whole
    # module fail to import and takes the entire test suite down with it.
    # The Python attribute is renamed; the DB column keeps its old name.
    extra_metadata = Column("metadata", JSON, default={})

    # Relationships
    user = relationship("User", back_populates="networks")

    __table_args__ = (
        Index("idx_network_user_id", "user_id"),
        Index("idx_network_contact_id", "contact_id"),
    )


class SpeakingOpportunity(Base):
    """Speaking opportunity model."""
    __tablename__ = "speaking_opportunities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conference_name = Column(String(500), nullable=False)
    topic = Column(String(500))
    event_date = Column(DateTime, nullable=False)
    deadline = Column(DateTime)
    fit_score = Column(Float, default=0.0)
    status = Column(SQLEnum(OpportunityStatusEnum), default=OpportunityStatusEnum.DISCOVERED)
    url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # ``metadata`` is reserved on SQLAlchemy's Declarative Base (it holds the
    # MetaData registry), so a mapped attribute of that name makes the whole
    # module fail to import and takes the entire test suite down with it.
    # The Python attribute is renamed; the DB column keeps its old name.
    extra_metadata = Column("metadata", JSON, default={})

    # Relationships
    user = relationship("User", back_populates="opportunities")

    __table_args__ = (
        Index("idx_opportunity_user_id", "user_id"),
        Index("idx_opportunity_status", "status"),
        Index("idx_opportunity_fit_score", "fit_score"),
    )


class IndustryReport(Base):
    """Industry report model."""
    __tablename__ = "industry_reports"

    id = Column(Integer, primary_key=True, index=True)
    publisher = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    topic = Column(String(255))
    published_date = Column(DateTime)
    url = Column(String(500))
    summary = Column(Text)
    relevance_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # ``metadata`` is reserved on SQLAlchemy's Declarative Base (it holds the
    # MetaData registry), so a mapped attribute of that name makes the whole
    # module fail to import and takes the entire test suite down with it.
    # The Python attribute is renamed; the DB column keeps its old name.
    extra_metadata = Column("metadata", JSON, default={})

    __table_args__ = (
        Index("idx_report_topic", "topic"),
        Index("idx_report_relevance", "relevance_score"),
    )


class EngagementMetric(Base):
    """Engagement metrics model."""
    __tablename__ = "engagement_metrics"

    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey("contents.id"), nullable=False, index=True)
    platform = Column(String(100), nullable=False)
    metric_date = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    content = relationship("Content", back_populates="metrics")

    __table_args__ = (
        Index("idx_metric_content_id", "content_id"),
        Index("idx_metric_platform", "platform"),
        Index("idx_metric_date", "metric_date"),
    )


class Template(Base):
    """Content template model."""
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    content_type = Column(String(100), nullable=False)
    language = Column(String(5), default="en")
    framework = Column(String(255))
    system_prompt = Column(Text, nullable=False)
    examples = Column(JSON, default=[])
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("idx_template_language", "language"),
        Index("idx_template_category", "category"),
    )
