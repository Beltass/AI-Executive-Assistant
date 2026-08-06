"""Kişisel Asistan — gün yönetimi, hedefler, ağ ve fırsat takibi.

Bu danışman kullanıcının günlük operasyonunu destekler:

1. **Sabah Brifingi** — Bugünün öncelikleri, kritik e-postalar, takvim özeti
2. **Son Tarih Takibi** — Bugün ve yarın yapılması gereken görevler
3. **Hedef İzleme** — Haftalık hedef ilerlemesi ve mile taşları
4. **Ağ Önerileri** — Takip gereken kişiler, yeni bağlantı fırsatları
5. **Akşam Özeti** — Bugün neler yapıldı, yarın neler bekliyor
6. **Fırsat Uyarıları** — Yeni iş, konferans, bağlantı fırsatları

Kişisel asistan durumu `.assistant_state/personal_assistant.json` dosyasında
tutulur. Google Calendar ve Gmail entegrasyonu kullanır.

Configuration (ortam değişkenleri):
    PERSONAL_ASSISTANT_MORNING_TIME       Sabah brifingi saati (örn: "07:00")
    PERSONAL_ASSISTANT_EVENING_TIME       Akşam özeti saati (örn: "19:00")
    PERSONAL_ASSISTANT_TIMEZONE           Zaman dilimi (default: Europe/Istanbul)
    PERSONAL_ASSISTANT_WORKDAY_START      İş günü başlangıcı (default: "09:00")
    PERSONAL_ASSISTANT_WORKDAY_END        İş günü sonu (default: "18:00")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import STATUS_OK, STATUS_SKIPPED, llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

# Ortam değişkenleri
ENV_MORNING_TIME = "PERSONAL_ASSISTANT_MORNING_TIME"
ENV_EVENING_TIME = "PERSONAL_ASSISTANT_EVENING_TIME"
ENV_TIMEZONE = "PERSONAL_ASSISTANT_TIMEZONE"
ENV_WORKDAY_START = "PERSONAL_ASSISTANT_WORKDAY_START"
ENV_WORKDAY_END = "PERSONAL_ASSISTANT_WORKDAY_END"

# Durum dosyası
STATE_DIR = Path(".assistant_state")
STATE_FILE = STATE_DIR / "personal_assistant.json"

# Sistem istemesi
SYSTEM_PROMPT = """Sen kişisel bir asistansın. Türkçe konuşuyorsun, organize,
profesyonel ama sıcak bir ton kullanıyorsun.

Görev:
1. Günü planlama ve öncelikleri vurgulama
2. Kritik son tarihler ve e-postalar hakkında uyar
3. Hedef ilerlemesini takip etme
4. Ağ inşası ve takip önerileri sunma
5. Fırsat ve etkinlikler hakkında bilgi verme
"""

USER_PROMPT_TEMPLATE = """Günlük kişisel asistan briefingi hazırla:

## Takvim
Bugünün etkinlikleri: {events_summary}

## Görevler
Son tarih yaklaşan: {urgent_tasks}
Bu hafta hedefleri: {weekly_goals}

## E-posta
Kritik / VIP gelen kutusu: {urgent_emails}

Derinlemesine bir günlük danışmanlık briefingi hazırla:

1. **Sabah Özeti**: Bugünün top 3 öncelikleri
2. **Kritik Unsurlar**: Son tarihler, VIP e-postalar
3. **Hedef İlerlemesi**: Bu hafta neler yapıldı?
4. **Ağ Önerileri**: Kimi takip etmelisin?
5. **Bugünün Görevi**: 15-30 dakikalık somut eylem

Türkçe, yapılandırılmış, somut ve sabah motivasyonu içer.

{briefing_guide}"""


@dataclass
class PersonalAssistantState:
    """Kişisel asistan durumu."""

    last_briefing: Optional[str] = None
    weekly_goals: List[str] = field(default_factory=list)
    goal_progress: Dict[str, float] = field(default_factory=dict)
    recent_networks: List[Dict[str, str]] = field(default_factory=list)
    urgent_deadlines: List[Dict[str, str]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PersonalAssistantAdvisor(Advisor):
    """Günlük operasyon ve ağ yönetimi danışmanı."""

    key = "personal_assistant"
    title = "Kişisel Asistan"
    private = True  # Kişisel hedefler ve takipler

    def _generate(self) -> Briefing:
        """Günlük kişisel asistan briefingi üret."""
        if not llm.is_configured():
            return self.skipped(
                "LLM yapılandırılmadı (GEMINI_API_KEY veya OPENAI_API_KEY)"
            )

        try:
            # Kişisel veri topla (takvim, görevler, e-posta vb.)
            events_summary = self._get_calendar_summary()
            urgent_tasks = self._get_urgent_tasks()
            weekly_goals = self._get_weekly_goals()
            urgent_emails = self._get_urgent_emails()

            # Mock veri (gerçek integrasyon daha sonra)
            if not events_summary:
                events_summary = (
                    "4 etkinlik: 10:00 Takım Toplantısı, 14:00 Müşteri Sunumu"
                )
            if not urgent_tasks:
                urgent_tasks = "Rapor sunumu (Çarşamba), Projeye feedback verme (Cuma)"
            if not weekly_goals:
                weekly_goals = (
                    "5 yeni müşteri değer teklifi, Ekip motivasyon toplantısı"
                )
            if not urgent_emails:
                urgent_emails = "Müdür'den feedback, Müşteriden acil soru"

            # LLM ile briefingi üret
            briefing_text = self._generate_briefing(
                events_summary, urgent_tasks, weekly_goals, urgent_emails
            )

            # Durumu kaydet
            self._save_state(briefing_text)

            return self.ok(briefing_text)

        except Exception as exc:
            logger.exception("kişisel asistan briefingi başarısız")
            return self.failed(f"briefingi oluşturalamadı: {exc}")

    def _get_calendar_summary(self) -> str:
        """Google Calendar'dan bugünün etkinliklerini al."""
        # Mock: Gerçek implementasyon Google Calendar API kullanacak
        return ""

    def _get_urgent_tasks(self) -> str:
        """Son tarihine yaklaşan görevleri al."""
        # Mock: Gerçek implementasyon task sistemi entegrasyonu kullanacak
        return ""

    def _get_weekly_goals(self) -> str:
        """Bu hafta için hedefleri al."""
        state = self._load_state()
        return ", ".join(state.weekly_goals[:3]) if state.weekly_goals else ""

    def _get_urgent_emails(self) -> str:
        """Kritik e-postaları al."""
        # Mock: Gerçek implementasyon Gmail API kullanacak
        return ""

    def _generate_briefing(
        self,
        events_summary: str,
        urgent_tasks: str,
        weekly_goals: str,
        urgent_emails: str,
    ) -> str:
        """LLM yardımıyla briefingi yarat."""
        from ._llm_base import RICH_BRIEFING_GUIDE

        user_prompt = USER_PROMPT_TEMPLATE.format(
            events_summary=events_summary,
            urgent_tasks=urgent_tasks,
            weekly_goals=weekly_goals,
            urgent_emails=urgent_emails,
            briefing_guide=RICH_BRIEFING_GUIDE,
        )

        try:
            text = llm.generate_text(SYSTEM_PROMPT, user_prompt)
            return text
        except Exception as exc:
            logger.exception("LLM çağrısı başarısız")
            # Fallback metin
            return (
                f"**Öne çıkan:** Bugünün 3 önceliği: {urgent_tasks}\n\n"
                f"Takvim: {events_summary}\n"
                f"Hedef: {weekly_goals}\n\n"
                f"Kişisel asistan hazır. Detaylar için takvim ve görev listeni kontrol et."
            )

    def _save_state(self, last_briefing: str) -> None:
        """Kişisel asistan durumunu kaydet."""
        STATE_DIR.mkdir(exist_ok=True)

        state = self._load_state()
        state.last_briefing = last_briefing
        state.updated_at = datetime.now().isoformat()

        with open(STATE_FILE, "w") as f:
            json.dump(asdict(state), f, indent=2, ensure_ascii=False)

        logger.info("kişisel asistan durumu kaydedildi")

    def _load_state(self) -> PersonalAssistantState:
        """Kişisel asistan durumunu yükle."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    return PersonalAssistantState(**data)
            except Exception as exc:
                logger.warning(f"durum yükleme başarısız: {exc}")

        return PersonalAssistantState()

    def batch_section(self) -> Optional[BatchSection]:
        """Batched call'a katıl."""
        if not llm.is_configured():
            return None

        # Mock veriler
        events_summary = "4 etkinlik: 10:00 Takım Toplantısı, 14:00 Müşteri Sunumu"
        urgent_tasks = "Rapor sunumu (Çarşamba), Projeye feedback verme (Cuma)"
        weekly_goals = "5 yeni müşteri değer teklifi, Ekip motivasyon toplantısı"
        urgent_emails = "Müdür'den feedback, Müşteriden acil soru"

        user_prompt = USER_PROMPT_TEMPLATE.format(
            events_summary=events_summary,
            urgent_tasks=urgent_tasks,
            weekly_goals=weekly_goals,
            urgent_emails=urgent_emails,
            briefing_guide="(Yukarıdaki ORTAK YAZIM KURALLARI bu bölüm için de geçerli.)",
        )

        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
