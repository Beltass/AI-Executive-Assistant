"""Speaking opportunities API routes."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import SpeakingOpportunity
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=List[dict])
async def list_opportunities(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List speaking opportunities."""
    user_id = 1  # Placeholder

    query = db.query(SpeakingOpportunity).filter(
        SpeakingOpportunity.user_id == user_id
    )

    if status:
        query = query.filter(SpeakingOpportunity.status == status)

    opportunities = query.all()

    return [
        {
            "id": o.id,
            "conference_name": o.conference_name,
            "topic": o.topic,
            "event_date": o.event_date,
            "deadline": o.deadline,
            "fit_score": o.fit_score,
            "status": o.status,
            "url": o.url,
        }
        for o in opportunities
    ]


@router.get("/top-opportunities")
async def get_top_opportunities(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get top speaking opportunities by fit score."""
    user_id = 1  # Placeholder

    opportunities = (
        db.query(SpeakingOpportunity)
        .filter(SpeakingOpportunity.user_id == user_id)
        .order_by(SpeakingOpportunity.fit_score.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": o.id,
            "conference_name": o.conference_name,
            "topic": o.topic,
            "fit_score": o.fit_score,
            "status": o.status,
        }
        for o in opportunities
    ]


@router.post("/{opportunity_id}/mark-interested")
async def mark_interested(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark opportunity as interested."""
    user_id = 1  # Placeholder

    opportunity = (
        db.query(SpeakingOpportunity)
        .filter(
            SpeakingOpportunity.id == opportunity_id,
            SpeakingOpportunity.user_id == user_id,
        )
        .first()
    )

    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    opportunity.status = "interested"
    db.commit()

    return {"message": "Marked as interested"}


@router.post("/{opportunity_id}/mark-pitched")
async def mark_pitched(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark opportunity as pitched."""
    user_id = 1  # Placeholder

    opportunity = (
        db.query(SpeakingOpportunity)
        .filter(
            SpeakingOpportunity.id == opportunity_id,
            SpeakingOpportunity.user_id == user_id,
        )
        .first()
    )

    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    opportunity.status = "pitched"
    db.commit()

    return {"message": "Marked as pitched"}
