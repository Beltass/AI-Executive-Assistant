"""Template API routes."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Template
from app.schemas.template import Template as TemplateSchema, TemplateCreate, TemplateUpdate
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=List[TemplateSchema])
async def list_templates(
    language: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List available templates."""
    query = db.query(Template).filter(Template.is_active == True)

    if language:
        query = query.filter(Template.language == language)

    if category:
        query = query.filter(Template.category == category)

    return query.all()


@router.get("/{template_id}", response_model=TemplateSchema)
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get template by ID."""
    template = db.query(Template).filter(Template.id == template_id).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.post("", response_model=TemplateSchema)
async def create_template(
    template: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create new template."""
    db_template = Template(**template.model_dump())
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


@router.put("/{template_id}", response_model=TemplateSchema)
async def update_template(
    template_id: int,
    template: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update template."""
    db_template = db.query(Template).filter(Template.id == template_id).first()

    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = template.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_template, key, value)

    db.commit()
    db.refresh(db_template)
    return db_template


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete template."""
    db_template = db.query(Template).filter(Template.id == template_id).first()

    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")

    db.delete(db_template)
    db.commit()

    return {"message": "Template deleted"}
