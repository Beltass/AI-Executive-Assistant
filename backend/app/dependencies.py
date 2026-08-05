"""Shared dependencies for the application."""

from typing import Any, Dict

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.security import decode_access_token

security = HTTPBearer()

_UNAUTHENTICATED_HEADERS = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Verify the bearer JWT and return the authenticated user.

    The token's signature and `exp` are checked against the configured secret,
    then the `sub` claim is resolved to a real, active row in `users`. A token
    that is unsigned, expired, tampered with, or points at a user who no longer
    exists gets a 401 — there is no path through this function that trusts an
    unverified token.

    Returns:
        A dict with the resolved ``user_id``, the ``user`` row, and the decoded
        JWT ``claims``.
    """
    payload = decode_access_token(credentials.credentials)

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers=_UNAUTHENTICATED_HEADERS,
        )

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers=_UNAUTHENTICATED_HEADERS,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers=_UNAUTHENTICATED_HEADERS,
        )

    return {"user_id": user.id, "user": user, "claims": payload}
