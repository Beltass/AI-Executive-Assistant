"""Service for analytics and metrics."""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models import EngagementMetric, Content, ScheduledPost

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics calculations and reporting."""

    def __init__(self, db: Session):
        """Initialize analytics service."""
        self.db = db

    async def get_content_metrics(self, content_id: int) -> Dict[str, Any]:
        """Get aggregated metrics for content."""
        metrics = (
            self.db.query(EngagementMetric)
            .filter(EngagementMetric.content_id == content_id)
            .all()
        )

        if not metrics:
            return self._empty_metrics()

        total_views = sum(m.views for m in metrics)
        total_likes = sum(m.likes for m in metrics)
        total_comments = sum(m.comments for m in metrics)
        total_shares = sum(m.shares for m in metrics)
        total_clicks = sum(m.clicks for m in metrics)

        engagement_rate = 0
        if total_views > 0:
            engagement_rate = (
                (total_likes + total_comments + total_shares) / total_views * 100
            )

        return {
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "total_clicks": total_clicks,
            "engagement_rate": round(engagement_rate, 2),
            "by_platform": self._group_metrics_by_platform(metrics),
        }

    async def get_user_analytics(self, user_id: int, days: int = 30) -> Dict[str, Any]:
        """Get analytics summary for user."""
        since = datetime.utcnow() - timedelta(days=days)

        # Get user's content
        contents = (
            self.db.query(Content)
            .filter(Content.user_id == user_id, Content.created_at >= since)
            .all()
        )

        if not contents:
            return self._empty_user_analytics()

        content_ids = [c.id for c in contents]

        # Get metrics for all user's content
        metrics = (
            self.db.query(EngagementMetric)
            .filter(
                EngagementMetric.content_id.in_(content_ids),
                EngagementMetric.metric_date >= since,
            )
            .all()
        )

        total_content = len(contents)
        published = len([c for c in contents if c.status == "published"])
        draft = len([c for c in contents if c.status == "draft"])
        approved = len([c for c in contents if c.status == "approved"])

        total_views = sum(m.views for m in metrics)
        total_engagement = sum(m.likes + m.comments + m.shares for m in metrics)

        return {
            "period_days": days,
            "total_content": total_content,
            "published_content": published,
            "draft_content": draft,
            "approved_content": approved,
            "total_views": total_views,
            "total_engagement": total_engagement,
            "average_engagement_per_post": (
                total_engagement / total_content if total_content > 0 else 0
            ),
            "platform_performance": self._get_platform_performance(metrics),
            "top_content": await self._get_top_content(contents, metrics),
        }

    async def get_platform_performance(self, user_id: int) -> Dict[str, Any]:
        """Get performance breakdown by platform."""
        contents = self.db.query(Content).filter(Content.user_id == user_id).all()

        content_ids = [c.id for c in contents]

        metrics = (
            self.db.query(EngagementMetric)
            .filter(EngagementMetric.content_id.in_(content_ids))
            .all()
        )

        return self._group_metrics_by_platform(metrics)

    async def get_engagement_trends(
        self, user_id: int, days: int = 30
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get engagement trends over time."""
        since = datetime.utcnow() - timedelta(days=days)

        contents = self.db.query(Content).filter(Content.user_id == user_id).all()

        content_ids = [c.id for c in contents]

        metrics = (
            self.db.query(EngagementMetric)
            .filter(
                EngagementMetric.content_id.in_(content_ids),
                EngagementMetric.metric_date >= since,
            )
            .order_by(EngagementMetric.metric_date)
            .all()
        )

        # Group by date
        trends_by_date = {}
        for metric in metrics:
            date_key = metric.metric_date.date().isoformat()
            if date_key not in trends_by_date:
                trends_by_date[date_key] = {
                    "date": date_key,
                    "views": 0,
                    "engagement": 0,
                }

            trends_by_date[date_key]["views"] += metric.views
            trends_by_date[date_key]["engagement"] += (
                metric.likes + metric.comments + metric.shares
            )

        return {"daily_trends": list(trends_by_date.values())}

    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics structure."""
        return {
            "total_views": 0,
            "total_likes": 0,
            "total_comments": 0,
            "total_shares": 0,
            "total_clicks": 0,
            "engagement_rate": 0,
            "by_platform": {},
        }

    def _empty_user_analytics(self) -> Dict[str, Any]:
        """Return empty user analytics structure."""
        return {
            "period_days": 30,
            "total_content": 0,
            "published_content": 0,
            "draft_content": 0,
            "approved_content": 0,
            "total_views": 0,
            "total_engagement": 0,
            "average_engagement_per_post": 0,
            "platform_performance": {},
            "top_content": [],
        }

    def _group_metrics_by_platform(
        self, metrics: List[EngagementMetric]
    ) -> Dict[str, Dict[str, Any]]:
        """Group metrics by platform."""
        by_platform = {}

        for metric in metrics:
            if metric.platform not in by_platform:
                by_platform[metric.platform] = {
                    "views": 0,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "clicks": 0,
                }

            by_platform[metric.platform]["views"] += metric.views
            by_platform[metric.platform]["likes"] += metric.likes
            by_platform[metric.platform]["comments"] += metric.comments
            by_platform[metric.platform]["shares"] += metric.shares
            by_platform[metric.platform]["clicks"] += metric.clicks

        return by_platform

    def _get_platform_performance(
        self, metrics: List[EngagementMetric]
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate performance metrics by platform."""
        performance = {}
        platforms = set(m.platform for m in metrics)

        for platform in platforms:
            platform_metrics = [m for m in metrics if m.platform == platform]
            total_views = sum(m.views for m in platform_metrics)
            total_engagement = sum(
                m.likes + m.comments + m.shares for m in platform_metrics
            )

            performance[platform] = {
                "views": total_views,
                "engagement": total_engagement,
                "engagement_rate": (
                    total_engagement / total_views * 100 if total_views > 0 else 0
                ),
            }

        return performance

    async def _get_top_content(
        self, contents: List[Content], metrics: List[EngagementMetric]
    ) -> List[Dict[str, Any]]:
        """Get top performing content."""
        content_performance = {}

        for metric in metrics:
            if metric.content_id not in content_performance:
                content_performance[metric.content_id] = {
                    "views": 0,
                    "engagement": 0,
                }

            content_performance[metric.content_id]["views"] += metric.views
            content_performance[metric.content_id]["engagement"] += (
                metric.likes + metric.comments + metric.shares
            )

        # Sort by engagement and get top 5
        top_ids = sorted(
            content_performance.items(),
            key=lambda x: x[1]["engagement"],
            reverse=True,
        )[:5]

        top_content = []
        for content_id, perf in top_ids:
            content = next((c for c in contents if c.id == content_id), None)
            if content:
                top_content.append(
                    {
                        "id": content.id,
                        "title": content.title,
                        "views": perf["views"],
                        "engagement": perf["engagement"],
                    }
                )

        return top_content
