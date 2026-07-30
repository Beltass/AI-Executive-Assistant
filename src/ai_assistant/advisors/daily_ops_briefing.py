"""Start-of-day operations briefing — Gün Başı Operasyon Brifingi.

Reads TODAY's real inputs from Gmail and Google Calendar and turns them into a
Turkish "what actually matters this morning" briefing: which e-mails need an
action or are waiting on your reply, today's meetings with a one-line prep note
each, clashes and the free blocks left for deep work, and the day's three
critical priorities.

Auth: reuses the EXISTING shared Google OAuth
(:mod:`ai_assistant.integrations.google_auth`, read-only scopes). No new auth is
invented. Until the one-time login has been done::

    python -m ai_assistant.integrations.google_auth

the advisor reports ``skipped`` with that exact instruction — which is the
expected state on a fresh checkout and on GitHub Actions.

PRIVACY: only metadata (sender, subject, date) and Gmail's own short snippet are
read — never a full message body — and the snippet is truncated before it ever
reaches the model. Nothing is written back to Google; every scope is read-only.

Data first, LLM second: like the RSS-backed advisors, the Google fetch happens
locally and only the *summarization* of the gathered facts joins the single
batched team call.

Configuration (via environment):
    OPS_BRIEFING_MAX_EMAILS   How many recent messages to look at (default 12).
    OPS_BRIEFING_EMAIL_WINDOW Gmail ``newer_than`` window (default ``1d``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from . import Advisor, BatchSection, Briefing
from ..integrations import google_auth, llm
from ._llm_base import RICH_BRIEFING_GUIDE

DEFAULT_MAX_EMAILS = 12
DEFAULT_EMAIL_WINDOW = "1d"

# Gmail snippets are short by design; truncate anyway so no long quoted thread
# can travel to the model.
SNIPPET_LIMIT = 220

SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth)"
)

SYSTEM_PROMPT = (
    "Sen, üst düzey bir yöneticinin şefdökabinesi (chief of staff) gibi "
    "çalışan bir operasyon asistanısın. Türkçe konuşuyorsun. Sabah, "
    "yöneticinin gerçek e-posta ve takvim verisine bakar ve ona 'bugün "
    "gerçekten ne önemli' sorusunun cevabını verirsin. Kısa, net ve "
    "önceliklendirilmiş yazarsın; dolgu cümle kurmazsın.\n\n"
    "KURALLAR: Sadece sana verilen verilere dayan. Sana verilmeyen bir "
    "e-postayı, toplantıyı, kişiyi veya kararı UYDURMA. Veri azsa bunu "
    "dürüstçe söyle. E-posta içeriklerini olduğu gibi kopyalama; özetle. "
    "Kişisel/hassas ayrıntıları gereksiz yere tekrar etme."
)

CAVEAT = (
    "🔒 Not: Bu bölüm Gmail ve Takvim'den yalnızca OKUMA yetkisiyle alınan "
    "başlık/özet bilgilerine dayanır; e-posta gövdeleri işlenmez. Aksiyon "
    "almadan önce ilgili e-postayı/daveti kendiniz açın."
)


@dataclass
class OpsFacts:
    """The real data gathered from Google before any LLM work."""

    emails: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.emails or self.events)

    def as_text(self) -> str:
        lines: List[str] = []
        if self.emails:
            lines.append("SON E-POSTALAR (okunmamış/öne çıkanlar):")
            lines.extend(f"- {item}" for item in self.emails)
        else:
            lines.append("SON E-POSTALAR: yeni/okunmamış e-posta bulunamadı.")
        if self.events:
            lines.append("")
            lines.append("BUGÜNKÜ TAKVİM:")
            lines.extend(f"- {item}" for item in self.events)
        else:
            lines.append("")
            lines.append("BUGÜNKÜ TAKVİM: bugün için planlanmış toplantı yok.")
        if self.notes:
            lines.append("")
            lines.append("VERİ NOTLARI: " + "; ".join(self.notes))
        return "\n".join(lines)


class DailyOpsBriefingAdvisor(Advisor):
    key = "daily_ops_briefing"
    title = "Gün Başı Operasyon Brifingi"

    def __init__(self) -> None:
        self._facts: Optional[OpsFacts] = None
        self._error: str = ""

    # -- main path -------------------------------------------------------
    def _generate(self) -> Briefing:
        if not google_auth.google_configured():
            return self.skipped(SKIP_DETAIL)

        facts = self._gather()
        if facts is None:
            return self.failed(self._error or "Google verisi alınamadı")

        if not llm.is_configured():
            # Still useful without a model: the raw, already-summarized facts.
            return self.ok(f"{facts.as_text()}\n\n{CAVEAT}")

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception:
            # Never lose the real data because the model was unavailable.
            return self.ok(f"{facts.as_text()}\n\n{CAVEAT}")

        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not llm.is_configured() or not google_auth.google_configured():
            return None
        if self._gather() is None:
            return None  # per-advisor path reports the failure
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        return self.ok(f"{text.strip()}\n\n{CAVEAT}")

    # -- data gathering --------------------------------------------------
    def _gather(self) -> Optional[OpsFacts]:
        """Fetch Gmail + Calendar once. Returns ``None`` when nothing worked."""
        if self._facts is not None or self._error:
            return self._facts

        try:
            creds = google_auth.get_credentials()
        except Exception as exc:
            self._error = f"Google kimlik doğrulaması başarısız: {exc}"
            return None

        facts = OpsFacts()
        gmail_ok = self._collect_emails(creds, facts)
        calendar_ok = self._collect_events(creds, facts)

        if not gmail_ok and not calendar_ok:
            self._error = (
                "Gmail ve Takvim verisi alınamadı: " + "; ".join(facts.notes)
            )
            return None

        self._facts = facts
        return facts

    def _collect_emails(self, creds, facts: OpsFacts) -> bool:
        """Read a bounded set of recent messages (metadata + snippet only)."""
        try:
            from googleapiclient.discovery import build

            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            query = (
                f"newer_than:{_email_window()} "
                "(is:unread OR is:important) -category:promotions -category:social"
            )
            listing = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=_max_emails())
                .execute()
            )
            for ref in listing.get("messages", [])[: _max_emails()]:
                message = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=ref["id"],
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
                facts.emails.append(_format_email(message))
        except Exception as exc:
            facts.notes.append(f"Gmail okunamadı ({type(exc).__name__})")
            return False
        return True

    def _collect_events(self, creds, facts: OpsFacts) -> bool:
        """Read today's calendar events (single instances, in order)."""
        try:
            from googleapiclient.discovery import build

            service = build(
                "calendar", "v3", credentials=creds, cache_discovery=False
            )
            start, end = _today_bounds()
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=start,
                    timeMax=end,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=20,
                )
                .execute()
            )
            for event in result.get("items", []):
                facts.events.append(_format_event(event))
        except Exception as exc:
            facts.notes.append(f"Takvim okunamadı ({type(exc).__name__})")
            return False
        return True

    # -- prompt ----------------------------------------------------------
    def _user_prompt(self) -> str:
        facts = self._facts or OpsFacts()
        today = date.today().strftime("%d.%m.%Y")
        return (
            f"Tarih: {today}\n\n"
            "Aşağıda yöneticinin GERÇEK verisi var. Yalnızca bu veriye dayanarak "
            "bir gün başı operasyon brifingi yaz:\n\n"
            f"{facts.as_text()}\n\n"
            "Brifingi şu bölümlerle ver:\n"
            "1) *📥 E-postalar*: aksiyon gerektirenler ve senden cevap bekleyenler "
            "ayrı ayrı; her biri için kimden, konu ve önerilen tek cümlelik aksiyon. "
            "Önemsizleri tek satırda topla.\n"
            "2) *📅 Bugünkü toplantılar*: saat sırasıyla; her biri için 1-2 cümlelik "
            "hazırlık notu (neye bakılmalı, hangi soru sorulmalı, hangi karar çıkmalı).\n"
            "3) *⚠️ Çakışmalar ve boşluklar*: üst üste binen randevular, arka arkaya "
            "toplantı blokları ve derin çalışma için kullanılabilecek boş zaman "
            "aralıkları (saat vererek).\n"
            "4) *🎯 Günün 3 kritik önceliği*: numaralı, her biri tek cümle ve "
            "ölçülebilir bir bitiş tanımıyla.\n"
            "5) *✅ Bugünün görevi*: bunlardan İLK yapılması gerekeni tek bir somut "
            "eylem olarak yaz.\n\n"
            "Veri yoksa uydurma; 'bugün takvimin boş, bu fırsatı şuna kullan' gibi "
            "dürüst ve yararlı bir yönlendirme yap. Yaklaşık 250-400 kelime, "
            "Slack'te güzel görünecek Markdown ile yaz.\n\n"
            "Not: Bu bölümde '📚 Kaynaklar' listesi verme; kaynak yerine kendi "
            "verine dayan. Ama aşağıdaki yazım rehberinin ton ve biçim "
            "kurallarına uy:\n" + RICH_BRIEFING_GUIDE
        )


# --- helpers ----------------------------------------------------------------


def _max_emails() -> int:
    try:
        value = int(os.getenv("OPS_BRIEFING_MAX_EMAILS") or DEFAULT_MAX_EMAILS)
    except ValueError:
        value = DEFAULT_MAX_EMAILS
    return max(1, min(value, 25))


def _email_window() -> str:
    raw = (os.getenv("OPS_BRIEFING_EMAIL_WINDOW") or "").strip()
    # Only a simple ``<n><unit>`` window is accepted, so nothing user-supplied
    # can reshape the Gmail query.
    if raw and raw[:-1].isdigit() and raw[-1] in "hd":
        return raw
    return DEFAULT_EMAIL_WINDOW


def _today_bounds() -> tuple:
    """RFC3339 start/end of today in the local timezone."""
    tz = datetime.now().astimezone().tzinfo
    today = date.today()
    start = datetime.combine(today, time.min, tzinfo=tz)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def _header(message: dict, name: str) -> str:
    headers = (message.get("payload") or {}).get("headers") or []
    for header in headers:
        if (header.get("name") or "").lower() == name.lower():
            return (header.get("value") or "").strip()
    return ""


def _format_email(message: dict) -> str:
    sender = _header(message, "From") or "bilinmeyen gönderen"
    subject = _header(message, "Subject") or "(konu yok)"
    snippet = (message.get("snippet") or "").strip().replace("\n", " ")
    if len(snippet) > SNIPPET_LIMIT:
        snippet = snippet[:SNIPPET_LIMIT] + "…"
    labels = message.get("labelIds") or []
    flags = []
    if "UNREAD" in labels:
        flags.append("okunmamış")
    if "IMPORTANT" in labels:
        flags.append("önemli")
    flag_txt = f" [{', '.join(flags)}]" if flags else ""
    snippet_txt = f" — {snippet}" if snippet else ""
    return f"{sender} | {subject}{flag_txt}{snippet_txt}"


def _format_event(event: dict) -> str:
    summary = (event.get("summary") or "(başlıksız etkinlik)").strip()
    start = _event_time(event.get("start") or {})
    end = _event_time(event.get("end") or {})
    when = f"{start}-{end}" if start and end else (start or "saat belirsiz")
    attendees = event.get("attendees") or []
    people = f", {len(attendees)} katılımcı" if attendees else ""
    location = (event.get("location") or "").strip()
    where = f", yer: {location}" if location else ""
    online = ", online" if event.get("hangoutLink") else ""
    return f"{when} | {summary}{people}{where}{online}"


def _event_time(node: dict) -> str:
    raw = node.get("dateTime") or node.get("date") or ""
    if not raw:
        return ""
    if "T" not in raw:
        return "tüm gün"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError:
        return raw[11:16] or raw
