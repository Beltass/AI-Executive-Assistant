"""Pydantic schemas for template-related endpoints."""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


class TemplateBase(BaseModel):
    """Base template schema."""

    name: str
    category: str
    content_type: str
    language: str = "en"
    framework: Optional[str] = None
    system_prompt: str
    examples: Optional[List[dict]] = None


class TemplateCreate(TemplateBase):
    """Schema for creating template."""

    pass


class TemplateUpdate(BaseModel):
    """Schema for updating template."""

    name: Optional[str] = None
    category: Optional[str] = None
    system_prompt: Optional[str] = None
    examples: Optional[List[dict]] = None
    is_active: Optional[bool] = None


class Template(TemplateBase):
    """Template response schema."""

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
