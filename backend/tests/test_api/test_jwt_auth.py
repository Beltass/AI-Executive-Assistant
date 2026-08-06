"""Tests that the bearer token is actually verified, not merely present.

The dependency these exercise used to accept any non-empty string. Each test
below is a token that *looks* fine to a naive check and must still be refused.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Content, User
from app.security import PLACEHOLDER_SECRET_KEY, create_access_token

from tests.conftest import TEST_SECRET_KEY


@pytest.fixture
def user(db: Session) -> User:
    """A persisted, active user the token can point at."""
    user = User(email="jwt-user@example.com", name="JWT User", language="en")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestTokenVerification:
    """A token is trusted only if its signature and claims check out."""

    def test_valid_token_is_accepted(self, client: TestClient, user: User):
        response = client.get(
            "/api/content", headers=_auth(create_access_token(user.id))
        )

        assert response.status_code == 200

    def test_request_without_token_is_rejected(self, client: TestClient, user: User):
        response = client.get("/api/content")

        assert response.status_code in (401, 403)

    def test_opaque_non_jwt_string_is_rejected(self, client: TestClient, user: User):
        """The old placeholder let this through purely because it was non-empty."""
        response = client.get("/api/content", headers=_auth("definitely-not-a-jwt"))

        assert response.status_code == 401

    def test_expired_token_is_rejected(self, client: TestClient, user: User):
        expired = create_access_token(user.id, expires_delta=timedelta(minutes=-5))

        response = client.get("/api/content", headers=_auth(expired))

        assert response.status_code == 401
        assert response.json()["detail"] == "Token has expired"

    def test_token_signed_with_another_key_is_rejected(
        self, client: TestClient, user: User
    ):
        """Well-formed, unexpired, correct claims — but a forged signature."""
        forged = jwt.encode(
            {
                "sub": str(user.id),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "an-attacker-controlled-key",
            algorithm="HS256",
        )

        response = client.get("/api/content", headers=_auth(forged))

        assert response.status_code == 401

    def test_tampered_payload_is_rejected(self, client: TestClient, user: User):
        """Swapping the payload segment invalidates the signature."""
        valid = create_access_token(user.id)
        header, _payload, signature = valid.split(".")
        other = create_access_token(user.id + 1)
        tampered = f"{header}.{other.split('.')[1]}.{signature}"

        response = client.get("/api/content", headers=_auth(tampered))

        assert response.status_code == 401

    def test_unsigned_alg_none_token_is_rejected(self, client: TestClient, user: User):
        """The classic downgrade: a token that claims it needs no signature."""
        unsigned = jwt.encode(
            {
                "sub": str(user.id),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            key="",
            algorithm="none",
        )

        response = client.get("/api/content", headers=_auth(unsigned))

        assert response.status_code == 401

    def test_token_without_expiry_is_rejected(self, client: TestClient, user: User):
        """A token that never expires is not a token we accept."""
        eternal = jwt.encode({"sub": str(user.id)}, TEST_SECRET_KEY, algorithm="HS256")

        response = client.get("/api/content", headers=_auth(eternal))

        assert response.status_code == 401

    def test_token_without_subject_is_rejected(self, client: TestClient, user: User):
        subjectless = jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            TEST_SECRET_KEY,
            algorithm="HS256",
        )

        response = client.get("/api/content", headers=_auth(subjectless))

        assert response.status_code == 401


class TestSubjectResolution:
    """A verified signature is not enough; the subject must be a real user."""

    def test_token_for_unknown_user_is_rejected(self, client: TestClient, user: User):
        response = client.get(
            "/api/content", headers=_auth(create_access_token(999_999))
        )

        assert response.status_code == 401

    def test_token_for_deactivated_user_is_rejected(
        self, client: TestClient, db: Session, user: User
    ):
        user.is_active = False
        db.commit()

        response = client.get(
            "/api/content", headers=_auth(create_access_token(user.id))
        )

        assert response.status_code == 401

    def test_non_numeric_subject_is_rejected(self, client: TestClient, user: User):
        response = client.get(
            "/api/content", headers=_auth(create_access_token("not-a-user-id"))
        )

        assert response.status_code == 401


class TestUserScoping:
    """The route reads its user id from the token, not from a hardcoded 1."""

    def test_listing_returns_only_the_token_holders_content(
        self, client: TestClient, db: Session
    ):
        owner = User(email="owner@example.com", name="Owner", language="en")
        other = User(email="other@example.com", name="Other", language="en")
        db.add_all([owner, other])
        db.commit()
        db.refresh(owner)
        db.refresh(other)

        db.add_all(
            [
                Content(
                    user_id=owner.id,
                    title="Owner post",
                    topic="Owner topic",
                    content_type="post",
                    main_content="owner",
                    status="draft",
                    platforms=["linkedin"],
                ),
                Content(
                    user_id=other.id,
                    title="Other post",
                    topic="Other topic",
                    content_type="post",
                    main_content="other",
                    status="draft",
                    platforms=["linkedin"],
                ),
            ]
        )
        db.commit()

        response = client.get(
            "/api/content", headers=_auth(create_access_token(other.id))
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()]
        assert titles == ["Other post"]

    def test_other_users_content_is_not_reachable_by_id(
        self, client: TestClient, db: Session
    ):
        owner = User(email="owner2@example.com", name="Owner", language="en")
        intruder = User(email="intruder@example.com", name="Intruder", language="en")
        db.add_all([owner, intruder])
        db.commit()
        db.refresh(owner)
        db.refresh(intruder)

        secret = Content(
            user_id=owner.id,
            title="Private",
            topic="Private",
            content_type="post",
            main_content="private",
            status="draft",
            platforms=["linkedin"],
        )
        db.add(secret)
        db.commit()
        db.refresh(secret)

        response = client.get(
            f"/api/content/{secret.id}",
            headers=_auth(create_access_token(intruder.id)),
        )

        assert response.status_code == 404


class TestUnconfiguredSecret:
    """With no usable secret there is nothing to verify, so the door closes."""

    def test_placeholder_secret_closes_the_endpoint(
        self, client: TestClient, db: Session, user: User, monkeypatch
    ):
        token = create_access_token(user.id)
        monkeypatch.setattr(settings, "SECRET_KEY", PLACEHOLDER_SECRET_KEY)

        response = client.get("/api/content", headers=_auth(token))

        assert response.status_code == 500
        assert "not configured" in response.json()["detail"]

    def test_empty_secret_closes_the_endpoint(
        self, client: TestClient, db: Session, user: User, monkeypatch
    ):
        token = create_access_token(user.id)
        monkeypatch.setattr(settings, "SECRET_KEY", "   ")

        response = client.get("/api/content", headers=_auth(token))

        assert response.status_code == 500
        assert "not configured" in response.json()["detail"]

    def test_token_minting_also_refuses_a_placeholder_secret(self, monkeypatch):
        from app.security import AuthConfigurationError

        monkeypatch.setattr(settings, "SECRET_KEY", PLACEHOLDER_SECRET_KEY)

        with pytest.raises(AuthConfigurationError):
            create_access_token(1)
