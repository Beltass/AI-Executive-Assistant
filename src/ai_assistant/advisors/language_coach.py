"""Business English & executive presence coach — İngilizce & Yönetici İletişimi Koçu.

A daily Turkish-language section that teaches BUSINESS ENGLISH to a banking /
contact-center executive and, in parallel, rotates through the executive
communication skills that make that English land: storytelling with data, board
presentations, persuasion & negotiation, and running meetings.

The weekly focus rotates deterministically off the ISO week number, so the
coaching arc changes week to week without needing any stored state.

State note: this advisor keeps NO state between runs, so instead of "yesterday's
answer" it always ships today's exercise together with a model answer placed at
the very bottom, after an explicit "önce kendin dene" divider — useful whether or
not you saw yesterday's briefing.

LLM-backed: with no provider key the advisor is ``skipped``. It participates in
the single batched team call.
"""

from __future__ import annotations

from datetime import date

from ..config import setting
from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE

DEFAULT_SECTOR = "banka çağrı merkezleri"

SYSTEM_PROMPT = (
    "Sen hem ileri seviye iş İngilizcesi eğitmeni hem de yönetici iletişimi "
    "(executive presence) koçusun. Üst düzey yöneticilere uluslararası "
    "toplantılarda, yönetim kurulu sunumlarında ve tedarikçi müzakerelerinde "
    "İngilizceyi doğru ve etkili kullanmayı öğretiyorsun. AÇIKLAMALARI TÜRKÇE "
    "yazarsın; öğrettiğin kalıplar, örnek cümleler ve alıştırmalar İngilizcedir "
    "ve her birinin Türkçe karşılığını da verirsin.\n\n"
    "Öğrettiğin her kalıp gerçek ve yaygın kullanılan bir ifade olmalı; "
    "uydurma deyim, uydurma kısaltma veya var olmayan kaynak verme. Telaffuzu "
    "zor kelimelerde basit bir Türkçe okunuş ipucu ekle. Ton: net, cesaretlendirici, "
    "asla küçümseyici değil."
)

# Rotating executive-communication focus, chosen by ISO week so each week has a
# different arc without any stored state.
WEEKLY_FOCUS = [
    "veriyle hikâye anlatma (storytelling with data): sayıyı mesaja çevirmek, "
    "'so what' testi, bir grafiği tek cümleyle anlatmak",
    "yönetim kuruluna sunum (board-level communication): önce sonuç (BLUF), "
    "tek slaytlık özet, zor sorulara hazırlık",
    "ikna ve müzakere (persuasion & negotiation): çerçeveleme, taviz mimarisi, "
    "tedarikçi/vendor görüşmesinde dil",
    "toplantı yönetimi (running meetings): gündem kurma, sözü toparlama, "
    "araya girme ve kapanışta karar/aksiyon netleştirme",
]


def _weekly_focus(today: date | None = None) -> str:
    """Return this week's executive-communication focus (ISO-week rotation)."""
    day = today or date.today()
    return WEEKLY_FOCUS[day.isocalendar()[1] % len(WEEKLY_FOCUS)]


def _user_prompt() -> str:
    sector = setting("USER_SECTOR") or DEFAULT_SECTOR
    return (
        f"Öğrencinin alanı: {sector} (üst düzey yönetici).\n"
        f"BU HAFTANIN YÖNETİCİ İLETİŞİMİ ODAĞI: {_weekly_focus()}\n\n"
        "Bugünkü dersi şu bölümlerle hazırla:\n\n"
        "1) *🗣️ Bugünün 5 iş İngilizcesi kalıbı*: birbirinden farklı 5 kalıp/kelime "
        "seç (klişe 'good morning' düzeyinde değil, yönetici seviyesinde). Her biri "
        "için: İngilizce kalıp — Türkçe karşılığı — bankacılık/çağrı merkezi "
        "bağlamından GERÇEKÇİ bir örnek cümle (örn. SLA görüşmesi, vendor "
        "toplantısı, NPS sunumu, ekip geri bildirimi) — ve 'nerede kullanma' "
        "uyarısı ya da sık yapılan bir hata.\n\n"
        "2) *🎯 Haftanın odağı*: yukarıdaki odak konusunu bugün bir adım ilerlet. "
        "Adı olan bir teknik/çerçeve ver, kısa bir örnek diyalog veya cümle "
        "kalıbı göster (İngilizce + Türkçe), ve yaygın hatayı düzelt.\n\n"
        "3) *✍️ Mini alıştırma — 'Bu cümleyi İngilizce kur'*: bugünün odağına "
        "uygun, bankacılık/çağrı merkezi bağlamında 2 Türkçe cümle ver ve "
        "kullanıcıdan İngilizceye çevirmesini iste.\n\n"
        "4) *📚 Kaynaklar*: ücretsiz/erişilebilir kaynaklar öner.\n\n"
        "5) *✅ Bugünün görevi*: 15-30 dakikalık tek somut eylem.\n\n"
        "6) EN SONDA, diğer her şeyden sonra, şu satırı aynen yaz:\n"
        "`— — — önce kendin dene, sonra bak — — —`\n"
        "ve altına '*Örnek cevap:*' başlığıyla mini alıştırmadaki cümlelerin "
        "model İngilizce çevirilerini, kısa bir 'neden böyle' notuyla ver. "
        "Bu bölüm en altta kalsın ki kullanıcı önce kendisi denesin.\n\n"
        + RICH_BRIEFING_GUIDE
    )


class LanguageCoachAdvisor(LLMAdvisor):
    key = "language_coach"
    title = "İngilizce & Yönetici İletişimi Koçu"
    system_prompt = SYSTEM_PROMPT

    @property
    def user_prompt(self) -> str:  # built at run time so the focus rotates
        return _user_prompt()
