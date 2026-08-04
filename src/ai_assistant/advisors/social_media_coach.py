"""Sosyal Medya İmaj Koçu — Instagram, Twitter ve diğer kişisel marka platformları.

Bu danışman kullanıcının kişisel marka görünürlüğünü ve sosyal medya imajını
optimize eder:

1. **Profil Optimizasyonu** — Bio, kapak fotoğrafı, bağlantılar
2. **İçerik Stratejisi** — Hergün için İçerik takvimi ve yazı önerileri
3. **Engagement İzleme** — Takip etçi büyümesi, etkileşim oranları
4. **Marka Tutarlılığı** — Tüm platformlarda görünüm ve mesajlaşma

Profil analizleri `.assistant_state/profile_analyses.json` dosyasında depolanır.
Mock mod başlangıcta; gerçek API entegrasyonu daha sonra mümkün.

Configuration (ortam değişkenleri):
    SOCIAL_MEDIA_INSTAGRAM_HANDLE    Instagram hesabı (örn: "@username")
    SOCIAL_MEDIA_TWITTER_HANDLE      Twitter/X hesabı
    SOCIAL_MEDIA_CONTENT_STRATEGY    "personal", "professional", "mixed"
    SOCIAL_MEDIA_POSTING_DAYS        Paylaşma günleri (örn: "mon,wed,fri")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import STATUS_OK, STATUS_SKIPPED, llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

# Ortam değişkenleri
ENV_INSTAGRAM = "SOCIAL_MEDIA_INSTAGRAM_HANDLE"
ENV_TWITTER = "SOCIAL_MEDIA_TWITTER_HANDLE"
ENV_STRATEGY = "SOCIAL_MEDIA_CONTENT_STRATEGY"
ENV_POSTING_DAYS = "SOCIAL_MEDIA_POSTING_DAYS"

# Durum dosyası
STATE_DIR = Path(".assistant_state")
PROFILES_FILE = STATE_DIR / "profile_analyses.json"

# Sistem istemesi
SYSTEM_PROMPT = """Sen deneyimli bir sosyal medya ve kişisel marka koçusun.
Uzmanlığın: profilin optimize edilmesi, içerik stratejisi, görünürlük ve
bağlantı inşası. Türkçe konuşuyorsun, profesyonel ama insani bir ton kullanıyorsun.

Görev:
1. Sosyal medya profillerini analiz et ve iyileştirme önerileri sun
2. Her gün İçerik stratejisi ve yazı önerileri yarat
3. Kişisel marka tutarlılığını izle ve güçlendir
"""

USER_PROMPT_TEMPLATE = """Bugün için sosyal medya danışmanlığı yap:

## Profil Bilgisi
Platform: {platform}
Hesap: {handle}
Strateji: {strategy}

Şunları içeren derinlemesine bir danışmanlık brifingi hazırla:

1. **Profil Analizi**: Bio, kapak fotoğrafı, bağlantılar ve CTA mevcut durumu
2. **Güçlü Yönler**: En iyi performans gösteren öğeler neler?
3. **İyileştirme Alanları**: Bio, hashtag stratejisi, gönderme zamanlaması
4. **Bu Hafta İçin 3 Post Fikri**: Her biri konu, başlık ve engagement stratejisi ile
5. **📚 Kaynaklar**: Platform-spesifik rehberler ve en iyi uygulamalar

Türkçe, yapılandırılmış, somut ve eylem odaklı yaz.

Çıktı formatı:
- Başlık: **Öne çıkan:** <tek cümlelik ana bulgu>
- Bölümlü metin, madde işaretleri
- Her post fikrinde: başlık, konu, CTA (Call To Action)
"""


@dataclass
class ProfileAnalysis:
    """Sosyal medya profili analiz sonucu."""
    platform: str  # "instagram", "twitter", "linkedin"
    handle: str
    analyzed_at: str
    strengths: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    bio_score: int = 0  # 0-100
    engagement_trend: str = "stable"  # "up", "down", "stable"
    recommendations: str = ""
    content_ideas: List[str] = field(default_factory=list)


class SocialMediaCoachAdvisor(Advisor):
    """Sosyal medya profil optimizasyonu ve içerik stratejisi danışmanı."""

    key = "social_media_coach"
    title = "Sosyal Medya İmaj Koçu"
    private = True  # Profil verisi kişisel olabilir

    def _generate(self) -> Briefing:
        """Sosyal medya profil analizi ve önerilerini üret."""
        instagram = setting(ENV_INSTAGRAM)
        twitter = setting(ENV_TWITTER)
        strategy = setting(ENV_STRATEGY) or "professional"

        if not instagram and not twitter:
            return self.skipped(
                "sosyal medya hesapları yapılandırılmadı. "
                f"{ENV_INSTAGRAM} veya {ENV_TWITTER} ayarlayın."
            )

        try:
            # Mock profil analizi (gerçek API daha sonra)
            profiles = []

            if instagram:
                profiles.append(self._analyze_instagram(instagram, strategy))
            if twitter:
                profiles.append(self._analyze_twitter(twitter, strategy))

            # LLM ile konsolide tavsiye al
            if not llm.is_configured():
                return self.skipped("LLM yapılandırılmadı (GEMINI_API_KEY veya OPENAI_API_KEY)")

            briefing_text = self._generate_briefing(profiles, strategy)

            # Analiz sonuçlarını kaydet
            self._save_analyses(profiles)

            return self.ok(briefing_text)

        except Exception as exc:
            logger.exception("sosyal medya analizi başarısız")
            return self.failed(f"sosyal medya analizi başarısız: {exc}")

    def _analyze_instagram(self, handle: str, strategy: str) -> ProfileAnalysis:
        """Instagram profili analiz et."""
        # Mock veri
        return ProfileAnalysis(
            platform="instagram",
            handle=handle,
            analyzed_at=datetime.now().isoformat(),
            strengths=[
                "Tutarlı paylaşım sıklığı (haftada 4 post)",
                "Yüksek engagement oranı (%4.2)",
                "Profesyonel gözüküm ve estetik"
            ],
            improvements=[
                "Bio'da CTA (Call To Action) yok",
                "Haştag stratejisi rastgele",
                "Hayran sayfalarına izin vermeme"
            ],
            bio_score=72,
            engagement_trend="up",
            recommendations="Bio'da açık bir CTA ekle (web sitesi linki, email)",
            content_ideas=[
                "İşe dönüş sorusu ile pazartesi motivasyon",
                "Haftalık 'neler öğrendim' paylaşımı",
                "Sektör haberlerinden kısa yorum"
            ]
        )

    def _analyze_twitter(self, handle: str, strategy: str) -> ProfileAnalysis:
        """Twitter/X profili analiz et."""
        # Mock veri
        return ProfileAnalysis(
            platform="twitter",
            handle=handle,
            analyzed_at=datetime.now().isoformat(),
            strengths=[
                "Güncel konulara hızlı tepki veriliyor",
                "Sektör liderlerini takip ve etkileşim"
            ],
            improvements=[
                "Bio'da profesyonel fotoğraf eksik",
                "Pinned tweet güncel değil",
                "Retweet fazlalığı (orijinal içerik azlığı)"
            ],
            bio_score=65,
            engagement_trend="stable",
            recommendations="En iyi performans gösteren 1 tweetini pin'le",
            content_ideas=[
                "Sabahın ilk haberini kısa analiz ile taşla",
                "Cuma akşamı haftalık özet",
                "Sektör etkinliklerinden canlı tweet"
            ]
        )

    def _generate_briefing(self, profiles: List[ProfileAnalysis], strategy: str) -> str:
        """LLM yardımıyla konsolide bir briefing yarat."""
        profile_text = "\n\n".join([
            f"**{p.platform.upper()}** (@{p.handle})\n"
            f"Skor: {p.bio_score}/100 | Trend: {p.engagement_trend}\n"
            f"Güçlü: {', '.join(p.strengths[:2])}\n"
            f"İyileştir: {', '.join(p.improvements[:2])}"
            for p in profiles
        ])

        user_prompt = f"""Sosyal medya profil analizi:

{profile_text}

Strateji: {strategy}

Türkçe, yapılandırılmış, somut ve eylem odaklı tavsiye yaz.
İlk satır: **Öne çıkan:** <tek cümle ana bulgu>
Sonra: İyileştirme alanları, bu hafta için 3 post fikri (başlık, konu, CTA)

{RICH_BRIEFING_GUIDE}"""

        try:
            text = llm.generate_text(SYSTEM_PROMPT, user_prompt)
            return text
        except Exception as exc:
            logger.exception("LLM çağrısı başarısız")
            # Fallback metin
            return (
                f"**Öne çıkan:** Sosyal medya profillerin {strategy} stratejiye "
                f"hazır. Bio'da CTA eksik ve haştag stratejisi gerekli.\n\n"
                f"Analiz: {len(profiles)} platform tarandi. Detaylar için "
                f"profil analizlerini kontrol et."
            )

    def _save_analyses(self, profiles: List[ProfileAnalysis]) -> None:
        """Profil analizlerini durum dosyasına kaydet."""
        STATE_DIR.mkdir(exist_ok=True)

        existing = []
        if PROFILES_FILE.exists():
            with open(PROFILES_FILE) as f:
                existing = json.load(f)

        # Yeni analizleri ekle (en sonuncu ver)
        for profile in profiles:
            # Aynı platform/handle'ı eski listeden sil
            existing = [
                p for p in existing
                if not (p.get("platform") == profile.platform and
                       p.get("handle") == profile.handle)
            ]
            existing.append(asdict(profile))

        # Son 10 analizi sakla
        existing = existing[-10:]

        with open(PROFILES_FILE, "w") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        logger.info(f"{len(profiles)} profil analizi kaydedildi")

    def batch_section(self) -> Optional[BatchSection]:
        """Batched call'a katıl."""
        if not llm.is_configured():
            return None

        instagram = setting(ENV_INSTAGRAM)
        twitter = setting(ENV_TWITTER)

        if not instagram and not twitter:
            return None

        handle = instagram or twitter
        strategy = setting(ENV_STRATEGY) or "professional"

        user_prompt = USER_PROMPT_TEMPLATE.format(
            platform="instagram" if instagram else "twitter",
            handle=handle,
            strategy=strategy
        )

        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
