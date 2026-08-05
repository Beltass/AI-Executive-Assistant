"""LinkedIn network API routes."""

import logging
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import LinkedInNetwork
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=List[dict])
async def list_network(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List user's LinkedIn network contacts."""
    user_id = 1  # Placeholder

    networks = (
        db.query(LinkedInNetwork).filter(LinkedInNetwork.user_id == user_id).all()
    )

    return [
        {
            "id": n.id,
            "contact_id": n.contact_id,
            "name": n.name,
            "current_title": n.current_title,
            "company": n.company,
            "last_contacted": n.last_contacted,
        }
        for n in networks
    ]


@router.post("/sync")
async def sync_network(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Sync LinkedIn network from LinkedIn API."""
    # TODO: Integrate with LinkedIn API to fetch and sync contacts

    return {"message": "Network sync started"}


@router.get("/job-changes")
async def get_job_changes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get recent job changes in network."""
    user_id = 1  # Placeholder

    # Get recent network updates with job changes
    networks = (
        db.query(LinkedInNetwork)
        .filter(LinkedInNetwork.user_id == user_id)
        .order_by(LinkedInNetwork.job_change_date.desc())
        .limit(10)
        .all()
    )

    return [
        {
            "id": n.id,
            "name": n.name,
            "previous_company": (
                n.extra_metadata.get("previous_company") if n.extra_metadata else None
            ),
            "new_company": n.company,
            "new_title": n.current_title,
            "change_date": n.job_change_date,
        }
        for n in networks
    ]
