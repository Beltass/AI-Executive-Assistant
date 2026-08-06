"""Analytics API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.analytics_service import AnalyticsService
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/content/{content_id}")
async def get_content_metrics(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get metrics for specific content."""
    try:
        service = AnalyticsService(db)
        metrics = await service.get_content_metrics(content_id)
        return metrics

    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/summary")
async def get_user_summary(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get user analytics summary."""
    user_id = 1  # Placeholder

    try:
        service = AnalyticsService(db)
        analytics = await service.get_user_analytics(user_id, days=days)
        return analytics

    except Exception as e:
        logger.error(f"Error fetching analytics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/platform-performance")
async def get_platform_performance(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get performance breakdown by platform."""
    user_id = 1  # Placeholder

    try:
        service = AnalyticsService(db)
        performance = await service.get_platform_performance(user_id)
        return {"performance": performance}

    except Exception as e:
        logger.error(f"Error fetching platform performance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/trends")
async def get_engagement_trends(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get engagement trends over time."""
    user_id = 1  # Placeholder

    try:
        service = AnalyticsService(db)
        trends = await service.get_engagement_trends(user_id, days=days)
        return trends

    except Exception as e:
        logger.error(f"Error fetching trends: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
