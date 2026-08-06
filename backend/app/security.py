"""JWT creation and verification helpers.

This module owns every decision about how an access token is signed and how a
signature is checked. Keeping it in one place means there is exactly one answer
to "is this token trustworthy?" instead of one answer per route.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status

from app.config import settings

# config.py ships this value so a fresh checkout boots. It is published in the
# repository, which makes it a *known* key: anyone can mint a valid-looking
# token with it. Treating it as "configured" would mean the verification below
# proves nothing, so it is refused explicitly rather than accepted quietly.
PLACEHOLDER_SECRET_KEY = "your-secret-key-change-in-production"

_UNAUTHENTICATED_HEADERS = {"WWW-Authenticate": "Bearer"}


class AuthConfigurationError(RuntimeError):
    """Raised when the signing secret is missing or is the shipped placeholder."""


def get_signing_key() -> str:
    """Return the configured JWT signing key.

    Raises:
        AuthConfigurationError: if no usable secret is configured.
    """
    secret = (settings.SECRET_KEY or "").strip()

    if not secret:
        raise AuthConfigurationError(
            "SECRET_KEY is not set; refusing to issue or accept JWTs."
        )

    if secret == PLACEHOLDER_SECRET_KEY:
        raise AuthConfigurationError(
            "SECRET_KEY is still the placeholder value from config.py; "
            "set a real secret before serving authenticated requests."
        )

    return secret


def get_algorithm() -> str:
    """Return the configured JWT algorithm, rejecting the unsigned `none` alg."""
    algorithm = (settings.ALGORITHM or "").strip()

    if not algorithm or algorithm.lower() == "none":
        raise AuthConfigurationError(
            "ALGORITHM must name a real signing algorithm (e.g. HS256)."
        )

    return algorithm


def create_access_token(
    subject: Any,
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Mint a signed access token.

    Args:
        subject: The user identifier stored in the `sub` claim.
        expires_delta: Lifetime override; defaults to
            ``settings.ACCESS_TOKEN_EXPIRE_MINUTES``.
        additional_claims: Extra claims merged into the payload.

    Returns:
        The encoded JWT.
    """
    now = datetime.now(timezone.utc)
    lifetime = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": now + lifetime,
    }

    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(payload, get_signing_key(), algorithm=get_algorithm())


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and fully verify a JWT.

    Verification covers the signature, the algorithm (only the configured one is
    accepted, so an attacker cannot downgrade to `none`), and the `exp` claim.

    Args:
        token: The raw bearer token.

    Returns:
        The decoded claim set.

    Raises:
        HTTPException: 401 for any token that fails verification, 500 when the
            service has no usable signing secret.
    """
    try:
        signing_key = get_signing_key()
        algorithm = get_algorithm()
    except AuthConfigurationError as exc:
        # Never fall through to "token looks non-empty, let it in". Without a
        # secret there is nothing to verify against, so the endpoint closes.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication is not configured: {exc}",
        ) from exc

    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers=_UNAUTHENTICATED_HEADERS,
        )

    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=[algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers=_UNAUTHENTICATED_HEADERS,
        ) from exc
    except jwt.InvalidTokenError as exc:
        # Covers bad signatures, wrong algorithms, malformed tokens and missing
        # required claims. The reason is deliberately not echoed back to the
        # caller; it goes no further than the 401.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers=_UNAUTHENTICATED_HEADERS,
        ) from exc
