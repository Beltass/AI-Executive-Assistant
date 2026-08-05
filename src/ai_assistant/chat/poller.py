"""Yoklayıcı: kanalı oku, işle, cevapla, imleci ilerlet.

    python -m ai_assistant.chat.poller

Bir GitHub Actions cron'u bunu birkaç dakikada bir çalıştırır. Her çalıştırma
YENİ BİR SÜREÇTİR; kaldığı yeri :mod:`ai_assistant.chat.store` içindeki imleçten
öğrenir.

Bir turun anatomisi:

1. imleçten sonraki mesajlar ``conversations.history`` ile okunur,
2. botun KENDİ mesajları ve sistem mesajları elenir (yoksa bot kendi menüsünü
   komut sanar ve sonsuza kadar kendisiyle konuşur),
3. her mesaj sırayla durum makinesine verilir,
4. cevaplar ``chat.postMessage`` ile yazılır,
5. onaylanan sipariş varsa rapor üretilir ve teslim edilir,
6. imleç işlenen SON mesaja çekilir ve diske yazılır.

YAPILANDIRILMAMIŞSA HİÇBİR ŞEY YAPMAZ. ``SLACK_BOT_TOKEN`` ya da kanal yoksa
çıkış kodu 0'dır ve tek satır log düşer — çatallanmış bir depoda bu iş kırmızı
yanmaz.

İMLEÇ, HATA OLSA DA İLERLER. Bir mesajın işlenmesi çökerse kullanıcıya hata
yazılır ve imleç yine de o mesajı geçer: aksi hâlde aynı bozuk mesaj her beş
dakikada bir yeniden denenir ve kanal aynı hatayla dolar.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

from . import delivery as delivery_mod
from .session import SessionEngine, Turn
from .slack_api import (
    BOT_TOKEN_ENV,
    DEFAULT_HISTORY_LIMIT,
    SlackClient,
    SlackError,
    SlackMessage,
    analyst_channel,
    bot_token,
)
from .store import ChatStore

logger = logging.getLogger(__name__)

#: Bir turda en çok bu kadar mesaj işlenir. Uzun bir sessizlikten sonra kanal
#: dolu olabilir; hepsini birden işlemek Slack'i de kullanıcıyı da boğar.
MAX_MESSAGES_ENV = "CHAT_POLL_MAX_MESSAGES"
DEFAULT_MAX_MESSAGES = 20

#: Bot ilk kez çalıştığında GEÇMİŞİ işlemez. İmleç yokken kanaldaki eski
#: mesajlara toplu cevap yazmak, kullanıcının hiç istemediği bir şeydir.
FIRST_RUN_LIMIT = 1


def max_messages() -> int:
    raw = (os.getenv(MAX_MESSAGES_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_MESSAGES
    return value if value > 0 else DEFAULT_MAX_MESSAGES


@dataclass
class PollReport:
    """Bir turun sonucu — iş günlüğüne yazılan özet."""

    configured: bool = False
    channel: str = ""
    read: int = 0
    handled: int = 0
    replies: int = 0
    reports: int = 0
    errors: List[str] = field(default_factory=list)
    skipped_reason: str = ""

    def summary_line(self) -> str:
        if not self.configured:
            return f"sohbet yoklaması yapılmadı — {self.skipped_reason}"
        parts = [
            f"{self.read} mesaj okundu",
            f"{self.handled} işlendi",
            f"{self.replies} cevap",
        ]
        if self.reports:
            parts.append(f"{self.reports} rapor")
        if self.errors:
            parts.append(f"{len(self.errors)} hata")
        return " · ".join(parts)


def run_once(
    client: Optional[SlackClient] = None,
    store: Optional[ChatStore] = None,
    engine: Optional[SessionEngine] = None,
    channel: str = "",
    now: Optional[datetime] = None,
    deliver: Any = None,
) -> PollReport:
    """Tek bir yoklama turu. Asla istisna fırlatmaz."""
    report = PollReport()

    target = channel or analyst_channel()
    api = client or (SlackClient() if bot_token() else None)
    if api is None or not api.configured:
        report.skipped_reason = f"kimlik bilgisi yok ({BOT_TOKEN_ENV})"
        logger.info("Sohbet yoklaması atlandı: %s", report.skipped_reason)
        return report
    if not target:
        report.skipped_reason = "sohbet kanalı tanımlı değil (SLACK_ANALYST_CHANNEL)"
        logger.info("Sohbet yoklaması atlandı: %s", report.skipped_reason)
        return report

    report.configured = True
    report.channel = target

    state = store or ChatStore()
    state.prune_sessions(now)
    # Motor ağa çıkmaz; ama uzun süren bir iş (not özeti tek bir model çağrısı
    # alır) başlamadan önce kanala "bakıyorum" yazabilmesi için Slack'e yazan
    # tek satırlık bir geri çağrı verilir. Beş dakikalık yoklamada kullanıcının
    # isteğinin düştüğünü hemen görmesi budur.
    brain = engine or SessionEngine(
        store=state,
        now=now,
        notifier=lambda text: _post(api, target, report, text),
    )
    runner = deliver or delivery_mod.run

    cursor = state.cursor(target)
    try:
        messages = api.history(target, oldest=cursor, limit=DEFAULT_HISTORY_LIMIT)
    except SlackError as exc:
        report.errors.append(str(exc))
        logger.warning("Kanal okunamadı: %s", exc)
        return report

    report.read = len(messages)
    usable = [m for m in messages if _is_user_message(m)]

    if not cursor:
        # İlk çalıştırma: geçmişe cevap yazma, yalnızca en son mesajı işle ve
        # imleci oraya çek.
        usable = usable[-FIRST_RUN_LIMIT:]
        if messages:
            state.set_cursor(target, messages[-1].ts)

    limit = max_messages()
    if len(usable) > limit:
        skipped = len(usable) - limit
        usable = usable[-limit:]
        _post(
            api,
            target,
            report,
            f"Son {skipped} mesajı atladım; en yeniden devam ediyorum.",
        )

    for message in usable:
        try:
            turn = brain.handle(target, message.user, message.text)
        except Exception as exc:  # pragma: no cover - motor kendi içinde yakalıyor
            logger.exception("mesaj işlenemedi: %s", exc)
            report.errors.append(str(exc))
            _post(
                api,
                target,
                report,
                f"Bu mesajı işleyemedim ({type(exc).__name__}). `rapor` yazarak "
                "yeniden başlayabilirsiniz.",
            )
            state.set_cursor(target, message.ts)
            state.save()
            continue

        if turn.ignored:
            state.set_cursor(target, message.ts)
            continue

        report.handled += 1
        for text in turn.messages:
            _post(api, target, report, text)

        if turn.spec is not None:
            _run_report(runner, turn, api, target, report, now)

        # İmleç HER mesajdan sonra yazılır: teslimat uzun sürer, süreç o sırada
        # kesilirse aynı rapor bir daha üretilmemeli.
        state.set_cursor(target, message.ts)
        state.save()

    state.save()
    logger.info("Sohbet yoklaması: %s", report.summary_line())
    return report


def _run_report(
    runner: Any,
    turn: Turn,
    api: SlackClient,
    channel: str,
    report: PollReport,
    now: Optional[datetime],
) -> None:
    """Onaylanan siparişi üretir. Hata da olsa kanala bir cevap düşer."""
    try:
        result = runner(turn.spec, channel, client=api, now=now)
    except Exception as exc:  # pragma: no cover - delivery kendi içinde yakalıyor
        logger.exception("rapor üretilemedi: %s", exc)
        report.errors.append(str(exc))
        _post(
            api,
            channel,
            report,
            f"Rapor üretilemedi ({type(exc).__name__}): {exc}",
        )
        return
    for text in getattr(result, "messages", []) or []:
        _post(api, channel, report, text)
    if getattr(result, "ok", False):
        report.reports += 1
    else:
        report.errors.append(str(getattr(result, "error", "") or "rapor üretilemedi"))


def _post(api: SlackClient, channel: str, report: PollReport, text: str) -> None:
    """Kanala yazar; yazamazsa turu çökertmez, hatayı kaydeder."""
    body = str(text or "").strip()
    if not body:
        return
    try:
        api.post(channel, body)
        report.replies += 1
    except SlackError as exc:
        logger.warning("Cevap gönderilemedi: %s", exc)
        report.errors.append(str(exc))
    except Exception as exc:  # pragma: no cover - savunma
        logger.warning("Cevap gönderilemedi: %s", exc)
        report.errors.append(str(exc))


def _is_user_message(message: SlackMessage) -> bool:
    """İşlenecek mesaj mı?

    Botun kendi mesajı ELENİR — bu, yoklamalı bir botun kendi kuyruğunu
    yemesini engelleyen tek kural. Katılma/ayrılma gibi sistem mesajları da
    elenir; kullanıcı kimliği olmayan mesaj da öyle.
    """
    if message.is_bot or message.is_joinish:
        return False
    if not message.user or not message.text.strip():
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_assistant.chat.poller",
        description="Slack sohbet kanalını yoklar ve rapor siparişlerini işler.",
    )
    parser.add_argument(
        "--channel",
        default="",
        help="Yoklanacak kanal kimliği (varsayılan: SLACK_ANALYST_CHANNEL).",
    )
    parser.add_argument("--verbose", action="store_true", help="Ayrıntılı günlük.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI girişi. Yapılandırma yoksa 0 döner ve hiçbir şey yapmaz."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    report = run_once(channel=args.channel)
    print(report.summary_line())
    # Hata bile olsa 0: yoklama kaçırılabilir bir iştir, bir sonraki tur
    # aynı yerden devam eder. Kırmızı bir cron, düzeltilmeyen bir cron olur.
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "DEFAULT_MAX_MESSAGES",
    "FIRST_RUN_LIMIT",
    "MAX_MESSAGES_ENV",
    "PollReport",
    "build_parser",
    "main",
    "max_messages",
    "run_once",
]
