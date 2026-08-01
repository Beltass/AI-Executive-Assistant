"""Slack Web API'nin bu paketin ihtiyaç duyduğu ince dilimi.

Dört iş: kanalı OKU, mesaj YAZ, dosya YÜKLE, botun kendi kimliğini öğren.

TEK AĞ NOKTASI: her çağrı :meth:`SlackClient.call` üzerinden geçer ve o da
kurucuya verilen ``transport``ı kullanır. Testler tek bir sahte ``transport``
takarak bütün paketi ağa çıkmadan çalıştırır — dosya yüklemenin ham gövde
``PUT``ı da ayrı bir ``uploader`` olarak dışarı alınmıştır.

KİMLİK: yalnızca ``SLACK_BOT_TOKEN``. Gelen webhook (``SLACK_WEBHOOK_URL``)
kanal OKUYAMAZ ve tek bir kanala bağlıdır; bu katman onunla çalışmaz — token
yoksa yoklama hiçbir şey yapmadan çıkar.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from ..config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"

#: Sohbetin geçtiği kanal. Ayrı bir değişken, çünkü rapor siparişi bir danışman
#: yayını değil: kullanıcının BOTLA konuştuğu tek oda.
ANALYST_CHANNEL_ENV = "SLACK_ANALYST_CHANNEL"
#: Ayrı bir sohbet kanalı tanımlanmadıysa iş analisti kanalına düşülür.
FALLBACK_CHANNEL_ENVS = ("SLACK_CHANNEL_WORK_ANALYST", "SLACK_MAIN_CHANNEL", "SLACK_CHANNEL")

API_BASE = "https://slack.com/api/"

#: ``conversations.history`` bir yoklamada en çok bu kadar mesaj getirir.
DEFAULT_HISTORY_LIMIT = 50

#: Slack'in ham gövde yüklemesi büyük dosyada uzun sürer.
UPLOAD_TIMEOUT = 60.0


class SlackError(RuntimeError):
    """Slack bir isteği reddetti ya da istek hiç gitmedi."""


def bot_token() -> str:
    return (os.getenv(BOT_TOKEN_ENV) or "").strip()


def analyst_channel() -> str:
    """Sohbetin dinleneceği kanal; hiçbiri tanımlı değilse boş dize."""
    for env in (ANALYST_CHANNEL_ENV, *FALLBACK_CHANNEL_ENVS):
        value = (os.getenv(env) or "").strip()
        if value:
            return value
    return ""


@dataclass
class SlackMessage:
    """Kanaldan okunan tek mesaj."""

    ts: str = ""
    user: str = ""
    text: str = ""
    channel: str = ""
    bot_id: str = ""
    subtype: str = ""
    thread_ts: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_bot(self) -> bool:
        """Botun kendi mesajı mı?

        İki ayrı işaret: ``bot_id`` (uygulama yazdı) ve ``bot_message``
        alt tipi. Biri bile varsa bu mesaj işlenmez — yoksa bot kendi
        yanıtını komut sanıp sonsuz döngüye girer.
        """
        return bool(self.bot_id) or self.subtype == "bot_message"

    @property
    def is_joinish(self) -> bool:
        """Kanala katılma/ayrılma, sabitleme gibi sistem mesajı mı?"""
        return bool(self.subtype) and self.subtype != "thread_broadcast"

    @classmethod
    def from_payload(cls, payload: Dict[str, Any], channel: str = "") -> "SlackMessage":
        return cls(
            ts=str(payload.get("ts") or ""),
            user=str(payload.get("user") or ""),
            text=str(payload.get("text") or ""),
            channel=channel,
            bot_id=str(payload.get("bot_id") or ""),
            subtype=str(payload.get("subtype") or ""),
            thread_ts=str(payload.get("thread_ts") or ""),
            raw=dict(payload),
        )


def http_transport(method: str, payload: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Gerçek Slack çağrısı. Testler bunun yerine bir sahte takar.

    ``conversations.history`` gibi okuma yöntemleri JSON gövde kabul etmez, bu
    yüzden GET + sorgu parametresi ile çağrılır; yazma yöntemleri JSON gider.
    """
    url = API_BASE + method
    headers = {"Authorization": f"Bearer {token}"}
    try:
        if method in _GET_METHODS:
            response = httpx.get(
                url, headers=headers, params=_flatten(payload), timeout=REQUEST_TIMEOUT
            )
        else:
            headers["Content-Type"] = "application/json; charset=utf-8"
            response = httpx.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        raise SlackError(f"Slack isteği gönderilemedi ({method}): {exc}") from exc
    try:
        return response.json()
    except Exception as exc:
        raise SlackError(
            f"Slack yanıtı JSON değil ({method}, HTTP {response.status_code})"
        ) from exc


def http_uploader(url: str, filename: str, data: bytes) -> None:
    """Dosya gövdesini Slack'in verdiği tek kullanımlık adrese yükler."""
    try:
        response = httpx.post(
            url, files={"file": (filename, data)}, timeout=UPLOAD_TIMEOUT
        )
    except Exception as exc:
        raise SlackError(f"Dosya yüklenemedi: {exc}") from exc
    if response.status_code >= 400:
        raise SlackError(f"Dosya yüklenemedi (HTTP {response.status_code}).")


_GET_METHODS = {"conversations.history", "conversations.replies", "auth.test"}

#: Slack API hatalarının Türkçe karşılığı ve NE YAPILACAĞI.
ERROR_HELP = {
    "not_in_channel": (
        "Bot kanalda değil. Kanalda `/invite @asistan` yazıp botu ekleyin."
    ),
    "channel_not_found": (
        "Kanal bulunamadı. `SLACK_ANALYST_CHANNEL` değerinin kanal kimliği "
        "(C… ile başlar) olduğundan emin olun."
    ),
    "missing_scope": (
        "Bot yetkisi eksik. Uygulamaya `channels:history`, `chat:write` ve "
        "`files:write` kapsamlarını ekleyip yeniden yükleyin."
    ),
    "not_allowed_token_type": (
        "Bu işlem bot token'ı ister. `SLACK_BOT_TOKEN` değeri `xoxb-` ile "
        "başlamalı."
    ),
    "invalid_auth": "Slack token'ı geçersiz. `SLACK_BOT_TOKEN` değerini yenileyin.",
    "account_inactive": "Slack uygulaması devre dışı bırakılmış; yeniden etkinleştirin.",
    "ratelimited": "Slack hız sınırı devrede; bir sonraki yoklamada tekrar denenecek.",
}


def explain(error: str) -> str:
    """Slack hata kodunu "ne oldu, ne yapmalı" cümlesine çevirir."""
    code = str(error or "unknown")
    help_text = ERROR_HELP.get(code)
    return f"{help_text} (`{code}`)" if help_text else f"Slack hatası: `{code}`"


class SlackClient:
    """Bu paketin Slack'le konuştuğu tek nesne."""

    def __init__(
        self,
        token: str = "",
        transport: Optional[Callable[[str, Dict[str, Any], str], Dict[str, Any]]] = None,
        uploader: Optional[Callable[[str, str, bytes], None]] = None,
    ):
        self.token = token or bot_token()
        self._transport = transport or http_transport
        self._uploader = uploader or http_uploader

    @property
    def configured(self) -> bool:
        return bool(self.token)

    # --- düşük seviye -------------------------------------------------------

    def call(self, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Bir Slack yöntemini çağırır; ``ok`` değilse :class:`SlackError` atar."""
        if not self.token:
            raise SlackError(f"Slack kimliği yok ({BOT_TOKEN_ENV}).")
        data = self._transport(method, dict(payload or {}), self.token)
        if not isinstance(data, dict):
            raise SlackError(f"Slack yanıtı okunamadı ({method}).")
        if not data.get("ok"):
            raise SlackError(explain(str(data.get("error") or "unknown")))
        return data

    # --- okuma --------------------------------------------------------------

    def history(
        self, channel: str, oldest: str = "", limit: int = DEFAULT_HISTORY_LIMIT
    ) -> List[SlackMessage]:
        """Kanalın ``oldest``tan SONRAKİ mesajları, ESKİDEN YENİYE sıralı.

        Slack yeniden eskiye döner; sıralamayı burada çeviriyoruz çünkü bir
        sohbetin adımları sırayla işlenmek zorunda: kullanıcı "1" sonra "3"
        yazdıysa "3" önce işlenirse menü yanlış adımı görür.
        """
        payload: Dict[str, Any] = {"channel": channel, "limit": max(1, int(limit))}
        if oldest:
            # ``inclusive=false``: imlecin gösterdiği mesaj zaten işlenmişti.
            payload["oldest"] = oldest
            payload["inclusive"] = False
        data = self.call("conversations.history", payload)
        messages = [
            SlackMessage.from_payload(item, channel=channel)
            for item in (data.get("messages") or [])
            if isinstance(item, dict)
        ]
        messages.sort(key=lambda m: _ts(m.ts))
        return messages

    def bot_user_id(self) -> str:
        """Botun kullanıcı kimliği — kendi mesajlarını tanımanın ikinci yolu."""
        try:
            return str(self.call("auth.test").get("user_id") or "")
        except SlackError as exc:
            logger.debug("auth.test başarısız: %s", exc)
            return ""

    # --- yazma --------------------------------------------------------------

    def post(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: str = "",
    ) -> str:
        """Mesaj gönderir ve ``ts``sini döner."""
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = self.call("chat.postMessage", payload)
        return str(data.get("ts") or "")

    # --- dosya --------------------------------------------------------------

    def upload_file(
        self,
        channel: str,
        path: str,
        title: str = "",
        comment: str = "",
    ) -> str:
        """``.xlsx``i kanala yükler ve dosya kimliğini döner.

        files.upload v2 akışı: adres al → gövdeyi yükle → tamamla. Eski
        ``files.upload`` yöntemi Slack tarafından kapatıldı, bu yüzden üç adım.
        """
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise SlackError(f"Yüklenecek dosya okunamadı ({path}): {exc}") from exc

        filename = os.path.basename(path)
        ticket = self.call(
            "files.getUploadURLExternal",
            {"filename": filename, "length": len(data)},
        )
        upload_url = str(ticket.get("upload_url") or "")
        file_id = str(ticket.get("file_id") or "")
        if not upload_url or not file_id:
            raise SlackError("Slack yükleme adresi vermedi.")

        self._uploader(upload_url, filename, data)

        payload: Dict[str, Any] = {
            "files": json.dumps([{"id": file_id, "title": title or filename}]),
            "channel_id": channel,
        }
        if comment:
            payload["initial_comment"] = comment
        self.call("files.completeUploadExternal", payload)
        return file_id


def _ts(value: str) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _flatten(payload: Dict[str, Any]) -> Dict[str, Any]:
    """GET sorgusu için değerleri dizeye çevirir (bool -> "true"/"false")."""
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif value is None:
            continue
        else:
            out[key] = value
    return out


__all__ = [
    "ANALYST_CHANNEL_ENV",
    "API_BASE",
    "BOT_TOKEN_ENV",
    "DEFAULT_HISTORY_LIMIT",
    "ERROR_HELP",
    "SlackClient",
    "SlackError",
    "SlackMessage",
    "analyst_channel",
    "bot_token",
    "explain",
    "http_transport",
    "http_uploader",
]
