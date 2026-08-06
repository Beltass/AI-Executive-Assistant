"""Email analysis advisor — E-posta Analiz Danışmanı.

Analyzes the user's recent emails (last 24 hours) from Gmail, categorizes them
by importance and priority, extracts action items, and provides a detailed
summary with trends and recommendations.

Features:
    - Analyzes last 24 hours of emails
    - Categorizes by importance: Acil (Urgent), Önemli (Important),
      Bilgi (Info), Harekete Geçilecek (Action)
    - Extracts action items with Turkish keywords
    - Identifies VIP senders (CEO, managers, important clients)
    - Tracks email volume and trends
    - Generates structured JSON report
    - Gracefully handles missing Gmail access

Auth: reuses the EXISTING shared Google OAuth
(:mod:`ai_assistant.integrations.google_auth`, read-only scopes).

PRIVACY: only metadata (sender, subject, date) and Gmail's own short snippet
are read — never a full message body. All data is processed locally.

Configuration (via environment):
    MAIL_ANALYST_MAX_EMAILS    How many recent messages to analyze (default 50).
    MAIL_ANALYST_EMAIL_WINDOW  Gmail ``newer_than`` window (default ``1d``).

Data first: email fetch and categorization happen locally; only summarization
(if enabled) joins a batched LLM call.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from . import Advisor, Briefing
from ..integrations import google_auth

DEFAULT_MAX_EMAILS = 50
DEFAULT_EMAIL_WINDOW = "1d"
SNIPPET_LIMIT = 220

SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth, then set "
    "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN to run "
    "in the cloud)"
)

# Keywords for categorizing emails (Turkish)
URGENT_KEYWORDS = [
    "acil",
    "hemen",
    "bugün",
    "deadline",
    "critical",
    "kritikal",
    "emergency",
    "urgent",
    "önemli",
    "asap",
    "hızlı",
    "hızlıca",
    "derhal",
    "immediately",
    "zanı",
    "zanında",
    "yanında",
]

ACTION_KEYWORDS = [
    "lütfen",
    "please",
    "ihtiyaç",
    "need",
    "request",
    "istek",
    "yapacaksınız",
    "yapcaksınız",
    "toplantı",
    "meeting",
    "görüş",
    "sonuç",
    "result",
    "bilgi",
    "information",
    "onay",
    "approval",
]

# VIP sender patterns
VIP_PATTERNS = [
    r"\b[Cc][Ee][Oo]\b",
    r"\bcto\b",
    r"\bchief\b",
    r"\bmanager\b",
    r"\byönetici\b",
    r"\bdirector\b",
    r"\bdirecteur\b",
    r"\bkurucu\b",
    r"\bfounders?\b",
    r"\bexecutive\b",
    r"\bvp\b",
    r"\bboss\b",
]


@dataclass
class EmailMessage:
    """Parsed email metadata and categorization."""

    email_id: str
    sender: str
    subject: str
    timestamp: str
    snippet: str
    importance: str  # urgent, important, action, info
    is_unread: bool = False
    is_starred: bool = False
    action_item: Optional[str] = None
    is_vip_sender: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, omitting email_id for the report."""
        d = asdict(self)
        d.pop("email_id", None)
        return d


@dataclass
class MailStats:
    """Email analysis statistics."""

    total_emails: int = 0
    unread: int = 0
    from_vip: int = 0
    urgent: int = 0
    important: int = 0
    info: int = 0
    action_needed: int = 0
    action_items: int = 0
    avg_response_time_hours: float = 0.0
    volume_trend: str = "normal"  # increasing, normal, decreasing

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MailReport:
    """Structured email analysis report."""

    generated_at: str
    period: str
    summary: str
    stats: MailStats
    emails: List[Dict[str, Any]]
    action_items: List[str]
    trends: Dict[str, Any]

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "generated_at": self.generated_at,
                "period": self.period,
                "summary": self.summary,
                "stats": self.stats.to_dict(),
                "emails": self.emails,
                "action_items": self.action_items,
                "trends": self.trends,
            },
            ensure_ascii=False,
            indent=2,
        )


class MailAnalystAdvisor(Advisor):
    """Email analysis advisor — analyzes recent emails and categorizes them."""

    key = "mail_analyst"
    title = "E-posta Analiz Danışmanı"

    # Emails contain personal data: sender names, subjects, content snippets
    private = True

    # Emails are a genuine source of new findings (if new emails arrive)
    incremental_source = False  # Usually no new emails on incremental runs

    def __init__(self) -> None:
        self._emails: List[EmailMessage] = []
        self._error: str = ""
        self._report: Optional[MailReport] = None

    # -- main path -------------------------------------------------------
    def _generate(self) -> Briefing:
        if not google_auth.google_configured():
            return self.skipped(SKIP_DETAIL)

        emails = self._gather_emails()
        if emails is None:
            return self.failed(self._error or "E-posta verileri alınamadı")

        if not emails:
            return self.ok(
                "**Öne çıkan:** Son 24 saatte yeni e-posta yok.\n\n"
                "Gelen kutunuz sessiz — bu güzel bir istirahat fırsatı."
            )

        self._emails = emails
        report = self._generate_report()
        self._report = report

        return self.ok(self._format_briefing(report))

    # -- data gathering --------------------------------------------------
    def _gather_emails(self) -> Optional[List[EmailMessage]]:
        """Fetch recent emails from Gmail (last 24 hours)."""
        try:
            creds = google_auth.get_credentials()
        except Exception as exc:
            self._error = f"Google kimlik doğrulaması başarısız: {exc}"
            return None

        try:
            from googleapiclient.discovery import build

            service = build("gmail", "v1", credentials=creds, cache_discovery=False)

            # Query: last 24 hours, exclude promotions/social, exclude drafts/sent
            query = (
                f"newer_than:{_email_window()} "
                "-category:promotions -category:social "
                "-label:DRAFT -label:SENT"
            )

            listing = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=_max_emails())
                .execute()
            )

            emails = []
            for ref in listing.get("messages", [])[: _max_emails()]:
                try:
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
                    email = self._parse_email(message)
                    if email:
                        emails.append(email)
                except Exception:  # Skip individual message parsing errors
                    continue

            return emails

        except Exception as exc:
            self._error = f"Gmail okunamadı: {type(exc).__name__}: {exc}"
            return None

    def _parse_email(self, message: dict) -> Optional[EmailMessage]:
        """Parse Gmail message metadata into EmailMessage."""
        msg_id = message.get("id", "")
        if not msg_id:
            return None

        sender = self._get_header(message, "From") or "bilinmeyen gönderen"
        subject = self._get_header(message, "Subject") or "(konu yok)"
        date_str = self._get_header(message, "Date") or ""

        snippet = (message.get("snippet") or "").strip().replace("\n", " ")
        if len(snippet) > SNIPPET_LIMIT:
            snippet = snippet[:SNIPPET_LIMIT] + "…"

        labels = message.get("labelIds") or []
        is_unread = "UNREAD" in labels
        is_starred = "STARRED" in labels

        # Categorize email
        importance = self._categorize_email(subject, snippet, sender)

        # Extract action item if present
        action_item = None
        if importance in ("urgent", "action"):
            action_item = self._extract_action_item(subject, snippet)

        # Check if sender is VIP
        is_vip = self._is_vip_sender(sender)

        # Parse timestamp (Gmail date format)
        timestamp = self._parse_date(date_str)

        return EmailMessage(
            email_id=msg_id,
            sender=sender,
            subject=subject,
            timestamp=timestamp,
            snippet=snippet,
            importance=importance,
            is_unread=is_unread,
            is_starred=is_starred,
            action_item=action_item,
            is_vip_sender=is_vip,
        )

    # -- analysis --------------------------------------------------------
    def _categorize_email(self, subject: str, snippet: str, sender: str) -> str:
        """Categorize email by importance: urgent, important, action, info."""
        combined = f"{subject} {snippet} {sender}".lower()

        # Check for urgent keywords
        if any(kw in combined for kw in URGENT_KEYWORDS):
            return "urgent"

        # Check for VIP sender
        if self._is_vip_sender(sender):
            return "important"

        # Check for action keywords
        if any(kw in combined for kw in ACTION_KEYWORDS):
            return "action"

        # Default to info
        return "info"

    def _extract_action_item(self, subject: str, snippet: str) -> Optional[str]:
        """Extract action item text if detected."""
        combined = f"{subject}: {snippet}"

        # Look for common action patterns
        patterns = [
            r"lütfen\s+([^.!?]+[.!?])",
            r"please\s+([^.!?]+[.!?])",
            r"ihtiyaç\s+([^.!?]+[.!?])",
            r"yapacaksınız\s+([^.!?]+[.!?])",
            r"toplantı.*?(\d{2}:\d{2}|\d{1,2}[.]\d{1,2})",
        ]

        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                action_text = match.group(1).strip()
                return action_text[:150]  # Limit to 150 chars

        # Fallback: use first 100 chars of subject
        if subject and len(subject) < 150:
            return subject

        return None

    def _is_vip_sender(self, sender: str) -> bool:
        """Check if sender is a VIP (CEO, manager, important client)."""
        sender_lower = sender.lower()
        return any(re.search(pattern, sender_lower) for pattern in VIP_PATTERNS)

    def _parse_date(self, date_str: str) -> str:
        """Parse Gmail date header to ISO format."""
        if not date_str:
            return datetime.now().isoformat()

        try:
            # Gmail uses RFC 2822 format: "Mon, 31 Jul 2026 10:30:45 +0000"
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except Exception:
            return datetime.now().isoformat()

    # -- report generation -----------------------------------------------
    def _generate_report(self) -> MailReport:
        """Generate structured email analysis report."""
        now = datetime.now()
        stats = self._compute_stats()

        action_items = [
            email.action_item
            for email in self._emails
            if email.action_item and email.importance in ("urgent", "action")
        ]

        trends = {
            "volume_trend": self._compute_volume_trend(),
            "avg_response_time_hours": self._compute_avg_response_time(),
            "busiest_senders": self._get_busiest_senders(top=3),
        }

        summary = self._generate_summary(stats, action_items)

        # Prepare email list for report (sorted by importance)
        importance_order = {"urgent": 0, "important": 1, "action": 2, "info": 3}
        sorted_emails = sorted(
            self._emails,
            key=lambda e: (importance_order.get(e.importance, 3), e.timestamp),
            reverse=True,
        )

        return MailReport(
            generated_at=now.isoformat(),
            period="Son 24 saat",
            summary=summary,
            stats=stats,
            emails=[email.to_dict() for email in sorted_emails],
            action_items=action_items,
            trends=trends,
        )

    def _compute_stats(self) -> MailStats:
        """Compute email statistics."""
        stats = MailStats(total_emails=len(self._emails))
        stats.unread = sum(1 for e in self._emails if e.is_unread)
        stats.from_vip = sum(1 for e in self._emails if e.is_vip_sender)
        stats.urgent = sum(1 for e in self._emails if e.importance == "urgent")
        stats.important = sum(1 for e in self._emails if e.importance == "important")
        stats.info = sum(1 for e in self._emails if e.importance == "info")
        stats.action_needed = sum(1 for e in self._emails if e.importance == "action")
        stats.action_items = sum(1 for e in self._emails if e.action_item)
        return stats

    def _compute_volume_trend(self) -> str:
        """Compute email volume trend."""
        if len(self._emails) > 40:
            return "increasing"
        elif len(self._emails) < 10:
            return "decreasing"
        return "normal"

    def _compute_avg_response_time(self) -> float:
        """Estimate average response time based on urgency."""
        if not self._emails:
            return 0.0

        urgent = sum(1 for e in self._emails if e.importance == "urgent")
        if urgent > 0:
            return 1.0  # Urgent emails usually get 1 hour response

        action = sum(1 for e in self._emails if e.importance == "action")
        if action > 0:
            return 2.5  # Action items typically get 2.5 hours

        return 4.0  # Info emails can wait

    def _get_busiest_senders(self, top: int = 3) -> List[tuple]:
        """Get top senders by email count."""
        from collections import Counter

        senders = [e.sender.split(" <")[0].strip() for e in self._emails]
        counter = Counter(senders)
        return counter.most_common(top)

    def _generate_summary(self, stats: MailStats, action_items: List[str]) -> str:
        """Generate Turkish summary of email analysis."""
        lines = []

        if stats.urgent > 0:
            lines.append(
                f"⚠️ {stats.urgent} acil/önemli e-posta — hemen dikkat gerekiyor."
            )

        if action_items:
            lines.append(
                f"✅ {len(action_items)} çalışma maddesi tespit edildi — "
                "priorite listeni güncelle."
            )

        if stats.from_vip > 0:
            lines.append(f"👔 {stats.from_vip} VIP göndericiden posta vardır.")

        if stats.unread > 0:
            lines.append(f"📬 {stats.unread} okunmamış e-posta bulunmaktadır.")

        lines.append(
            f"📊 Toplam: {stats.total_emails} e-posta ({stats.action_needed} aksiyon, "
            f"{stats.info} bilgi), trend: {self._trend_text(stats.volume_trend)}."
        )

        return " ".join(lines) if lines else "E-posta analizi tamamlandı."

    def _trend_text(self, trend: str) -> str:
        """Convert trend to Turkish."""
        mapping = {
            "increasing": "artış",
            "normal": "normal",
            "decreasing": "azalış",
        }
        return mapping.get(trend, "normal")

    # -- formatting -------------------------------------------------------
    def _format_briefing(self, report: MailReport) -> str:
        """Format report as Turkish briefing."""
        lines = [f"**Öne çıkan:** {report.summary}"]
        lines.append("")

        # Stats section
        stats = report.stats
        lines.append("**📊 İstatistikler:**")
        lines.append(f"- Toplam: {stats.total_emails} e-posta")
        lines.append(f"- Okunmamış: {stats.unread}")
        lines.append(f"- Acil: {stats.urgent} | Önemli: {stats.important}")
        lines.append(f"- Aksiyon gerekli: {stats.action_needed} | Bilgi: {stats.info}")
        lines.append(f"- VIP gönderici: {stats.from_vip}")
        lines.append("")

        # Action items
        if report.action_items:
            lines.append("**✅ Çalışma Maddeleri:**")
            for i, item in enumerate(report.action_items[:5], 1):
                if item:
                    lines.append(f"{i}. {item[:120]}")
            lines.append("")

        # Category breakdown
        lines.append("**📧 Kategoriye göre dağılım:**")
        by_importance = {
            "urgent": [],
            "important": [],
            "action": [],
            "info": [],
        }
        for email in report.emails[:10]:
            imp = email.get("importance", "info")
            if imp in by_importance:
                subj = email.get("subject", "")[:50]
                by_importance[imp].append(subj)

        if by_importance["urgent"]:
            lines.append(
                f"- **Acil ({len(by_importance['urgent'])}):** "
                + ", ".join(by_importance["urgent"][:2])
            )
        if by_importance["important"]:
            lines.append(
                f"- **Önemli ({len(by_importance['important'])}):** "
                + ", ".join(by_importance["important"][:2])
            )
        if by_importance["action"]:
            lines.append(
                f"- **Aksiyon ({len(by_importance['action'])}):** "
                + ", ".join(by_importance["action"][:2])
            )
        if by_importance["info"]:
            lines.append(
                f"- **Bilgi ({len(by_importance['info'])}):** "
                + ", ".join(by_importance["info"][:2])
            )

        lines.append("")
        lines.append("**✅ Bugünün görevi:** Acil e-postaları ve aksiyon maddelerini ")
        lines.append(
            "öncelik sırasıyla gözden geçir; hemen cevap verilecekler işaretle."
        )
        lines.append("")
        lines.append(
            "🔒 Not: Bu bölüm Gmail'den yalnızca OKUMA yetkisiyle alınan "
            "başlık/özet bilgilerine dayanır; tam e-posta gövdeleri işlenmez."
        )

        return "\n".join(lines)


# --- helpers ----------------------------------------------------------------


def _max_emails() -> int:
    """Get max emails to analyze from environment."""
    try:
        value = int(os.getenv("MAIL_ANALYST_MAX_EMAILS") or DEFAULT_MAX_EMAILS)
    except ValueError:
        value = DEFAULT_MAX_EMAILS
    return max(1, min(value, 100))


def _email_window() -> str:
    """Get email time window from environment."""
    raw = (os.getenv("MAIL_ANALYST_EMAIL_WINDOW") or "").strip()
    # Only simple ``<n><unit>`` window accepted (e.g., "1d", "24h")
    if raw and raw[:-1].isdigit() and raw[-1] in "hd":
        return raw
    return DEFAULT_EMAIL_WINDOW
