"""Pydantic schemas for user-related endpoints."""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    name: str
    language: str = "en"
    linkedin_profile_url: Optional[str] = None
    slack_id: Optional[str] = None
    settings: Optional[dict] = None


class UserCreate(UserBase):
    """Schema for creating user."""

    google_token: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for updating user."""

    name: Optional[str] = None
    language: Optional[str] = None
    linkedin_profile_url: Optional[str] = None
    settings: Optional[dict] = None


class User(UserBase):
    """User response schema."""

    id: int
    created_at: datetime
    updated_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    """User API response schema."""

    id: int
    email: str
    name: str
    language: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
