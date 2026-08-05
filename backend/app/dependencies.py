"""Shared dependencies for the application."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.config import settings

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """
    Verify JWT token and return current user.

    In production, integrate with Google OAuth or JWT validation.
    """
    token = credentials.credentials

    # TODO: Implement actual JWT verification
    # For now, this is a placeholder that validates token exists
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production, decode JWT token and validate
    # user = db.query(User).filter(User.id == user_id).first()
    # if not user:
    #     raise HTTPException(status_code=404, detail="User not found")

    return {"token": token}
