"""Slack Doğrudan Mesajlaşma — danışmanların DM yoluyla erişilebilmesi.

Kullanıcı bota doğrudan bir mesaj gönderirse, bot:
1. Dialog durumunu kontrol eder (aktif dialog var mı?)
2. İçeriği analiz eder (niyeti algılar)
3. Uygun danışmana yönlendirir
4. Danışmanın cevabını geri gönderir
5. Mobil bildirim gönderir

Dialog Sistemi:
  - AdvisorDialog: Veri Analisti, Sosyal Medya Koçu, Kişisel Asistan
  - Multi-turn konuşma: Geçmiş bağlamı hatırla
  - State persistence: Dialog durumunu diskte sakla

Örnek:
  Kullanıcı: "Veri analizi yap"
  Bot: Menüyü göster → dialog oluştur → input bekle → analiz → rapor

Configuration:
    SLACK_NOTIFICATION_METHOD  "push" (varsayılan), "email", veya "sms"
    DIRECT_MESSAGE_TIMEOUT     Timeout süresi saniyecinsinden (varsayılan: 30)
    ADVISOR_DIALOG_ENABLED     Dialog sistemi aktif mi? (varsayılan: true)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Yapılandırma
NOTIFICATION_METHOD_ENV = "SLACK_NOTIFICATION_METHOD"
NOTIFICATION_PUSH = "push"
NOTIFICATION_EMAIL = "email"
NOTIFICATION_SMS = "sms"

TIMEOUT_ENV = "DIRECT_MESSAGE_TIMEOUT"
DEFAULT_TIMEOUT = 30

ADVISOR_DIALOG_ENABLED_ENV = "ADVISOR_DIALOG_ENABLED"
DEFAULT_ADVISOR_DIALOG_ENABLED = True


@dataclass
class DirectMessage:
    """Doğrudan mesaj yapısı."""
    user_id: str
    text: str
    timestamp: str
    channel_id: str  # DM channel ID
    thread_ts: Optional[str] = None


@dataclass
class DirectMessageResponse:
    """DM yanıt yapısı."""
    advisor_key: str
    response_text: str
    generated_at: str
    sources: List[str] = None


class DirectMessenger:
    """Slack DM yoluyla danışmanlara erişim — Dialog sistemi ile."""

    # Basit anahtar kelime -> danışman eşlemesi
    ADVISOR_KEYWORDS = {
        "sosyal": "social_media_coach",
        "instagram": "social_media_coach",
        "twitter": "social_media_coach",
        "tiktok": "social_media_coach",
        "profil": "social_media_coach",
        "linkedin": "linkedin_coach",
        "veri": "data_analyst",
        "analiz": "data_analyst",
        "verileri": "data_analyst",
        "hedef": "personal_assistant",
        "görev": "personal_assistant",
        "takvim": "personal_assistant",
        "toplantı": "personal_assistant",
        "gün": "personal_assistant",
        "özet": "personal_assistant",
    }

    def __init__(self):
        """DirectMessenger'ı başlat."""
        self.timeout = self._get_timeout()
        self.notification_method = self._get_notification_method()
        self.dialog_enabled = self._is_dialog_enabled()
        self.dialog_flow = None
        if self.dialog_enabled:
            from .advisor_dialog import AdvisorDialogFlow
            self.dialog_flow = AdvisorDialogFlow()

    def _get_timeout(self) -> int:
        """Yapılandırılan timeout'u al."""
        import os
        raw = (os.getenv(TIMEOUT_ENV) or "").strip()
        try:
            return int(raw)
        except ValueError:
            return DEFAULT_TIMEOUT

    def _get_notification_method(self) -> str:
        """Bildirim yöntemini al."""
        import os
        method = (os.getenv(NOTIFICATION_METHOD_ENV) or "").strip().lower()
        if method in [NOTIFICATION_PUSH, NOTIFICATION_EMAIL, NOTIFICATION_SMS]:
            return method
        return NOTIFICATION_PUSH

    def _is_dialog_enabled(self) -> bool:
        """Dialog sistemi etkin mi?"""
        import os
        value = (os.getenv(ADVISOR_DIALOG_ENABLED_ENV) or "").strip().lower()
        if value in ["false", "no", "0"]:
            return False
        return DEFAULT_ADVISOR_DIALOG_ENABLED

    async def route_to_advisor(self, message: DirectMessage) -> Optional[DirectMessageResponse]:
        """Bir DM'yi uygun danışmana yönlendir.

        Args:
            message: Doğrudan mesaj

        Returns:
            Danışmanın yanıtı veya None
        """
        try:
            # Dialog sistemi etkinse ve aktif dialog varsa, onu kullan
            if self.dialog_enabled and self.dialog_flow:
                return await self._route_with_dialog(message)

            # Fallback: eski sistem
            advisor_key = self._detect_advisor(message.text)
            if not advisor_key:
                return await self._unknown_intent_response()

            logger.info(f"DM yönlendirildi: {advisor_key}")

            # Danışmanı çağır ve cevap al
            response = await self._call_advisor(advisor_key, message)
            return response

        except Exception as exc:
            logger.exception("DM yönlendirme başarısız")
            return None

    async def _route_with_dialog(self, message: DirectMessage) -> Optional[DirectMessageResponse]:
        """Dialog sistemi ile yönlendir.

        Args:
            message: Doğrudan mesaj

        Returns:
            Danışmanın yanıtı
        """
        try:
            user_id = message.user_id
            text = message.text.strip()

            # Menü seçimi kontrolü: danışman seçilmedi mi?
            if self._is_menu_selection(text):
                advisor_key, response_dict = self.dialog_flow.handle_advisor_selection(user_id, text)
                if advisor_key:
                    return DirectMessageResponse(
                        advisor_key=advisor_key,
                        response_text=self._format_blocks_as_text(response_dict),
                        generated_at=datetime.now().isoformat(),
                        sources=[]
                    )
                else:
                    return DirectMessageResponse(
                        advisor_key="system",
                        response_text=response_dict.get("text", "Seçim anlaşılamadı."),
                        generated_at=datetime.now().isoformat(),
                        sources=[]
                    )

            # Hangi advisor'a ait dialog'u kontrol et
            advisor_key = self._detect_advisor(text)
            if not advisor_key:
                # Menü göster
                response_dict = self.dialog_flow.show_advisor_menu(user_id)
                return DirectMessageResponse(
                    advisor_key="system",
                    response_text=self._format_blocks_as_text(response_dict),
                    generated_at=datetime.now().isoformat(),
                    sources=[]
                )

            # Advisora yönlendir
            response_dict = self.dialog_flow.handle_advisor_input(advisor_key, user_id, text)
            return DirectMessageResponse(
                advisor_key=advisor_key,
                response_text=response_dict.get("text", ""),
                generated_at=datetime.now().isoformat(),
                sources=[]
            )

        except Exception as exc:
            logger.exception("Dialog yönlendirme başarısız")
            return None

    @staticmethod
    def _is_menu_selection(text: str) -> bool:
        """Menü seçimi mi (1, 2, 3)?"""
        text = text.strip().lower()
        return text in ["1", "2", "3", "veri", "sosyal", "asistan"]

    @staticmethod
    def _format_blocks_as_text(response_dict: Dict[str, Any]) -> str:
        """Block Kit formatını metne çevir."""
        text = response_dict.get("text", "")
        if response_dict.get("blocks"):
            # Blokları ekle
            for block in response_dict["blocks"]:
                if block.get("type") == "section" and block.get("text"):
                    text += f"\n{block['text'].get('text', '')}"
        return text

    def _detect_advisor(self, text: str) -> Optional[str]:
        """Mesaj içeriğinden danışman türünü algıla."""
        text_lower = text.lower()

        # Anahtar kelime eşlemesi
        for keyword, advisor in self.ADVISOR_KEYWORDS.items():
            if keyword in text_lower:
                return advisor

        # Standart danışman (bulunamadığında)
        return "personal_assistant"

    async def _unknown_intent_response(self) -> DirectMessageResponse:
        """Niyeti anlaşılamadığında cevap."""
        return DirectMessageResponse(
            advisor_key="personal_assistant",
            response_text=(
                "Mesajını anlamış olmayabilirim 🤔\n\n"
                "Şunlardan birini dene:\n"
                "• 'Instagram profilimi analiz et' → Sosyal Medya Koçu\n"
                "• 'Veri analizi yap' → Veri Analisti\n"
                "• 'Bugünün görevleri' → Kişisel Asistan\n"
                "• 'LinkedIn'i optimize et' → LinkedIn Koçu\n\n"
                "Veya tam sorunun yazabilirsin!"
            ),
            generated_at=datetime.now().isoformat(),
            sources=[]
        )

    async def _call_advisor(
        self,
        advisor_key: str,
        message: DirectMessage
    ) -> Optional[DirectMessageResponse]:
        """Bir danışmanı çağır ve cevap al."""
        try:
            # Danışmanlar modülünü dinamik olarak yükle
            from ..advisors import all_advisors

            # Danışmanı bul
            advisors_dict = {a.key: a for a in all_advisors()}
            advisor = advisors_dict.get(advisor_key)

            if not advisor:
                logger.warning(f"Danışman bulunamadı: {advisor_key}")
                return None

            # Danışmanı çağır (kişilleştirilmiş istem)
            # Bunun yerine basit bir cevap döndür
            response_text = f"📌 {advisor.title} analiz ediyor...\n\n{message.text}"

            return DirectMessageResponse(
                advisor_key=advisor_key,
                response_text=response_text,
                generated_at=datetime.now().isoformat(),
                sources=[advisor.key]
            )

        except Exception as exc:
            logger.exception(f"Danışman çağrısı başarısız: {advisor_key}")
            return None

    async def send_direct_message(
        self,
        user_id: str,
        advisor_key: str,
        response: DirectMessageResponse
    ) -> bool:
        """Danışman yanıtını kullanıcıya DM olarak gönder.

        Args:
            user_id: Slack kullanıcı ID'si
            advisor_key: Danışman anahtarı
            response: Gönderilecek yanıt

        Returns:
            Başarılı mı?
        """
        try:
            from .slack_api import SlackClient, bot_token

            token = bot_token()
            if not token:
                logger.warning("Slack token yapılandırılmadı")
                return False

            client = SlackClient(token)

            # DM kanalını aç (veya var olanı al)
            dm_channel = await client.open_dm(user_id)
            if not dm_channel:
                logger.error(f"DM kanalı açılamadı: {user_id}")
                return False

            # Yanıtı gönder
            text = f"*{advisor_key}*\n\n{response.response_text}"
            success = await client.post_message(dm_channel, text)

            if success:
                logger.info(f"DM gönderildi: {user_id} -> {advisor_key}")

            return success

        except Exception as exc:
            logger.exception("DM gönderme başarısız")
            return False

    async def send_notification(
        self,
        user_id: str,
        notification: str,
        urgent: bool = False
    ) -> bool:
        """Bildirim gönder (push/email/SMS).

        Args:
            user_id: Slack kullanıcı ID'si
            notification: Bildirim metni
            urgent: Acil mi?

        Returns:
            Başarılı mı?
        """
        try:
            if self.notification_method == NOTIFICATION_PUSH:
                return await self._send_push_notification(user_id, notification, urgent)
            elif self.notification_method == NOTIFICATION_EMAIL:
                return await self._send_email_notification(user_id, notification, urgent)
            elif self.notification_method == NOTIFICATION_SMS:
                return await self._send_sms_notification(user_id, notification, urgent)

            return False

        except Exception as exc:
            logger.exception("Bildirim gönderme başarısız")
            return False

    async def _send_push_notification(
        self,
        user_id: str,
        text: str,
        urgent: bool
    ) -> bool:
        """Slack push bildirimi gönder."""
        try:
            from .slack_api import SlackClient, bot_token

            token = bot_token()
            if not token:
                return False

            client = SlackClient(token)
            dm_channel = await client.open_dm(user_id)
            if not dm_channel:
                return False

            # Acil bildirim emoji'si
            prefix = "🚨" if urgent else "📬"
            full_text = f"{prefix} {text}"

            return await client.post_message(dm_channel, full_text)

        except Exception as exc:
            logger.exception("Push bildirimi başarısız")
            return False

    async def _send_email_notification(
        self,
        user_id: str,
        text: str,
        urgent: bool
    ) -> bool:
        """E-posta bildirimi gönder."""
        # TODO: E-posta entegrasyonu (Gmail API)
        logger.info(f"E-posta bildirimi (mock): {user_id} -> {text[:50]}")
        return True

    async def _send_sms_notification(
        self,
        user_id: str,
        text: str,
        urgent: bool
    ) -> bool:
        """SMS bildirimi gönder."""
        # TODO: SMS entegrasyonu (Twilio vb.)
        logger.info(f"SMS bildirimi (mock): {user_id} -> {text[:50]}")
        return True

    async def fallback_if_offline(
        self,
        user_id: str,
        message: str,
        method_preference: Optional[str] = None
    ) -> bool:
        """Kullanıcı çevrimdışısysa fallback yöntemi kullan.

        Args:
            user_id: Slack kullanıcı ID'si
            message: Mesaj
            method_preference: Tercih edilen yöntem

        Returns:
            Başarılı mı?
        """
        try:
            # Fallback sırası: push -> email -> sms
            methods = [NOTIFICATION_PUSH, NOTIFICATION_EMAIL, NOTIFICATION_SMS]

            for method in methods:
                if method_preference and method != method_preference:
                    continue

                try:
                    if method == NOTIFICATION_PUSH:
                        await self._send_push_notification(user_id, message, urgent=True)
                    elif method == NOTIFICATION_EMAIL:
                        await self._send_email_notification(user_id, message, urgent=True)
                    elif method == NOTIFICATION_SMS:
                        await self._send_sms_notification(user_id, message, urgent=True)

                    logger.info(f"Fallback bildirim gönderildi: {method}")
                    return True

                except Exception:
                    continue

            return False

        except Exception as exc:
            logger.exception("Fallback gönderme başarısız")
            return False
