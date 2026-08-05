"""Comprehensive Google OAuth 2.0 authentication and token management.

Provides a production-ready GoogleOAuthClient class for managing OAuth authentication
with Gmail, Calendar, and Drive services. Supports both local development and
production environments with PKCE security, automatic token refresh, and comprehensive
error handling.

Configuration (via environment variables):
    - GOOGLE_OAUTH_CLIENT_ID: OAuth client ID
    - GOOGLE_OAUTH_CLIENT_SECRET: OAuth client secret
    - GOOGLE_OAUTH_REFRESH_TOKEN: Stored refresh token (for cloud environments)
    - GOOGLE_OAUTH_CALLBACK_URL: OAuth callback URL (default: http://localhost:8080/oauth/callback)

Example usage:
    from ai_assistant.integrations.google_oauth import GoogleOAuthClient

    client = GoogleOAuthClient()

    # Get OAuth URL for user authentication
    auth_url, state = client.get_auth_url(['gmail', 'calendar'])

    # After user grants access, exchange code for tokens
    tokens = client.exchange_code_for_tokens(auth_code, callback_url)

    # Use Gmail service
    gmail_service = client.get_gmail_service()
    messages = client.list_messages(query='from:example@gmail.com', max_results=10)

    # Use Calendar service
    calendar_service = client.get_calendar_service()
    events = client.list_events(max_results=10)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import Resource
    from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# OAuth 2.0 scope mappings
SCOPE_MAPPINGS = {
    "gmail_read": "https://www.googleapis.com/auth/gmail.readonly",
    "gmail_send": "https://www.googleapis.com/auth/gmail.send",
    "gmail_modify": "https://www.googleapis.com/auth/gmail.modify",
    "calendar_read": "https://www.googleapis.com/auth/calendar.readonly",
    "calendar_write": "https://www.googleapis.com/auth/calendar",
    "drive_read": "https://www.googleapis.com/auth/drive.metadata.readonly",
    "drive_write": "https://www.googleapis.com/auth/drive",
}

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Default token expiry buffer (refresh 5 minutes before expiry)
TOKEN_EXPIRY_BUFFER = 300


class GoogleOAuthError(Exception):
    """Base exception for Google OAuth operations."""

    pass


class GoogleAuthError(GoogleOAuthError):
    """Raised when authentication fails."""

    pass


class GoogleTokenError(GoogleOAuthError):
    """Raised when token operations fail."""

    pass


class GoogleServiceError(GoogleOAuthError):
    """Raised when service operations fail."""

    pass


class GoogleRateLimitError(GoogleOAuthError):
    """Raised when rate limit is exceeded."""

    pass


class GoogleOAuthClient:
    """Production-ready Google OAuth client for Gmail, Calendar, and Drive.

    Manages OAuth authentication, token storage and refresh, and provides
    easy access to Google services. Supports both development (localhost callback)
    and production environments with PKCE security.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        callback_url: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        """Initialize the Google OAuth client.

        Args:
            client_id: OAuth client ID (defaults to GOOGLE_OAUTH_CLIENT_ID env var)
            client_secret: OAuth client secret (defaults to GOOGLE_OAUTH_CLIENT_SECRET env var)
            callback_url: OAuth callback URL (defaults to http://localhost:8080/oauth/callback)
            refresh_token: Refresh token for existing credentials (defaults to GOOGLE_OAUTH_REFRESH_TOKEN env var)

        Raises:
            GoogleAuthError: If client credentials are not configured.
        """
        self.client_id = client_id or os.getenv("GOOGLE_OAUTH_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
        self.callback_url = callback_url or os.getenv(
            "GOOGLE_OAUTH_CALLBACK_URL", "http://localhost:8080/oauth/callback"
        )
        self.refresh_token = refresh_token or os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN")

        if not self.client_id or not self.client_secret:
            logger.error(
                "Google OAuth yapılandırması eksik: GOOGLE_OAUTH_CLIENT_ID ve "
                "GOOGLE_OAUTH_CLIENT_SECRET ortam değişkenleri ayarlanması gerekir"
            )
            raise GoogleAuthError(
                "Missing Google OAuth configuration. "
                "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET environment variables."
            )

        # In-memory token cache
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[float] = None
        self._credentials: Optional[Credentials] = None

        # Service instances cache
        self._gmail_service: Optional[Resource] = None
        self._calendar_service: Optional[Resource] = None

        logger.info("Google OAuth istemcisi başlatıldı")

    def _generate_pkce_challenge(self) -> tuple[str, str]:
        """Generate PKCE code challenge and verifier.

        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(
            "utf-8"
        )
        code_verifier = code_verifier.rstrip("=")

        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("utf-8")).digest()
        ).decode("utf-8")
        code_challenge = code_challenge.rstrip("=")

        return code_verifier, code_challenge

    def get_auth_url(
        self, scope_list: list[str], callback_url: Optional[str] = None
    ) -> tuple[str, str]:
        """Generate OAuth consent URL for user authentication.

        Args:
            scope_list: List of scopes to request (e.g., ['gmail_read', 'calendar_read'])
            callback_url: Optional callback URL override

        Returns:
            Tuple of (auth_url, state_parameter)

        Raises:
            GoogleAuthError: If scope_list is invalid or empty.

        Example:
            auth_url, state = client.get_auth_url(['gmail_read', 'calendar_read'])
            print(f"Please visit: {auth_url}")
        """
        if not scope_list:
            logger.error("Kapsam listesi boş")
            raise GoogleAuthError("scope_list cannot be empty")

        # Map scope names to full OAuth scope URLs
        scopes = []
        for scope in scope_list:
            if scope in SCOPE_MAPPINGS:
                scopes.append(SCOPE_MAPPINGS[scope])
            elif scope.startswith("https://"):
                scopes.append(scope)
            else:
                logger.warning(f"Bilinmeyen kapsam: {scope}")
                raise GoogleAuthError(f"Unknown scope: {scope}")

        url_callback = callback_url or self.callback_url

        # Generate PKCE challenge
        code_verifier, code_challenge = self._generate_pkce_challenge()

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Build auth URL
        auth_params = {
            "client_id": self.client_id,
            "redirect_uri": url_callback,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }

        auth_url = f"{GOOGLE_AUTH_URL}?" + "&".join(
            f"{k}={_url_encode(v)}" for k, v in auth_params.items()
        )

        logger.info(f"OAuth URL oluşturuldu, durum: {state[:10]}...")
        return auth_url, state

    def exchange_code_for_tokens(
        self, auth_code: str, callback_url: Optional[str] = None
    ) -> dict[str, Any]:
        """Exchange authorization code for tokens.

        Args:
            auth_code: Authorization code from OAuth callback
            callback_url: Optional callback URL override

        Returns:
            Dictionary with token information including access_token and refresh_token

        Raises:
            GoogleTokenError: If token exchange fails
        """
        if not auth_code:
            logger.error("Yetkilendirme kodu boş")
            raise GoogleTokenError("Authorization code is empty")

        url_callback = callback_url or self.callback_url

        try:
            import requests
        except ImportError:
            logger.error("requests kütüphanesi yüklenmemiş")
            raise GoogleTokenError("requests library is not installed")

        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": url_callback,
        }

        try:
            response = requests.post(GOOGLE_TOKEN_URL, data=token_data, timeout=10)
            response.raise_for_status()
            tokens = response.json()

            # Store refresh token if provided
            if "refresh_token" in tokens:
                self.refresh_token = tokens["refresh_token"]
                os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"] = tokens["refresh_token"]
                logger.info("Yenileme belirteci saklandı")

            # Cache access token
            self._access_token = tokens.get("access_token")
            if "expires_in" in tokens:
                self._token_expiry = time.time() + tokens["expires_in"]

            logger.info("Belirteciler başarıyla alındı")
            return tokens

        except requests.exceptions.Timeout:
            logger.error("Belirteç alışı zaman aşımına uğradı")
            raise GoogleTokenError("Token exchange request timed out")
        except requests.exceptions.RequestException as e:
            logger.error(f"Belirteç alışı başarısız: {e}")
            raise GoogleTokenError(f"Token exchange failed: {e}")
        except ValueError as e:
            logger.error(f"Geçersiz belirteç yanıtı: {e}")
            raise GoogleTokenError(f"Invalid token response: {e}")

    def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token.

        Returns:
            True if refresh was successful, False otherwise

        Raises:
            GoogleTokenError: If refresh token is not available
        """
        if not self.refresh_token:
            logger.error("Yenileme belirteci kullanılamıyor")
            raise GoogleTokenError("Refresh token not available")

        try:
            import requests
        except ImportError:
            logger.error("requests kütüphanesi yüklenmemiş")
            raise GoogleTokenError("requests library is not installed")

        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            response = requests.post(GOOGLE_TOKEN_URL, data=token_data, timeout=10)
            response.raise_for_status()
            tokens = response.json()

            # Update cached access token
            self._access_token = tokens.get("access_token")
            if "expires_in" in tokens:
                self._token_expiry = time.time() + tokens["expires_in"]

            # Invalidate service caches on token refresh
            self._credentials = None
            self._gmail_service = None
            self._calendar_service = None

            logger.info("Erişim belirteci başarıyla yenilendi")
            return True

        except requests.exceptions.Timeout:
            logger.error("Belirteç yenileme zaman aşımına uğradı")
            raise GoogleTokenError("Token refresh timed out")
        except requests.exceptions.RequestException as e:
            logger.error(f"Belirteç yenileme başarısız: {e}")
            raise GoogleTokenError(f"Token refresh failed: {e}")
        except ValueError as e:
            logger.error(f"Geçersiz yenileme yanıtı: {e}")
            raise GoogleTokenError(f"Invalid refresh response: {e}")

    def check_token_expiry(self) -> bool:
        """Check if access token needs refresh.

        Returns:
            True if token is valid and not expiring soon, False if refresh is needed
        """
        if not self._token_expiry:
            return False

        time_until_expiry = self._token_expiry - time.time()
        if time_until_expiry < TOKEN_EXPIRY_BUFFER:
            logger.warning(
                f"Belirteç {time_until_expiry:.0f} saniye içinde sona erecek"
            )
            return False

        return True

    def get_credentials(self) -> Credentials:
        """Get or create Google credentials object.

        Returns:
            Google Credentials object

        Raises:
            GoogleAuthError: If credentials cannot be created
        """
        if self._credentials:
            return self._credentials

        try:
            from google.oauth2.credentials import Credentials
        except ImportError:
            logger.error("google-auth kütüphaneleri yüklenmemiş")
            raise GoogleAuthError("google-auth libraries not installed")

        # Refresh token if needed
        if not self.check_token_expiry() and self.refresh_token:
            try:
                self.refresh_access_token()
            except GoogleTokenError as e:
                logger.error(f"Kimlik bilgileri yenilenemiyor: {e}")
                raise GoogleAuthError(f"Cannot refresh credentials: {e}")

        if not self._access_token:
            logger.error("Erişim belirteci kullanılamıyor")
            raise GoogleAuthError("Access token not available")

        self._credentials = Credentials(
            token=self._access_token,
            refresh_token=self.refresh_token,
            token_uri=GOOGLE_TOKEN_URL,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

        return self._credentials

    def get_user_email(self) -> str:
        """Get the authenticated user's email address.

        Returns:
            Email address of authenticated user

        Raises:
            GoogleServiceError: If user profile cannot be retrieved
        """
        try:
            from googleapiclient.discovery import build
        except ImportError:
            logger.error("google-api-client kütüphanesi yüklenmemiş")
            raise GoogleServiceError("google-api-client not installed")

        try:
            creds = self.get_credentials()
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            profile = service.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress", "unknown")
            logger.info(f"Kullanıcı e-postası alındı: {email}")
            return email
        except Exception as e:
            logger.error(f"Kullanıcı profili alınamadı: {e}")
            raise GoogleServiceError(f"Cannot get user profile: {e}")

    def get_gmail_service(self) -> Resource:
        """Get authenticated Gmail service instance.

        Returns:
            Gmail API service resource

        Raises:
            GoogleServiceError: If service cannot be created
        """
        if self._gmail_service:
            return self._gmail_service

        try:
            from googleapiclient.discovery import build
        except ImportError:
            logger.error("google-api-client kütüphanesi yüklenmemiş")
            raise GoogleServiceError("google-api-client not installed")

        try:
            creds = self.get_credentials()
            self._gmail_service = build(
                "gmail", "v1", credentials=creds, cache_discovery=False
            )
            logger.info("Gmail servisi başlatıldı")
            return self._gmail_service
        except Exception as e:
            logger.error(f"Gmail servisi başlatılamadı: {e}")
            raise GoogleServiceError(f"Cannot create Gmail service: {e}")

    def get_calendar_service(self) -> Resource:
        """Get authenticated Calendar service instance.

        Returns:
            Calendar API service resource

        Raises:
            GoogleServiceError: If service cannot be created
        """
        if self._calendar_service:
            return self._calendar_service

        try:
            from googleapiclient.discovery import build
        except ImportError:
            logger.error("google-api-client kütüphanesi yüklenmemiş")
            raise GoogleServiceError("google-api-client not installed")

        try:
            creds = self.get_credentials()
            self._calendar_service = build(
                "calendar", "v3", credentials=creds, cache_discovery=False
            )
            logger.info("Takvim servisi başlatıldı")
            return self._calendar_service
        except Exception as e:
            logger.error(f"Takvim servisi başlatılamadı: {e}")
            raise GoogleServiceError(f"Cannot create Calendar service: {e}")

    # ==================== Gmail Methods ====================

    def list_messages(
        self, query: str = "", max_results: int = 10, page_token: Optional[str] = None
    ) -> dict[str, Any]:
        """List email messages matching the query.

        Args:
            query: Gmail search query (e.g., 'from:user@example.com', 'label:unread')
            max_results: Maximum number of messages to return (1-500)
            page_token: Page token for pagination

        Returns:
            Dictionary with 'messages' list and optional 'nextPageToken'

        Raises:
            GoogleServiceError: If message list cannot be retrieved
            GoogleRateLimitError: If rate limit is exceeded

        Example:
            result = client.list_messages(query='from:example@gmail.com', max_results=10)
            for msg in result.get('messages', []):
                print(msg['id'])
        """
        max_results = max(1, min(max_results, 500))

        try:
            service = self.get_gmail_service()
            request_params = {
                "userId": "me",
                "q": query,
                "maxResults": max_results,
            }
            if page_token:
                request_params["pageToken"] = page_token

            result = service.users().messages().list(**request_params).execute()
            logger.info(
                f"İletiler listelendi: sorgu='{query}', sonuç={len(result.get('messages', []))}"
            )
            return result
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rateLimitExceeded" in error_msg:
                logger.error(f"Google API oran sınırı aşıldı: {e}")
                raise GoogleRateLimitError(f"Rate limit exceeded: {e}")
            logger.error(f"İletiler listelenmedi: {e}")
            raise GoogleServiceError(f"Cannot list messages: {e}")

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Get full message content by ID.

        Args:
            message_id: Gmail message ID

        Returns:
            Dictionary with message headers, body, and attachments

        Raises:
            GoogleServiceError: If message cannot be retrieved
        """
        try:
            service = self.get_gmail_service()
            message = (
                service.users().messages().get(userId="me", id=message_id).execute()
            )

            # Parse message
            parsed = _parse_message(message)
            logger.info(f"İleti alındı: {message_id}")
            return parsed
        except Exception as e:
            logger.error(f"İleti alınamadı ({message_id}): {e}")
            raise GoogleServiceError(f"Cannot get message {message_id}: {e}")

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        """Get conversation thread by ID.

        Args:
            thread_id: Gmail thread ID

        Returns:
            Dictionary with thread messages

        Raises:
            GoogleServiceError: If thread cannot be retrieved
        """
        try:
            service = self.get_gmail_service()
            thread = service.users().threads().get(userId="me", id=thread_id).execute()

            messages = []
            for msg in thread.get("messages", []):
                parsed = _parse_message(msg)
                messages.append(parsed)

            logger.info(f"Konuşma alındı: {thread_id}, ileti sayısı={len(messages)}")
            return {"thread_id": thread_id, "messages": messages}
        except Exception as e:
            logger.error(f"Konuşma alınamadı ({thread_id}): {e}")
            raise GoogleServiceError(f"Cannot get thread {thread_id}: {e}")

    def send_message(
        self, to: str, subject: str, body: str, body_html: Optional[str] = None
    ) -> str:
        """Send an email message.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            body_html: Optional HTML version of body

        Returns:
            Message ID of sent email

        Raises:
            GoogleServiceError: If message cannot be sent
        """
        try:
            service = self.get_gmail_service()

            if body_html:
                message_obj = MIMEMultipart("alternative")
                message_obj.attach(MIMEText(body, "plain"))
                message_obj.attach(MIMEText(body_html, "html"))
            else:
                message_obj = MIMEText(body)

            message_obj["to"] = to
            message_obj["subject"] = subject

            raw_message = base64.urlsafe_b64encode(message_obj.as_bytes()).decode()

            send_message = {"raw": raw_message}
            result = (
                service.users()
                .messages()
                .send(userId="me", body=send_message)
                .execute()
            )

            logger.info(f"E-posta gönderildi: {to}")
            return result.get("id", "")
        except Exception as e:
            logger.error(f"E-posta gönderilemedi: {e}")
            raise GoogleServiceError(f"Cannot send message: {e}")

    # ==================== Calendar Methods ====================

    def list_events(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 10,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """List calendar events in a time range.

        Args:
            time_min: Minimum time (ISO 8601 format, e.g., '2024-01-01T00:00:00Z')
            time_max: Maximum time (ISO 8601 format)
            max_results: Maximum number of events to return
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Dictionary with 'items' list of events

        Raises:
            GoogleServiceError: If events cannot be retrieved
            GoogleRateLimitError: If rate limit is exceeded

        Example:
            time_min = datetime.now(timezone.utc).isoformat()
            events = client.list_events(time_min=time_min, max_results=10)
        """
        try:
            service = self.get_calendar_service()

            # Default to next 30 days if not specified
            if not time_min:
                time_min = datetime.now(timezone.utc).isoformat()
            if not time_max:
                time_max = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

            request_params = {
                "calendarId": calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max(1, min(max_results, 2500)),
                "singleEvents": True,
                "orderBy": "startTime",
            }

            result = service.events().list(**request_params).execute()
            events = result.get("items", [])
            logger.info(f"Takvim etkinlikleri listelendi: {len(events)} etkinlik")
            return result
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rateLimitExceeded" in error_msg:
                logger.error(f"Google API oran sınırı aşıldı: {e}")
                raise GoogleRateLimitError(f"Rate limit exceeded: {e}")
            logger.error(f"Takvim etkinlikleri listelenmedi: {e}")
            raise GoogleServiceError(f"Cannot list events: {e}")

    def get_event(self, event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
        """Get calendar event by ID.

        Args:
            event_id: Calendar event ID
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Dictionary with event details

        Raises:
            GoogleServiceError: If event cannot be retrieved
        """
        try:
            service = self.get_calendar_service()
            event = (
                service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            logger.info(f"Takvim etkinliği alındı: {event_id}")
            return event
        except Exception as e:
            logger.error(f"Takvim etkinliği alınamadı ({event_id}): {e}")
            raise GoogleServiceError(f"Cannot get event {event_id}: {e}")

    def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        calendar_id: str = "primary",
        attendees: Optional[list[str]] = None,
        location: Optional[str] = None,
    ) -> str:
        """Create a calendar event.

        Args:
            summary: Event title
            start_time: Start time (ISO 8601 format)
            end_time: End time (ISO 8601 format)
            description: Optional event description
            calendar_id: Calendar ID (default: 'primary')
            attendees: Optional list of attendee email addresses
            location: Optional event location

        Returns:
            Event ID of created event

        Raises:
            GoogleServiceError: If event cannot be created

        Example:
            event_id = client.create_event(
                summary='Meeting',
                start_time='2024-12-25T10:00:00+01:00',
                end_time='2024-12-25T11:00:00+01:00',
                description='Important meeting'
            )
        """
        try:
            service = self.get_calendar_service()

            event = {
                "summary": summary,
                "start": {"dateTime": start_time},
                "end": {"dateTime": end_time},
            }

            if description:
                event["description"] = description
            if location:
                event["location"] = location
            if attendees:
                event["attendees"] = [{"email": email} for email in attendees]

            result = (
                service.events().insert(calendarId=calendar_id, body=event).execute()
            )
            logger.info(f"Takvim etkinliği oluşturuldu: {result.get('id')}")
            return result.get("id", "")
        except Exception as e:
            logger.error(f"Takvim etkinliği oluşturulamadı: {e}")
            raise GoogleServiceError(f"Cannot create event: {e}")

    def update_event(
        self,
        event_id: str,
        changes: dict[str, Any],
        calendar_id: str = "primary",
    ) -> str:
        """Update a calendar event.

        Args:
            event_id: Calendar event ID
            changes: Dictionary with fields to update (summary, description, start, end, etc.)
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Event ID of updated event

        Raises:
            GoogleServiceError: If event cannot be updated

        Example:
            client.update_event(
                event_id='event123',
                changes={'summary': 'Updated Title', 'description': 'New description'}
            )
        """
        try:
            service = self.get_calendar_service()

            # Get existing event
            event = (
                service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )

            # Update with changes
            for key, value in changes.items():
                event[key] = value

            result = (
                service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event)
                .execute()
            )
            logger.info(f"Takvim etkinliği güncellendi: {event_id}")
            return result.get("id", "")
        except Exception as e:
            logger.error(f"Takvim etkinliği güncellenemedi ({event_id}): {e}")
            raise GoogleServiceError(f"Cannot update event {event_id}: {e}")

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Delete a calendar event.

        Args:
            event_id: Calendar event ID
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            True if deletion was successful

        Raises:
            GoogleServiceError: If event cannot be deleted
        """
        try:
            service = self.get_calendar_service()
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info(f"Takvim etkinliği silindi: {event_id}")
            return True
        except Exception as e:
            logger.error(f"Takvim etkinliği silinemedi ({event_id}): {e}")
            raise GoogleServiceError(f"Cannot delete event {event_id}: {e}")


# ==================== Helper Functions ====================


def _url_encode(value: str) -> str:
    """URL-encode a string for OAuth parameters."""
    try:
        from urllib.parse import quote
    except ImportError:
        from urllib import quote  # type: ignore

    return quote(value, safe="")


def _parse_message(message: dict[str, Any]) -> dict[str, Any]:
    """Parse a Gmail message to extract headers, body, and attachments.

    Args:
        message: Raw Gmail message object

    Returns:
        Parsed message dictionary with headers, body, and attachments
    """
    msg_id = message.get("id", "")
    headers = message.get("payload", {}).get("headers", [])
    parts = message.get("payload", {}).get("parts", [])

    # Extract common headers
    header_dict = {}
    for header in headers:
        name = header.get("name", "").lower()
        value = header.get("value", "")
        header_dict[name] = value

    # Extract body
    body = ""
    attachments = []

    # Check main payload first
    payload = message.get("payload", {})
    if "body" in payload and payload["body"].get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="ignore"
        )

    # Parse parts for multipart messages
    for part in parts:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            if "body" in part and part["body"].get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="ignore"
                )
        elif mime_type == "text/html":
            if "body" in part and part["body"].get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="ignore"
                )
        elif mime_type.startswith("image/") or mime_type.startswith("application/"):
            if "filename" in part:
                attachments.append(
                    {
                        "filename": part["filename"],
                        "mime_type": mime_type,
                        "size": part.get("body", {}).get("size", 0),
                    }
                )

    return {
        "id": msg_id,
        "from": header_dict.get("from", ""),
        "to": header_dict.get("to", ""),
        "subject": header_dict.get("subject", ""),
        "date": header_dict.get("date", ""),
        "body": body,
        "attachments": attachments,
        "labels": message.get("labelIds", []),
    }
