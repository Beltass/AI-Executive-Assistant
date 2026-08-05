"""Content generation API routes."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.content import (
    Content,
    ContentCreate,
    ContentUpdate,
    ContentGenerateRequest,
    ContentGenerateResponse,
)
from app.services.content_service import ContentService
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate", response_model=ContentGenerateResponse)
async def generate_content(
    request: ContentGenerateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Generate new content using AI."""
    # TODO: Extract user_id from JWT token in current_user
    user_id = 1  # Placeholder - should come from current_user

    try:
        service = ContentService(db)

        content = await service.generate_content(
            user_id=user_id,
            topic=request.topic,
            content_type=request.content_type,
            platforms=request.platforms,
            tone=request.tone,
            language=request.language,
            additional_context=request.additional_context,
        )

        return ContentGenerateResponse(
            content_id=content.id,
            title=content.title,
            main_content=content.main_content or "",
            variations=[],
            status=content.status,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating content: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{content_id}", response_model=Content)
async def get_content(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get content by ID."""
    user_id = 1  # Placeholder

    service = ContentService(db)
    content = await service.get_content(user_id=user_id, content_id=content_id)

    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    return content


@router.get("", response_model=List[Content])
async def list_content(
    skip: int = 0,
    limit: int = 10,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List user's content."""
    user_id = 1  # Placeholder

    service = ContentService(db)
    contents = await service.list_user_content(
        user_id=user_id, skip=skip, limit=limit, status=status
    )

    return contents


@router.put("/{content_id}", response_model=Content)
async def update_content(
    content_id: int,
    update: ContentUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update content."""
    user_id = 1  # Placeholder

    service = ContentService(db)
    content = await service.update_content(
        user_id=user_id, content_id=content_id, update_data=update
    )

    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    return content


@router.delete("/{content_id}")
async def delete_content(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete content."""
    user_id = 1  # Placeholder

    service = ContentService(db)
    success = await service.delete_content(user_id=user_id, content_id=content_id)

    if not success:
        raise HTTPException(status_code=404, detail="Content not found")

    return {"message": "Content deleted"}


@router.post("/{content_id}/approve")
async def approve_content(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Approve content for publishing."""
    user_id = 1  # Placeholder

    service = ContentService(db)
    content = await service.approve_content(user_id=user_id, content_id=content_id)

    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    return {"message": "Content approved", "content_id": content.id}


@router.post("/{content_id}/publish")
async def publish_content(
    content_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Publish content."""
    user_id = 1  # Placeholder

    try:
        service = ContentService(db)
        content = await service.publish_content(user_id=user_id, content_id=content_id)

        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

        return {"message": "Content published", "content_id": content.id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
