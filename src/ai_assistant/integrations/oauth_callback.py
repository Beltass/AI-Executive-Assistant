"""OAuth 2.0 callback handler for Google login flow.

Provides a simple HTTP server for handling OAuth callbacks from Google's
authorization endpoint. Implements state validation, PKCE support, token
exchange, and secure refresh token storage.

Usage:
    handler = OAuthCallbackHandler()
    refresh_token = handler.start_and_wait()  # Blocks until callback received
    # refresh_token is ready to save to .env or secure storage
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.error import URLError

logger = logging.getLogger(__name__)


class OAuthCallbackHandler:
    """Simple HTTP server for OAuth callback handling.

    Implements the OAuth 2.0 authorization code flow with PKCE support.
    Handles callback from Google, exchanges code for tokens, and stores
    the refresh token securely.

    Attributes:
        port: The local port to listen on (default: 8080).
        timeout_seconds: How long to wait for callback before timing out
            (default: 600 seconds = 10 minutes).
        state: PKCE state parameter for security.
        code_verifier: PKCE code verifier.
        code_challenge: PKCE code challenge.
        received_data: Dict containing code, state and tokens after callback.
    """

    def __init__(
        self,
        port: int = 8080,
        timeout_seconds: int = 600,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_uri: str = "https://oauth2.googleapis.com/token",
    ):
        """Initialize the OAuth callback handler.

        Args:
            port: Local port to listen on (default: 8080).
            timeout_seconds: Timeout for waiting on callback (default: 600).
            client_id: Google OAuth client ID. If not provided, reads from
                GOOGLE_CLIENT_ID environment variable.
            client_secret: Google OAuth client secret. If not provided, reads from
                GOOGLE_CLIENT_SECRET environment variable.
            token_uri: Token exchange endpoint (default: Google's token URI).
        """
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.token_uri = token_uri

        self.state: Optional[str] = None
        self.code_verifier: Optional[str] = None
        self.code_challenge: Optional[str] = None
        self.received_data: dict = {}
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self._callback_event = threading.Event()
        self._server_ready_event = threading.Event()

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge.

        Returns:
            Tuple of (code_verifier, code_challenge).
        """
        # Generate a random 32-byte value, encode as URL-safe base64
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(
            "utf-8"
        )
        # Remove padding
        code_verifier = code_verifier.rstrip("=")

        # Generate challenge: SHA256(verifier) encoded as URL-safe base64
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("utf-8")).digest()
        ).decode("utf-8")
        challenge = challenge.rstrip("=")

        return code_verifier, challenge

    def generate_auth_params(self) -> dict:
        """Generate OAuth 2.0 authorization parameters.

        Generates state and PKCE parameters for the authorization request.
        These should be passed to Google's authorization endpoint.

        Returns:
            Dict with keys: state, code_challenge, code_challenge_method
        """
        self.state = secrets.token_urlsafe(32)
        self.code_verifier, self.code_challenge = self._generate_pkce_pair()

        return {
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
        }

    def get_authorization_url(
        self,
        client_id: Optional[str] = None,
        redirect_uri: str = "http://localhost:8080/oauth/callback",
        scopes: Optional[list[str]] = None,
    ) -> str:
        """Build the Google authorization URL.

        Args:
            client_id: Google OAuth client ID. Uses self.client_id if not
                provided.
            redirect_uri: Where Google should redirect after authorization.
            scopes: List of OAuth scopes to request.

        Returns:
            Full authorization URL to visit in a browser.

        Raises:
            ValueError: If client_id is not available.
        """
        client_id = client_id or self.client_id
        if not client_id:
            raise ValueError(
                "client_id must be provided or set as GOOGLE_CLIENT_ID "
                "environment variable"
            )

        if scopes is None:
            scopes = [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/drive.metadata.readonly",
            ]

        # Generate auth parameters if not already done
        if not self.state:
            self.generate_auth_params()

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }

        return (
            "https://accounts.google.com/o/oauth2/auth?"
            + urllib.parse.urlencode(params)
        )

    def _build_callback_handler(self):
        """Build the request handler class for the HTTP server.

        Returns:
            A BaseHTTPRequestHandler subclass that processes OAuth callbacks.
        """
        oauth_handler = self

        class CallbackRequestHandler(BaseHTTPRequestHandler):
            """Handles the OAuth callback request from Google."""

            def do_get(self):
                """Handle GET request from OAuth callback."""
                # Parse query parameters
                parsed_url = urllib.parse.urlparse(self.path)
                query_params = urllib.parse.parse_qs(parsed_url.query)

                # Extract code and state
                code = query_params.get("code", [None])[0]
                state = query_params.get("state", [None])[0]
                error = query_params.get("error", [None])[0]

                # Handle authorization errors from Google
                if error:
                    error_description = query_params.get(
                        "error_description", ["Unknown error"]
                    )[0]
                    oauth_handler.received_data = {
                        "error": error,
                        "error_description": error_description,
                    }
                    self._send_error_page(error, error_description)
                    oauth_handler._callback_event.set()
                    return

                # Validate state parameter
                if state != oauth_handler.state:
                    oauth_handler.received_data = {
                        "error": "invalid_state",
                        "error_description": "State parameter does not match",
                    }
                    self._send_error_page(
                        "invalid_state", "State parameter does not match"
                    )
                    oauth_handler._callback_event.set()
                    return

                # Validate authorization code
                if not code:
                    oauth_handler.received_data = {
                        "error": "missing_code",
                        "error_description": "Authorization code not provided",
                    }
                    self._send_error_page(
                        "missing_code", "Authorization code not provided"
                    )
                    oauth_handler._callback_event.set()
                    return

                # Exchange code for tokens
                try:
                    token_data = oauth_handler._exchange_code_for_tokens(code)
                    oauth_handler.received_data = token_data
                    self._send_success_page()
                except Exception as exc:  # noqa: BLE001
                    error_msg = str(exc)
                    oauth_handler.received_data = {
                        "error": "token_exchange_failed",
                        "error_description": error_msg,
                    }
                    self._send_error_page("token_exchange_failed", error_msg)

                oauth_handler._callback_event.set()

            def _send_success_page(self):
                """Send success HTML response to the browser."""
                html = """<html>
<head>
    <meta charset="UTF-8">
    <title>Google OAuth - Başarılı</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 8px;
            padding: 40px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
            max-width: 400px;
        }
        h1 {
            color: #4CAF50;
            margin: 0 0 20px 0;
            font-size: 28px;
        }
        .checkmark {
            font-size: 48px;
            margin: 0 0 20px 0;
        }
        p {
            color: #333;
            font-size: 16px;
            line-height: 1.6;
            margin: 10px 0;
        }
        .info {
            background: #f5f5f5;
            border-left: 4px solid #4CAF50;
            padding: 15px;
            margin: 20px 0;
            text-align: left;
            border-radius: 4px;
        }
        .info strong {
            color: #333;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="checkmark">✓</div>
        <h1>Google OAuth Başarılı!</h1>
        <p>Kimlik doğrulama tamamlandı.</p>
        <p>Yenileme jetonu güvenli şekilde kaydedildi.</p>
        <div class="info">
            <strong>Sonraki adımlar:</strong>
            <p>Bu pencereyi güvenle kapatabilirsiniz. Asistan artık
            Google hizmetlerine erişebilir.</p>
        </div>
    </div>
</body>
</html>"""
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))

            def _send_error_page(self, error_code: str, error_msg: str):
                """Send error HTML response to the browser.

                Args:
                    error_code: Short error identifier.
                    error_msg: Human-readable error message.
                """
                error_map = {
                    "access_denied": "Erişim Reddedildi",
                    "invalid_state": "Güvenlik Doğrulaması Başarısız",
                    "missing_code": "Yetkilendirme Kodu Eksik",
                    "token_exchange_failed": "Token Değişimi Başarısız",
                }
                error_title = error_map.get(error_code, "Hata Oluştu")

                html = f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Google OAuth - Hata</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            min-height: 100vh;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: white;
            border-radius: 8px;
            padding: 40px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
            max-width: 400px;
        }}
        h1 {{
            color: #f44336;
            margin: 0 0 20px 0;
            font-size: 28px;
        }}
        .error-icon {{
            font-size: 48px;
            margin: 0 0 20px 0;
        }}
        p {{
            color: #333;
            font-size: 16px;
            line-height: 1.6;
            margin: 10px 0;
        }}
        .error-details {{
            background: #ffebee;
            border-left: 4px solid #f44336;
            padding: 15px;
            margin: 20px 0;
            text-align: left;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            color: #c62828;
            word-break: break-all;
        }}
        .info {{
            background: #f5f5f5;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin: 20px 0;
            text-align: left;
            border-radius: 4px;
        }}
        .info strong {{
            color: #333;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-icon">✕</div>
        <h1>{error_title}</h1>
        <p>OAuth kimlik doğrulaması başarısız oldu.</p>
        <div class="error-details">
            <strong>Hata Kodu:</strong> {error_code}<br>
            <strong>Detaylar:</strong> {error_msg}
        </div>
        <div class="info">
            <strong>Sonraki adımlar:</strong>
            <p>Lütfen terminale dönüp OAuth akışını yeniden başlatın veya
            hata ayrıntılarını kontrol edin.</p>
        </div>
    </div>
</body>
</html>"""
                self.send_response(400)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))

            def log_message(self, format, *args):  # noqa: ARG002, ANN001
                """Suppress default HTTP server logging."""
                # Only log errors, not every GET request
                pass

        return CallbackRequestHandler

    def _exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code from Google.

        Returns:
            Dictionary with access_token, refresh_token, and other token data.

        Raises:
            Exception: If token exchange fails.
        """
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "client_id and client_secret must be configured for token exchange"
            )

        if not self.code_verifier:
            raise ValueError("PKCE code_verifier not available")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": "http://localhost:8080/oauth/callback",
            "code_verifier": self.code_verifier,
        }

        request = urllib.request.Request(
            self.token_uri,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            method="POST",
        )
        request.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_data = json.loads(response.read().decode("utf-8"))
                return response_data
        except URLError as exc:
            raise Exception(
                f"Token exchange failed: {exc.reason if hasattr(exc, 'reason') else exc}"
            ) from exc

    def start_server(self) -> str:
        """Start the local HTTP server for OAuth callbacks.

        Returns:
            The authorization URL to visit in the browser.

        Raises:
            RuntimeError: If the server cannot start.
        """
        try:
            CallbackHandler = self._build_callback_handler()
            self.server = HTTPServer(("localhost", self.port), CallbackHandler)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to start OAuth callback server on port {self.port}: {exc}"
            ) from exc

        # Start server in a background thread
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        # Wait for server to be ready
        time.sleep(0.5)

        auth_url = self.get_authorization_url()
        logger.info("OAuth callback server started on http://localhost:%d", self.port)
        logger.info("Authorization URL: %s", auth_url)

        return auth_url

    def _run_server(self):
        """Run the HTTP server until shutdown is requested."""
        if self.server:
            self.server.timeout = 1  # Allow checking for shutdown every second
            while True:
                self.server.handle_request()
                # Check if we should shutdown
                if self._callback_event.is_set():
                    break

    def start_and_wait(self, timeout: Optional[int] = None) -> Optional[str]:
        """Start server, wait for callback, and return refresh token.

        This is the main entry point: it blocks until the OAuth callback
        is received, then returns the refresh token (or None on error).

        Args:
            timeout: Override the default timeout (in seconds).

        Returns:
            The refresh token if successful, None if timeout or error.

        Raises:
            RuntimeError: If the server cannot start.
        """
        timeout = timeout or self.timeout_seconds

        # Start the server
        auth_url = self.start_server()

        logger.info(
            "Waiting for OAuth callback (timeout: %d seconds)...", timeout
        )

        # Wait for callback with timeout
        callback_received = self._callback_event.wait(timeout=timeout)

        # Shutdown the server
        self.shutdown()

        if not callback_received:
            logger.error("OAuth callback timeout after %d seconds", timeout)
            return None

        # Check for errors in the callback
        if "error" in self.received_data:
            error = self.received_data["error"]
            error_desc = self.received_data.get("error_description", "Unknown error")
            logger.error("OAuth callback error: %s - %s", error, error_desc)
            return None

        # Extract refresh token
        refresh_token = self.received_data.get("refresh_token")
        if refresh_token:
            logger.info("Successfully obtained refresh token")
            return refresh_token

        logger.error("No refresh token in token response")
        return None

    def shutdown(self):
        """Shutdown the HTTP server gracefully."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("OAuth callback server shut down")

    def save_refresh_token_to_env(
        self, refresh_token: str, env_file: str = ".env"
    ) -> bool:
        """Save refresh token to .env file.

        Creates or updates the .env file with the refresh token.
        Other environment variables are preserved.

        Args:
            refresh_token: The refresh token to save.
            env_file: Path to the .env file (default: ".env").

        Returns:
            True if successful, False otherwise.
        """
        env_vars = {}

        # Read existing .env file if it exists
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if "=" in line:
                                key, value = line.split("=", 1)
                                env_vars[key.strip()] = value.strip()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to read %s: %s", env_file, exc)
                return False

        # Update or add refresh token
        env_vars["GOOGLE_OAUTH_REFRESH_TOKEN"] = refresh_token

        # Write updated .env file
        try:
            with open(env_file, "w", encoding="utf-8") as f:
                for key, value in sorted(env_vars.items()):
                    f.write(f"{key}={value}\n")
            logger.info("Refresh token saved to %s", env_file)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write to %s: %s", env_file, exc)
            return False


def main():
    """CLI entry point for OAuth login flow.

    Usage:
        python -m ai_assistant.integrations.oauth_callback
    """
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print(
            "Error: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment "
            "variables must be set",
            file=sys.stderr,
        )
        return 1

    handler = OAuthCallbackHandler()

    print("\n" + "=" * 70)
    print("Google OAuth 2.0 Authorization Flow")
    print("=" * 70)

    auth_url = handler.start_server()
    print(f"\nOpening browser to authorization URL...")
    print(f"\nIf your browser doesn't open, visit this URL:\n{auth_url}\n")

    # Try to open browser
    try:
        import webbrowser

        webbrowser.open(auth_url)
    except Exception as exc:  # noqa: BLE001
        print(f"Note: Could not open browser: {exc}")
        print(f"Please visit the URL above manually.")

    print("Waiting for authorization callback (timeout: 10 minutes)...")

    refresh_token = handler.start_and_wait()

    if not refresh_token:
        print("\nError: Failed to obtain refresh token", file=sys.stderr)
        return 1

    # Save to .env
    success = handler.save_refresh_token_to_env(refresh_token)
    if not success:
        print("\nWarning: Could not save to .env file", file=sys.stderr)
        print(f"Please add this to your .env file:")
        print(f"GOOGLE_OAUTH_REFRESH_TOKEN={refresh_token}")
        return 1

    print("\n" + "=" * 70)
    print("Success!")
    print("=" * 70)
    print("Refresh token has been saved to .env")
    print("\nYou can now use Google integrations (Gmail, Calendar, Drive)")
    print("without further authentication.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
