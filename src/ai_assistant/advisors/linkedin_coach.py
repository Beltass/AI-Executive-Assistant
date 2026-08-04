"""LinkedIn İmaj Koçu — LinkedIn Profile & Content Management Advisor.

Türkçe linkedin-focused advisor that manages the user's professional image on
LinkedIn through:

1. **Profil Optimizasyonu** — LinkedIn profili taraması ve iyileştirme önerileri
2. **Günlük Post Üretimi** — Sector news + tech developments based daily posts
3. **Onay İş Akışı** — Draft posts stored in state, Slack approval menu
4. **Engagement İzleme** — Likes, comments, shares tracking
5. **İş Arayışı Desteği** — Company posting & recruiting activity detection

This advisor works in MOCK mode initially (no real LinkedIn API), but is
structured for easy real API integration later.

Configuration (via environment):
    LINKEDIN_ACCESS_TOKEN      OAuth token for LinkedIn API (optional, mock mode)
    LINKEDIN_PROFILE_URL       User's LinkedIn profile URL
    LINKEDIN_AUTO_PUBLISH      false for manual approval (default)
    LINKEDIN_APPROVAL_CHANNEL  Slack channel for post approvals
    LINKEDIN_SECTOR            Sector to monitor for job opportunities
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

# Configuration keys
ENV_ACCESS_TOKEN = "LINKEDIN_ACCESS_TOKEN"
ENV_PROFILE_URL = "LINKEDIN_PROFILE_URL"
ENV_AUTO_PUBLISH = "LINKEDIN_AUTO_PUBLISH"
ENV_APPROVAL_CHANNEL = "LINKEDIN_APPROVAL_CHANNEL"
ENV_SECTOR = "LINKEDIN_SECTOR"

# Default configuration values
DEFAULT_SECTOR = "yazılım & bulut teknolojileri"

# State file paths
STATE_DIR = Path(".assistant_state")
DRAFTS_FILE = STATE_DIR / "linkedin_drafts.json"
METRICS_FILE = STATE_DIR / "linkedin_metrics.json"
PROFILE_FILE = STATE_DIR / "linkedin_profile.json"

# System prompt
LINKEDIN_SYSTEM_PROMPT = """
Sen bir LinkedIn İmaj Koçusun. Türkçe, profesyonel ama insani bir ton kullan.

Görev:
1. Kullanıcının LinkedIn profilini optimize etmek
2. Sektör haberleri, teknoloji geliştirmeleri ve araştırma temelli günlük postlar oluşturmak
3. Personel fikirler, yorum ve eyleme çağrısı içeren postlar yazmak
4. Engagement izleme ve haftalık özet raporlar

Stil:
- Profesyonel ama insani (corporate expert commentary)
- 2-3 paragraf, araştırma temelli
- Sektör alakalı hashtag ve engagement-driving CTA
- Her post muhakkak kişisel perspektif ve değer sunmalı
"""

USER_PROMPT_TEMPLATE = """
Bugün için LinkedIn postları oluştur. Aşağıdaki sector news + tech developments
göz önüne alan 1-2 post hazırla:

## Sector News
{sector_news}

## Tech Developments
{tech_news}

Her post şunları içermeli:
- Başlık: kötü olmayı davet eden, kliğe çekmekten kaçınan
- Gövde: 2-3 paragraf araştırma/kişisel perspektif
- Hashtag: 3-5 sektörel, trend
- CTA: Engagement-driving soru veya davet

Çıktı JSON:
[
  {
    "headline": "...",
    "body": "...",
    "hashtags": ["..."],
    "cta": "..."
  }
]
"""


# =============================================================================
# DataClasses
# =============================================================================


@dataclass
class LinkedInPost:
    """A single LinkedIn post draft or published."""

    id: str
    date: str
    headline: str
    body: str
    hashtags: List[str]
    cta: str  # call-to-action
    draft: bool = True
    approved: bool = False
    posted_at: Optional[str] = None
    edited_by_user: Optional[str] = None
    performance: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> LinkedInPost:
        return cls(**data)


@dataclass
class LinkedInProfile:
    """Cached user's LinkedIn profile info."""

    profile_url: str
    headline: str
    about: str
    industry: str
    followers_count: int = 0
    last_updated: str = ""
    optimization_score: int = 0


@dataclass
class EngagementMetrics:
    """Daily engagement metrics."""

    date: str
    followers: int
    impressions: int
    engagements: int
    posts_published: int
    top_post: Optional[str] = None
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    engagement_rate: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> EngagementMetrics:
        return cls(**data)


@dataclass
class JobOpportunity:
    """Identified job opportunity from LinkedIn activity."""

    company_name: str
    industry: str
    posting_date: str
    opportunity_type: str  # "direct_posting", "leadership_change", "expansion", "product_launch"
    relevance_score: int  # 1-5
    description: str
    action_suggested: str


# =============================================================================
# LinkedIn Coach Advisor
# =============================================================================


class LinkedInCoach(Advisor):
    """LinkedIn İmaj Koçu — Professional image and content management.

    Key characteristics:
    - key: "linkedin_coach"
    - title: "LinkedIn İmaj Koçu"
    - Not an incremental_source (coaching/timeless, not feed-driven)
    - Not private (can be published to dashboard)
    - Batched LLM work (optional, for post generation)
    """

    key: str = "linkedin_coach"
    title: str = "LinkedIn İmaj Koçu"
    incremental_source: bool = False
    private: bool = False

    def __init__(self):
        """Initialize the LinkedIn Coach."""
        self._ensure_state_dir()
        self.access_token = setting(ENV_ACCESS_TOKEN, "")
        self.profile_url = setting(ENV_PROFILE_URL, "")
        self.auto_publish = setting(ENV_AUTO_PUBLISH, "false").lower() == "true"
        self.approval_channel = setting(ENV_APPROVAL_CHANNEL, "")
        self.sector = setting(ENV_SECTOR, DEFAULT_SECTOR)

    def _generate(self) -> Briefing:
        """Generate briefing with profile optimization and pending posts status."""
        if not self.profile_url:
            return self.skipped("LinkedIn profil URL'i yapılandırılmadı")

        try:
            # Load current profile and metrics
            profile = self._load_profile()
            pending_posts = self._get_pending_posts()
            recent_metrics = self._get_recent_metrics()

            # Generate briefing text
            sections = []

            # 1. Profile optimization status
            if profile:
                sections.append(self._format_profile_section(profile))

            # 2. Pending approvals
            if pending_posts:
                sections.append(
                    f"\n## 📋 Onay Bekleyen Postlar\n\n"
                    f"{len(pending_posts)} post yayınlanmayı bekliyor."
                )

            # 3. Recent engagement summary
            if recent_metrics:
                sections.append(self._format_metrics_section(recent_metrics))

            # 4. Job opportunities detected
            opportunities = self._identify_job_opportunities()
            if opportunities:
                sections.append(self._format_opportunities_section(opportunities))

            briefing_text = "\n".join(sections) if sections else "LinkedIn İmaj Koçu hazır."
            return self.ok(briefing_text)

        except Exception as exc:
            logger.exception("LinkedIn Coach error: %s", exc)
            return self.failed(f"LinkedIn Coach hatası: {exc}")

    def batch_section(self) -> Optional[BatchSection]:
        """Return optional LLM work for post generation.

        Only contributes to batch if user has LinkedIn configured and we have
        sector news to work with.
        """
        if not self.profile_url or not self.access_token:
            return None

        # In a real implementation, fetch sector news here
        # For now, return a section only if explicitly configured for LLM work
        sector_news = "Yapay zekâ ve bulut teknolojisinde yenilikler devam ediyor."
        tech_news = "Yeni LLM modelleri ve open-source araçlar pazarı hızla büyüyor."

        user_prompt = USER_PROMPT_TEMPLATE.format(
            sector_news=sector_news, tech_news=tech_news
        )

        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=LINKEDIN_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

    # -- State file management -----------------------------------------------

    def _ensure_state_dir(self) -> None:
        """Create .assistant_state directory if it doesn't exist."""
        STATE_DIR.mkdir(exist_ok=True)

    def _load_drafts(self) -> List[LinkedInPost]:
        """Load all draft posts from state file."""
        try:
            if DRAFTS_FILE.exists():
                with open(DRAFTS_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    return [LinkedInPost.from_dict(post) for post in data.get("posts", [])]
        except Exception as exc:
            logger.warning("LinkedIn drafts dosyası okunamadı: %s", exc)
        return []

    def _save_drafts(self, posts: List[LinkedInPost]) -> None:
        """Save draft posts to state file."""
        try:
            with open(DRAFTS_FILE, "w", encoding="utf-8") as fh:
                json.dump({"posts": [p.to_dict() for p in posts]}, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("LinkedIn drafts dosyası yazılamadı: %s", exc)

    def _load_profile(self) -> Optional[LinkedInProfile]:
        """Load cached profile info."""
        try:
            if PROFILE_FILE.exists():
                with open(PROFILE_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    return LinkedInProfile(**data)
        except Exception as exc:
            logger.warning("LinkedIn profil dosyası okunamadı: %s", exc)
        return None

    def _save_profile(self, profile: LinkedInProfile) -> None:
        """Save profile info."""
        try:
            with open(PROFILE_FILE, "w", encoding="utf-8") as fh:
                json.dump(asdict(profile), fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("LinkedIn profil dosyası yazılamadı: %s", exc)

    def _load_metrics(self) -> List[EngagementMetrics]:
        """Load all engagement metrics."""
        try:
            if METRICS_FILE.exists():
                with open(METRICS_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    return [EngagementMetrics.from_dict(m) for m in data.get("metrics", [])]
        except Exception as exc:
            logger.warning("LinkedIn metrics dosyası okunamadı: %s", exc)
        return []

    def _save_metrics(self, metrics: List[EngagementMetrics]) -> None:
        """Save engagement metrics."""
        try:
            with open(METRICS_FILE, "w", encoding="utf-8") as fh:
                json.dump({"metrics": [m.to_dict() for m in metrics]}, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("LinkedIn metrics dosyası yazılamadı: %s", exc)

    # -- Post Management -------------------------------------------------------

    def _get_pending_posts(self) -> List[LinkedInPost]:
        """Get posts awaiting approval."""
        all_posts = self._load_drafts()
        return [p for p in all_posts if p.draft and not p.posted_at]

    def generate_daily_posts(self, sector_news: str = "", tech_news: str = "") -> List[LinkedInPost]:
        """Generate 1-2 daily posts from sector/tech news.

        Args:
            sector_news: Comma-separated or newline-separated sector news items
            tech_news: Comma-separated or newline-separated tech news items

        Returns:
            List of generated LinkedInPost objects (as drafts)
        """
        if not sector_news or not tech_news:
            sector_news = sector_news or self._get_mock_sector_news()
            tech_news = tech_news or self._get_mock_tech_news()

        try:
            # In a real implementation, this would call LLM
            # For now, generate mock posts
            posts = self._generate_mock_posts(sector_news, tech_news)

            # Save as drafts
            existing = self._load_drafts()
            all_posts = existing + posts
            self._save_drafts(all_posts)

            return posts
        except Exception as exc:
            logger.error("Post üretimi hatası: %s", exc)
            return []

    def mark_post_approved(self, post_id: str) -> bool:
        """Mark a post as approved (ready to publish).

        Args:
            post_id: ID of the post to approve

        Returns:
            True if success, False otherwise
        """
        try:
            posts = self._load_drafts()
            for post in posts:
                if post.id == post_id:
                    post.approved = True
                    self._save_drafts(posts)
                    logger.info("Post %s onaylandı", post_id)
                    return True
            logger.warning("Post %s bulunamadı", post_id)
            return False
        except Exception as exc:
            logger.error("Post onay hatası: %s", exc)
            return False

    def mark_post_rejected(self, post_id: str) -> bool:
        """Reject and delete a draft post.

        Args:
            post_id: ID of the post to reject

        Returns:
            True if success, False otherwise
        """
        try:
            posts = self._load_drafts()
            filtered = [p for p in posts if p.id != post_id]
            if len(filtered) < len(posts):
                self._save_drafts(filtered)
                logger.info("Post %s reddedildi", post_id)
                return True
            return False
        except Exception as exc:
            logger.error("Post reddetme hatası: %s", exc)
            return False

    def edit_post(self, post_id: str, headline: str = "", body: str = "", hashtags: List[str] = None, cta: str = "") -> bool:
        """Edit a draft post.

        Args:
            post_id: ID of the post to edit
            headline: New headline (if provided)
            body: New body (if provided)
            hashtags: New hashtags (if provided)
            cta: New call-to-action (if provided)

        Returns:
            True if success, False otherwise
        """
        try:
            posts = self._load_drafts()
            for post in posts:
                if post.id == post_id and post.draft:
                    if headline:
                        post.headline = headline
                    if body:
                        post.body = body
                    if hashtags:
                        post.hashtags = hashtags
                    if cta:
                        post.cta = cta
                    post.edited_by_user = datetime.utcnow().isoformat()
                    self._save_drafts(posts)
                    logger.info("Post %s düzenlendi", post_id)
                    return True
            return False
        except Exception as exc:
            logger.error("Post düzenleme hatası: %s", exc)
            return False

    def publish_post(self, post_id: str) -> bool:
        """Publish an approved post (mock implementation).

        In a real implementation, this would call LinkedIn's Share API.
        For now, it just marks it as posted in local storage.

        Args:
            post_id: ID of the post to publish

        Returns:
            True if success, False otherwise
        """
        try:
            posts = self._load_drafts()
            for post in posts:
                if post.id == post_id and post.approved:
                    post.draft = False
                    post.posted_at = datetime.utcnow().isoformat()
                    self._save_drafts(posts)
                    logger.info("Post %s yayınlandı", post_id)
                    return True
            logger.warning("Post %s onaylı değil", post_id)
            return False
        except Exception as exc:
            logger.error("Post yayınlama hatası: %s", exc)
            return False

    # -- Profile Management ---------------------------------------------------

    def generate_profile_suggestions(self) -> Dict[str, str]:
        """Generate profile optimization suggestions.

        Returns:
            Dict with keys: headline, about, photo_tips, skills_order, etc.
        """
        try:
            profile = self._load_profile()
            if not profile:
                return {
                    "status": "profil_bilgileri_yüklenemedi",
                    "suggestion": "Lütfen LinkedIn profilini bağla",
                }

            suggestions = {
                "headline": self._suggest_headline(profile),
                "about": self._suggest_about(profile),
                "photo_tips": "Profesyonel, açık arka planlı bir fotoğraf kullan",
                "skills_order": "En çok kullanılan beceriler başa gelsin",
                "optimization_score": str(profile.optimization_score),
            }
            return suggestions
        except Exception as exc:
            logger.error("Profil önerileri hatası: %s", exc)
            return {"status": "error", "message": str(exc)}

    def _suggest_headline(self, profile: LinkedInProfile) -> str:
        """Generate headline suggestions."""
        return f"Önerilen başlık: {profile.headline} | Teknoloji Lider & Danışman"

    def _suggest_about(self, profile: LinkedInProfile) -> str:
        """Generate about section suggestions."""
        return "Hakkında bölümü: En önemli başarılarını, uzmanlık alanlarını ve vizyonunu anlat. Kişisel ve profesyonel."

    # -- Engagement Tracking -------------------------------------------------

    def track_engagement(self) -> EngagementMetrics:
        """Track today's engagement metrics.

        In a real implementation, this would call LinkedIn's Analytics API.
        For now, returns mock data.

        Returns:
            EngagementMetrics for today
        """
        try:
            today = datetime.utcnow().date().isoformat()
            existing_metrics = self._load_metrics()

            # Check if we already have today's metrics
            for m in existing_metrics:
                if m.date == today:
                    return m

            # Generate mock metrics for today
            metrics = EngagementMetrics(
                date=today,
                followers=1250 + len(existing_metrics) * 5,
                impressions=450 + len(existing_metrics) * 20,
                engagements=85 + len(existing_metrics) * 3,
                posts_published=len([p for p in self._load_drafts() if p.posted_at and p.date == today]),
                likes_count=60,
                comments_count=15,
                shares_count=10,
                engagement_rate=0.189,
            )

            # Save metrics
            existing_metrics.append(metrics)
            self._save_metrics(existing_metrics)

            return metrics
        except Exception as exc:
            logger.error("Engagement izleme hatası: %s", exc)
            return EngagementMetrics(
                date=datetime.utcnow().date().isoformat(),
                followers=0,
                impressions=0,
                engagements=0,
                posts_published=0,
            )

    def generate_weekly_summary(self) -> Dict[str, any]:
        """Generate weekly engagement summary and recommendations.

        Returns:
            Dict with weekly stats, top posts, and recommendations
        """
        try:
            metrics = self._load_metrics()
            today = datetime.utcnow().date()
            week_ago = today - timedelta(days=7)

            weekly_metrics = [m for m in metrics if datetime.fromisoformat(m.date).date() >= week_ago]

            if not weekly_metrics:
                return {"status": "no_data", "message": "Haftalık veri yok"}

            total_followers = sum(m.followers for m in weekly_metrics) / len(weekly_metrics)
            total_engagements = sum(m.engagements for m in weekly_metrics)
            total_posts = sum(m.posts_published for m in weekly_metrics)
            avg_engagement_rate = sum(m.engagement_rate for m in weekly_metrics) / len(weekly_metrics)

            return {
                "period": f"{week_ago} - {today}",
                "avg_followers": int(total_followers),
                "total_engagements": total_engagements,
                "total_posts": total_posts,
                "avg_engagement_rate": round(avg_engagement_rate, 3),
                "recommendation": self._generate_engagement_recommendation(avg_engagement_rate),
            }
        except Exception as exc:
            logger.error("Haftalık özet hatası: %s", exc)
            return {"status": "error", "message": str(exc)}

    def _generate_engagement_recommendation(self, engagement_rate: float) -> str:
        """Generate recommendation based on engagement rate."""
        if engagement_rate > 0.2:
            return "Harika! Engagement oranın çok yüksek. Bu içerik tarzını devam ettir."
        elif engagement_rate > 0.1:
            return "İyi performans. Daha fazla konuşmaya davet eden postlar dene."
        else:
            return "Engagement oranı düşük. Daha kişisel ve soru içeren postlar yaz."

    # -- Job Opportunity Detection -------------------------------------------

    def identify_job_opportunities(self) -> List[JobOpportunity]:
        """Identify job opportunities from LinkedIn activity.

        In real implementation, would parse LinkedIn Company Pages activity,
        job postings, leadership changes, etc.

        Returns:
            List of JobOpportunity objects
        """
        try:
            # Mock opportunities
            opportunities = [
                JobOpportunity(
                    company_name="TechCorp Turkey",
                    industry="Yazılım & Bulut",
                    posting_date=datetime.utcnow().date().isoformat(),
                    opportunity_type="direct_posting",
                    relevance_score=5,
                    description="Yapay Zeka Mühendisi pozisyonu açılmış",
                    action_suggested="Şirketin CEO'sunun son postlarını oku ve takılı kal",
                ),
            ]
            return opportunities
        except Exception as exc:
            logger.error("İş fırsat tanımlama hatası: %s", exc)
            return []

    def _identify_job_opportunities(self) -> List[JobOpportunity]:
        """Wrapper for identify_job_opportunities for internal use."""
        return self.identify_job_opportunities()

    # -- Formatting helpers for briefing output ---------------------

    def _format_profile_section(self, profile: LinkedInProfile) -> str:
        """Format profile optimization section."""
        score = profile.optimization_score
        score_bar = "█" * (score // 10) + "░" * (10 - score // 10)
        return (
            f"## 👤 LinkedIn Profil Optimizasyon\n\n"
            f"Optimizasyon Puanı: {score}/100 [{score_bar}]\n\n"
            f"- **Başlık:** {profile.headline}\n"
            f"- **Takipçi:** {profile.followers_count:,}\n"
            f"- **Sektör:** {profile.industry}\n"
        )

    def _format_metrics_section(self, metrics: List[EngagementMetrics]) -> str:
        """Format engagement metrics section."""
        if not metrics:
            return ""

        latest = metrics[-1]
        return (
            f"## 📊 Engagement Metrikleri\n\n"
            f"- **Takipçi:** {latest.followers:,}\n"
            f"- **İzlenimler:** {latest.impressions:,}\n"
            f"- **Etkileşim:** {latest.engagements}\n"
            f"- **Engagement Oranı:** {latest.engagement_rate:.1%}\n"
        )

    def _format_opportunities_section(self, opportunities: List[JobOpportunity]) -> str:
        """Format job opportunities section."""
        if not opportunities:
            return ""

        lines = ["## 💼 İş Fırsatları Algılandı\n"]
        for opp in opportunities[:3]:  # Top 3
            lines.append(
                f"- **{opp.company_name}** ({opp.relevance_score}/5 alakalılık)\n"
                f"  {opp.description}\n"
            )
        return "\n".join(lines)

    # -- Mock data generators (for testing without API) ---

    def _get_mock_sector_news(self) -> str:
        """Generate mock sector news."""
        return (
            "1. Yapay zekâ ile müşteri hizmetleri otomasyonu hızlanıyor\n"
            "2. Bulut maliyetleri optimizasyonu yeni trend\n"
            "3. Fintech şirketleri yeni yatırım turu açıyor"
        )

    def _get_mock_tech_news(self) -> str:
        """Generate mock tech news."""
        return (
            "1. Yeni açık kaynak LLM modelleri yayınlandı\n"
            "2. Vektör veritabanları enterprise çözümlerde ön plana çıktı\n"
            "3. Multi-agent AI sistemleri üretime geçiyor"
        )

    def _generate_mock_posts(self, sector_news: str, tech_news: str) -> List[LinkedInPost]:
        """Generate mock posts from news."""
        from uuid import uuid4

        today = datetime.utcnow().date().isoformat()

        posts = [
            LinkedInPost(
                id=str(uuid4()),
                date=today,
                headline="Yapay Zeka ile Müşteri Hizmetleri Nasıl Dönüşüyor?",
                body=(
                    "Geçtiğimiz ay müşteri hizmetleri sektöründe yapay zekâ "
                    "uygulamalarında dikkat çekici artış yaşandı. Şirketler artık "
                    "otomasyonla insan temsilcilerin kombinasyonuna yatırım yapıyor.\n\n"
                    "Ama dikkat: Teknoloji altyapısı olan şirketler değil, müşteri "
                    "deneyimini merkez alan şirketler öne çıkıyor. Siz ne düşünüyorsunuz?"
                ),
                hashtags=["#YapayZeka", "#MüşterilerDeneyimi", "#İnovasyon"],
                cta="Sizin şirketinizde hangi müşteri hizmetleri görevleri başka türlü otomatize edilebilir? Aşağıya yazın.",
                draft=True,
                approved=False,
            ),
            LinkedInPost(
                id=str(uuid4()),
                date=today,
                headline="Bulut Maliyeti Kontrolü Yeni Başlıyor",
                body=(
                    "Bulut hizmetleri geçen on yılda işleri dönüştürdü. Ama bugün "
                    "başka bir sorun ortaya çıktı: kimse tam olarak ne kadar para "
                    "harcadığını bilmiyor.\n\n"
                    "Bu yılın ilk yarısında kuruluşlar bulut maliyet optimizasyonunda "
                    "ciddi yatırım yaptı. Eğer siz de bu yolda ilerliyorsanız, hangi "
                    "araçları/stratejileri denediyseniz merak ediyorum."
                ),
                hashtags=["#Bulut", "#FinOps", "#MaliyetOptimizsyon"],
                cta="Bulut maliyetlerinizi nasıl kontrol ediyor veya tasarruf sağlıyorsunuz? Deneyimlerinizi paylaşın.",
                draft=True,
                approved=False,
            ),
        ]

        return posts

    def _get_recent_metrics(self) -> Optional[List[EngagementMetrics]]:
        """Get last 7 days of metrics."""
        try:
            all_metrics = self._load_metrics()
            today = datetime.utcnow().date()
            week_ago = today - timedelta(days=7)
            return [m for m in all_metrics if datetime.fromisoformat(m.date).date() >= week_ago]
        except Exception as exc:
            logger.warning("Son metrikler alınamadı: %s", exc)
            return None


__all__ = [
    "LinkedInCoach",
    "LinkedInPost",
    "LinkedInProfile",
    "EngagementMetrics",
    "JobOpportunity",
]
