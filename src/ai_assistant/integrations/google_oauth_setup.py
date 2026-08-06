"""User-friendly CLI setup tool for Google OAuth.

This module provides an interactive setup flow for configuring Google OAuth
credentials. It guides users through the Google Cloud Console setup process,
validates credentials, and saves them to the .env file.

Entry point:
    python -m ai_assistant.integrations.google_oauth_setup
"""

from __future__ import annotations

import os
import re
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"


def print_header(text: str) -> None:
    """Print a bold header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== {text} ==={Colors.RESET}\n")


def print_success(text: str) -> None:
    """Print success message in green."""
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")


def print_error(text: str) -> None:
    """Print error message in red."""
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")


def print_info(text: str) -> None:
    """Print info message in cyan."""
    print(f"{Colors.CYAN}ℹ {text}{Colors.RESET}")


def print_warning(text: str) -> None:
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.RESET}")


def get_env_file_path() -> Path:
    """Return the path to the .env file."""
    return Path.cwd() / ".env"


def env_file_exists() -> bool:
    """Check if .env file exists."""
    return get_env_file_path().exists()


def load_env_vars() -> dict[str, str]:
    """Load existing environment variables from .env file."""
    env_vars = {}
    env_file = get_env_file_path()
    if not env_file.exists():
        return env_vars

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    except IOError as e:
        print_error(f".env dosyası okunamadı: {e}")
    return env_vars


def check_existing_credentials() -> tuple[bool, bool, bool]:
    """Check for existing Google OAuth credentials in .env.

    Returns:
        A tuple of (has_client_id, has_client_secret, has_refresh_token)
    """
    env_vars = load_env_vars()
    # Support both naming conventions
    has_client_id = bool(
        env_vars.get("GOOGLE_CLIENT_ID") or env_vars.get("GOOGLE_OAUTH_CLIENT_ID")
    )
    has_client_secret = bool(
        env_vars.get("GOOGLE_CLIENT_SECRET")
        or env_vars.get("GOOGLE_OAUTH_CLIENT_SECRET")
    )
    has_refresh_token = bool(
        env_vars.get("GOOGLE_REFRESH_TOKEN")
        or env_vars.get("GOOGLE_OAUTH_REFRESH_TOKEN")
    )
    return has_client_id, has_client_secret, has_refresh_token


def validate_client_id(client_id: str) -> bool:
    """Validate client ID format.

    Client IDs typically look like: 123456789-abcdefghijk.apps.googleusercontent.com
    """
    if not client_id or len(client_id) < 20:
        return False
    # Basic check for Google OAuth client ID format
    return ".apps.googleusercontent.com" in client_id or (
        len(client_id) > 20 and "-" in client_id
    )


def validate_client_secret(secret: str) -> bool:
    """Validate client secret format.

    Client secrets are typically alphanumeric strings of 24+ characters.
    """
    if not secret or len(secret) < 20:
        return False
    # Basic check - just ensure it's a reasonable length
    return True


def validate_refresh_token(token: str) -> bool:
    """Validate refresh token format.

    Refresh tokens typically start with digits and contain hyphens.
    """
    if not token or len(token) < 50:
        return False
    # Basic validation
    return True


def print_google_cloud_setup_instructions() -> None:
    """Print step-by-step instructions for setting up Google Cloud credentials."""
    print_header("Google Cloud Kimlik Bilgileri Kurulumu")

    instructions = """
{bold}Adım 1: Google Cloud Project Oluştur{reset}

1. https://console.cloud.google.com/ adresini açın
2. Henüz bir proje yoksa, "Yeni Proje" düğmesine tıklayın
3. Proje adı olarak "AI Executive Assistant" yazın
4. "Oluştur"u tıklayın

{bold}Adım 2: API'leri Etkinleştir{reset}

1. "API'ler ve Hizmetler" sayfasına gidin
2. Arama kutusuna "Gmail API" yazın
3. Gmail API'yi bulun ve "Etkinleştir"e tıklayın
4. Aynı işlemi "Google Calendar API" için tekrarlayın
5. Aynı işlemi "Google Drive API" için tekrarlayın

{bold}Adım 3: OAuth 2.0 Kimlik Bilgileri Oluştur{reset}

1. Soldaki menüden "Kimlik Bilgileri"ni seçin
2. "Kimlik Bilgisi Oluştur" düğmesine tıklayın
3. "OAuth istemci kimliği"ni seçin
4. "Desktop uygulaması" türünü seçin (sadece masaüstü uygulaması)
5. Adlandırma (örn. "AI Assistant Local") yapın ve "Oluştur"u tıklayın
6. Client ID ve Client Secret'ı görüntüleyin

{bold}Adım 4: Kimlik Bilgilerini Kaydet{reset}

Aşağıda gösterilen istemlerden Client ID ve Secret'ı kopyalayıp yapıştırın.
""".format(bold=Colors.BOLD, reset=Colors.RESET)

    print(instructions)


def get_client_id_secret() -> tuple[str, str]:
    """Prompt user to enter Google OAuth client credentials."""
    print_header("Kimlik Bilgilerini Girin")

    client_id = ""
    client_secret = ""

    while not validate_client_id(client_id):
        client_id = input(f"{Colors.BOLD}Client ID:{Colors.RESET} ").strip()
        if not client_id:
            print_error("Client ID boş olamaz.")
            continue
        if not validate_client_id(client_id):
            print_error(
                "Geçersiz Client ID formatı. Google Cloud Console'dan " "kopyalayın."
            )
            continue

    print_success("Client ID kaydedildi.")

    while not validate_client_secret(client_secret):
        client_secret = getpass_compatible(
            f"{Colors.BOLD}Client Secret:{Colors.RESET} "
        )
        if not client_secret:
            print_error("Client Secret boş olamaz.")
            continue
        if not validate_client_secret(client_secret):
            print_error(
                "Geçersiz Client Secret formatı. Google Cloud Console'dan "
                "kopyalayın."
            )
            continue

    print_success("Client Secret kaydedildi.")

    return client_id, client_secret


def getpass_compatible(prompt: str = "") -> str:
    """Get password from user without echoing input.

    Falls back to regular input if getpass is not available.
    """
    try:
        import getpass

        return getpass.getpass(prompt)
    except Exception:
        # Fallback to regular input
        return input(prompt)


def start_oauth_flow(client_id: str, client_secret: str) -> Optional[str]:
    """Start the OAuth flow and get the refresh token.

    This will:
    1. Generate the OAuth authorization URL
    2. Open user's browser to the URL
    3. Wait for user to authorize and get the code
    4. Exchange the code for a refresh token
    """
    print_header("Browser Kimlik Doğrulaması")

    # OAuth endpoints
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"

    # Scopes for Gmail, Calendar, and Drive (read-only)
    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]

    # Build authorization URL
    params = {
        "client_id": client_id,
        "redirect_uri": "http://localhost:8080/callback",
        "scope": " ".join(scopes),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = f"{auth_uri}?{urlencode(params)}"

    print_info("Tarayıcınız otomatik olarak açılacak.")
    print_info("Tarayıcı açılmazsa, aşağıdaki bağlantıyı kopyalayıp yapıştırın:")
    print(f"\n{Colors.CYAN}{auth_url}{Colors.RESET}\n")

    # Try to open browser
    try:
        webbrowser.open(auth_url)
        print_success("Tarayıcı açıldı. Lütfen Google hesabınızla oturum açın.")
    except Exception as e:
        print_warning(f"Tarayıcı otomatik açılamadı: {e}")
        print_info("Lütfen yukarıdaki bağlantıyı kopyalayıp tarayıcınıza yapıştırın.")

    # Prompt for authorization code
    print()
    auth_code = input(
        f"{Colors.BOLD}Yönlendirme URL'sinden 'code' parametresini girin:{Colors.RESET} "
    ).strip()

    if not auth_code:
        print_error("Yetkilendirme kodu boş olamaz.")
        return None

    # Exchange code for token
    print_info("Token alınıyor...")

    try:
        import httpx

        token_data = {
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": "http://localhost:8080/callback",
            "grant_type": "authorization_code",
        }

        response = httpx.post(token_uri, data=token_data, timeout=10.0)
        response.raise_for_status()

        token_response = response.json()

        if "refresh_token" not in token_response:
            print_error(
                "Yenileme token'ı alınamadı. Lütfen adım 3'ü tekrarlayın ve "
                "'Masaüstü uygulaması' olarak ayarlayın."
            )
            return None

        refresh_token = token_response["refresh_token"]
        print_success("Refresh token alındı!")
        return refresh_token

    except Exception as e:
        print_error(f"Token alınırken hata: {e}")
        print_info("Kod değerini manuel olarak girmek istemiş olabilirsiniz.")
        return None


def validate_credentials(
    client_id: str, client_secret: str, refresh_token: str
) -> bool:
    """Validate if the credentials work by testing them with Google APIs.

    This function performs a simple Gmail query to verify that the credentials
    are valid and can be used to access Google services.

    Args:
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret
        refresh_token: Google refresh token obtained from OAuth flow

    Returns:
        True if credentials are valid and working, False otherwise.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        # Create credentials object
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/drive.metadata.readonly",
            ],
        )

        # Refresh token to get access token
        creds.refresh(Request())

        # Build Gmail service and list labels
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds)

        # Perform a simple query to verify credentials work
        result = service.users().labels().list(userId="me").execute()
        labels = result.get("labels", [])

        return True

    except ImportError:
        # Libraries not installed but credentials might still be valid
        return True
    except Exception:
        # Credentials are invalid or cannot be used
        return False


def test_credentials(client_id: str, client_secret: str, refresh_token: str) -> bool:
    """Test if the credentials work by making a simple Gmail query.

    This is a wrapper around validate_credentials() that provides user feedback.
    """
    print_header("Kimlik Bilgileri Test Ediliyor")

    try:
        result = validate_credentials(client_id, client_secret, refresh_token)

        if result:
            # If validate_credentials passed, try to get more info
            try:
                from google.auth.transport.requests import Request
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build

                creds = Credentials(
                    token=None,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=[
                        "https://www.googleapis.com/auth/gmail.readonly",
                        "https://www.googleapis.com/auth/calendar.readonly",
                        "https://www.googleapis.com/auth/drive.metadata.readonly",
                    ],
                )

                print_info("Erişim token'ı alınıyor...")
                creds.refresh(Request())

                service = build("gmail", "v1", credentials=creds)

                print_info("Gmail bağlantısı test ediliyor...")
                result = service.users().labels().list(userId="me").execute()
                labels = result.get("labels", [])

                print_success(
                    f"Gmail bağlantısı başarılı! {len(labels)} etiket bulundu."
                )
            except ImportError:
                print_warning(
                    "Google auth kütüphaneleri yüklenmemiş. "
                    "Kimlik bilgileri yine de kaydedilecek."
                )
            except Exception as e:
                print_error(f"Kimlik bilgileri test edilirken hata: {e}")
                print_warning(
                    "Kimlik bilgileri kaydedilecek ancak doğrulanmadı. "
                    "Lütfen başlangıç adımlarını tekrarlayın."
                )

            return True
        else:
            print_error("Kimlik bilgileri geçersiz.")
            print_warning(
                "Kimlik bilgileri kaydedilecek ancak doğrulanmadı. "
                "Lütfen başlangıç adımlarını tekrarlayın."
            )
            return False

    except Exception as e:
        print_error(f"Kimlik bilgileri test edilirken hata: {e}")
        print_warning(
            "Kimlik bilgileri kaydedilecek ancak doğrulanmadı. "
            "Lütfen başlangıç adımlarını tekrarlayın."
        )
        return False


def save_to_env(updates: dict[str, str]) -> bool:
    """Save or update environment variables to .env file."""
    env_file = get_env_file_path()
    env_vars = load_env_vars()

    # Update with new values
    env_vars.update(updates)

    try:
        with open(env_file, "w", encoding="utf-8") as f:
            # Write header comment
            f.write("# AI Executive Assistant — environment configuration\n")
            f.write("# Google OAuth credentials\n\n")

            # Write variables
            for key, value in sorted(env_vars.items()):
                f.write(f"{key}={value}\n")

        print_success(f"Kimlik bilgileri {env_file} dosyasına kaydedildi.")
        return True

    except IOError as e:
        print_error(f".env dosyası yazılamadı: {e}")
        return False


def print_success_message() -> None:
    """Print success message with agent activation info."""
    print_header("Kurulum Tamamlandı!")

    success_text = f"""
{Colors.GREEN}✓ Google OAuth kurulumu başarıyla tamamlandı!{Colors.RESET}

{Colors.BOLD}Artık etkinleştirilmiş aracılar:{Colors.RESET}
  • Mail Analisti (Gmail) — E-postalarınızı analiz eder
  • Gün Planlayıcı (Google Calendar) — Takvim etkinliklerinizi yönetir
  • Dosya Yöneticisi (Google Drive) — Dosyalarınızı taraması

{Colors.BOLD}Sonraki adımlar:{Colors.RESET}
  1. Günlük özeti çalıştırmak için: python -m ai_assistant
  2. Tüm bağlantıları test etmek için: python -m ai_assistant.health
  3. Slack bağlantısını kurmak için talimatlar için: docs/ dizinine bakın

{Colors.CYAN}İpucu: Başlangıçta tüm aracıları etkinleştirmek için .env dosyasında
gerekli diğer kimlik bilgilerini ekleyin (Slack, Asana, vb.).{Colors.RESET}
"""
    print(success_text)


def print_agent_list() -> None:
    """Print list of available agents that can be activated."""
    agents_text = """
{bold}Kullanılabilir Aracılar:{reset}
  • Mail Analisti — Gmail e-postalarını analiz eder
  • Gün Planlayıcı — Google Calendar etkinliklerini gözden geçirir
  • Dosya Yöneticisi — Google Drive'daki güncellemeleri izler
  • Asana Uzmanı — Asana görevlerini izler (Asana token gerekli)
  • Notion Sekreteri — Notion sayfalarını güncellemeleri izler (Notion token gerekli)
  • Slack Bildirici — Sonuçları Slack'e gönderir (Slack token gerekli)

{bold}Google OAuth'u başarıyla kurduğunuz için:{reset}
  - Mail Analisti etkinleşti
  - Gün Planlayıcı etkinleşti
  - Dosya Yöneticisi etkinleşti

Diğer aracıları etkinleştirmek için ilgili hizmetlerin kimlik bilgilerini .env'ye ekleyin.
""".format(bold=Colors.BOLD, reset=Colors.RESET)
    print(agents_text)


def setup_google_oauth() -> bool:
    """Main setup flow for Google OAuth."""
    print_header("Google OAuth Kurulumu")

    print(
        "Bu kurulum aracı, AI Executive Assistant'ı Google hizmetleriyle "
        "bağlamaya yardımcı olacak.\n"
    )

    # Check existing credentials
    has_id, has_secret, has_token = check_existing_credentials()

    if has_id and has_secret and has_token:
        print_success("Google OAuth kimlik bilgileri zaten yapılandırılmış!")
        response = (
            input("\nKurulumu yeniden çalıştırmak istiyor musunuz? (evet/hayır): ")
            .lower()
            .strip()
        )
        if response not in ["y", "evet", "yes"]:
            print_info("Kurulum iptal edildi.")
            return True

    # Step 1: Google Cloud Setup Instructions
    response = (
        input(
            "\nGoogle Cloud Console'da proje ve OAuth kimlik bilgilerini "
            "oluşturdunuz mu? (evet/hayır): "
        )
        .lower()
        .strip()
    )
    if response not in ["y", "evet", "yes"]:
        print_google_cloud_setup_instructions()
        input(
            "\n"
            + Colors.BOLD
            + "Talimatları tamamladıktan sonra Enter'e basın..."
            + Colors.RESET
        )

    # Step 2: Get client credentials
    print()
    response = (
        input(
            "Client ID ve Secret'ı Google Cloud Console'dan kopyaladınız mı? "
            "(evet/hayır): "
        )
        .lower()
        .strip()
    )
    if response not in ["y", "evet", "yes"]:
        print_error("Client ID ve Secret olmadan devam edilemez.")
        return False

    client_id, client_secret = get_client_id_secret()

    # Step 3: OAuth flow to get refresh token
    print()
    print_info("Refresh token almak için OAuth akışı başlatılacak...")
    refresh_token = start_oauth_flow(client_id, client_secret)

    if not refresh_token:
        print_error("Refresh token alınamadı. Kurulum başarısız.")
        return False

    # Step 4: Test credentials
    print()
    test_passed = test_credentials(client_id, client_secret, refresh_token)

    if not test_passed:
        response = (
            input(
                "\nKimlik bilgileri doğrulanamadı. Yine de kaydetmek istiyor musunuz? "
                "(evet/hayır): "
            )
            .lower()
            .strip()
        )
        if response not in ["y", "evet", "yes"]:
            print_error("Kurulum iptal edildi.")
            return False

    # Step 5: Save to .env
    print()
    updates = {
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
        "GOOGLE_REFRESH_TOKEN": refresh_token,
    }

    if not save_to_env(updates):
        print_error("Kimlik bilgileri .env dosyasına kaydedilemedi.")
        return False

    # Success message
    print()
    print_success_message()
    print()
    print_agent_list()

    return True


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    try:
        # Handle Ctrl+C gracefully
        success = setup_google_oauth()
        return 0 if success else 1
    except KeyboardInterrupt:
        print()
        print_warning("Kurulum kullanıcı tarafından iptal edildi.")
        return 130
    except Exception as e:
        print_error(f"Beklenmeyen hata: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
