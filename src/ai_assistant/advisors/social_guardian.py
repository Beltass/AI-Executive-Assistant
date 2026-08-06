"""İtibar Muhafızı — marka zararı ve kriz ERKEN uyarısı.

İki komşusu var ve ikisinin de işini yapmaz:

* ``social_media_coach`` İÇERİK koçudur: profil, post fikri, etkileşim. Onun
  sorusu "ne paylaşayım".
* ``complaint_radar`` ŞİKÂYET AKIŞINI okur ve pazar sentimentine çevirir. Onun
  sorusu "müşteri neyden yakınıyor, sektör nereye gidiyor".

Bu bölümün sorusu ise tek başına şudur: **bu, itibarımıza zarar verir mi ve ne
kadar hızlı cevap vermeliyiz?** Konu hacim ya da trend değil, ZARAR ve HIZDIR.
Tek bir gönderi pazarı hiç etkilemeden bir markayı yakabilir; bu bölüm o tek
gönderiyi arar.

NE YAPAR
--------
1. İzleme akışlarını çeker (:data:`FEEDS`) — :mod:`ai_assistant.advisors._rss`
   ile; yeni bir istemci YOKTUR.
2. Başlıkları :mod:`ai_assistant.memory` defterinden geçirir: bir kez
   konuşulan başlık ikinci kez uyarı üretmez.
3. Her başlığa yerel bir ŞİDDET ipucu verir (:data:`RISK_TERMS`): hukuki
   tehdit, veri sızıntısı, dolandırıcılık, yaygınlaşma, düzenleyici. Terim
   listesi burada yazılıdır — modelin uyduracağı bir şey değil, böylece aynı
   sinyal iki gün üst üste aynı adla anılır.
4. Toplanan GERÇEK başlıkları ekibin ortak toplu çağrısına verir; model
   yalnızca bunları sınıflar ve cevap penceresi önerir.

TETİKLEYİCİ: ``data_triggered``. ``data_owner`` alanı ``reputation_feeds``;
akış değişmediyse istem de değişmez ve model hiç çağrılmaz.

TEMİZ DEVREDİLME: akış tanımlı değilse, yeni başlık yoksa ya da model anahtarı
yoksa Türkçe bir açıklamayla ``skipped`` döner. Model yokken ASLA uydurma bir
kriz değerlendirmesi üretmez — yanlış alarm, sessizlikten pahalıdır.

Configuration (via environment):
    SOCIAL_GUARDIAN_RSS_URL        Ana itibar izleme akışı (marka adı araması).
    SOCIAL_GUARDIAN_ALERT_RSS_URL  İkinci akış: düzenleyici/hukuki/kriz kaynağı.
    SOCIAL_GUARDIAN_BRANDS         İzlenen kendi marka/kişi adları (virgüllü).
    SOCIAL_GUARDIAN_MAX_ITEMS      Bir koşuda en fazla kaç başlık (varsayılan 8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ..memory import filter_new_items
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

#: ``(ayar adı, akış etiketi, madde sınırı)`` — etiket modele de gösterilir,
#: böylece bir başlığın hangi masadan geldiği kaybolmaz.
FEEDS: Tuple[Tuple[str, str, int], ...] = (
    ("SOCIAL_GUARDIAN_RSS_URL", "İtibar izleme akışı", 10),
    ("SOCIAL_GUARDIAN_ALERT_RSS_URL", "Düzenleyici / kriz akışı", 6),
)

BRANDS_ENV = "SOCIAL_GUARDIAN_BRANDS"
MAX_ITEMS_ENV = "SOCIAL_GUARDIAN_MAX_ITEMS"

#: Bir koşuda modele taşınacak en fazla başlık. Kriz değerlendirmesi derinlik
#: ister; uzun liste hem token yakar hem önceliği görünmez kılar.
DEFAULT_MAX_ITEMS = 8

#: Yerel şiddet ipuçları: ``(etiket, tetikleyen terimler)``. Sıra ÖNEMLİDİR —
#: ilk eşleşen etiket kazanır, en ağır olan başta durur.
RISK_TERMS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "hukuki / düzenleyici",
        ("dava", "soruşturma", "ceza", "mahkeme", "düzenleme", "yaptırım", "bddk"),
    ),
    (
        "veri / güvenlik",
        ("sızıntı", "veri ihlali", "hack", "siber", "dolandırıcılık", "phishing"),
    ),
    (
        "yaygınlaşma",
        ("viral", "gündem oldu", "boykot", "tepki çekti", "linç", "trend"),
    ),
    (
        "hizmet kesintisi",
        ("kesinti", "erişilemiyor", "çöktü", "arıza", "gecikme"),
    ),
)

#: Hiçbir terim eşleşmediğinde kullanılan etiket. "Bilmiyorum" demek,
#: uydurulmuş bir şiddet derecesinden iyidir.
UNCLASSIFIED = "sınıflanmadı"

NO_FEED_HELP = (
    "missing env var(s): SOCIAL_GUARDIAN_RSS_URL — itibar izleme için "
    "okunacak bir akış tanımlı değil. Marka adınızı arayan bir haber/sosyal "
    "arama RSS adresi (ve istenirse SOCIAL_GUARDIAN_ALERT_RSS_URL) "
    "tanımlandığında bu bölüm kriz erken uyarısı üretir."
)

NO_NEW_ITEMS = (
    "yeni itibar sinyali yok: izlenen akışlarda daha önce anlatılmamış bir "
    "başlık bulunamadı. Değerlendirilecek bir şey olmadığı için model "
    "çağrılmadı."
)

SKIP_NO_LLM = "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"

SYSTEM_PROMPT = (
    "Sen bir kurumun itibar muhafızısın. Türkçe yazıyorsun. İşin DAR ve "
    "nettir: eline gelen başlıklardan İTİBAR ZARARI riskini ölçmek ve cevap "
    "penceresini söylemek.\n\n"
    "KAPSAMIN NE DEĞİL: içerik/post koçluğu ('şunu paylaş') ve genel pazar "
    "sentimenti analizi SENİN İŞİN DEĞİL — ikisini de başka danışmanlar "
    "yapıyor. Sen 'ne paylaşayım' demezsin, 'bu bize zarar verir mi, ne kadar "
    "hızlı ve hangi tonda karşılık verilmeli' dersin.\n\n"
    "ÖLÇEĞİN: her sinyal için şiddet (düşük / orta / yüksek), yayılma "
    "ihtimali ve CEVAP PENCERESİ (şimdi / bugün / bu hafta / izle). Şiddeti "
    "abartma: her başlık kriz değildir ve yanlış alarm, gerçek alarmın "
    "güvenilirliğini yer.\n\n"
    "SESİN: soğukkanlı, savunmacı değil. Suçlamaya girme, olguyu ve seçenekleri "
    "koy.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: yalnızca sana verilen başlıkları kullan. "
    "Başlığın İÇERİĞİNİ okumadın; başlıktan çıkmayan bir iddiayı, sayıyı ya da "
    "olayı ICAT ETME ve emin olmadığın yorumu '(başlığa göre, doğrulayın)' "
    "diye işaretle. Hiçbir başlık ciddi değilse bunu açıkça söyle."
)

CAVEAT = (
    "📌 İtibar notu: Buradaki değerlendirme yalnızca BAŞLIKLARDAN "
    "çıkarılmıştır; içerik okunmamıştır ve bir kriz teşhisi değildir.\n"
    "🧯 Kamuya açık bir açıklama yapmadan önce hukuk ve iletişim birimine "
    "danışın; hızlı cevap her zaman doğru cevap değildir.\n"
    "🔎 Bağlantıları açılışta doğrulayın; başlıklar zamanla yer değiştirebilir."
)


def _int_setting(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def brands() -> List[str]:
    """İzlenen kendi marka/kişi adları; tanımsızsa boş liste."""
    raw = setting(BRANDS_ENV) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def classify(title: str) -> str:
    """Başlığa yerel bir şiddet etiketi verir; eşleşme yoksa 'sınıflanmadı'.

    Sınıflandırma modele bırakılmaz, çünkü aynı sinyalin iki gün üst üste
    aynı adla anılması gerekir. Model etiketi yorumlar, koymaz.
    """
    lowered = str(title or "").lower()
    for label, terms in RISK_TERMS:
        if any(term in lowered for term in terms):
            return label
    return UNCLASSIFIED


@dataclass
class Signal:
    """Tek bir izleme başlığı ve yerel sınıfı."""

    item: FeedItem
    label: str
    source: str = ""

    def describe(self) -> str:
        line = f"- [{self.label}] {self.item.title}"
        if self.item.link:
            line += f" ({self.item.link})"
        return line


class SocialGuardianAdvisor(Advisor):
    """İtibar zararı riskini ölçer ve cevap penceresini söyler."""

    key = "social_guardian"
    title = "İtibar Muhafızı (Kriz Erken Uyarısı)"
    #: Kamuya açık başlıkları özetler; panoya yazılabilir.
    private = False
    #: Akış yeni başlık üretir, yani artımlı koşularda da konuşabilir.
    incremental_source = True

    def __init__(self) -> None:
        self._signals: List[Signal] = []
        self._fetched = False

    # -- the run ---------------------------------------------------------
    def _generate(self) -> Briefing:
        if not self._configured():
            return self.skipped(NO_FEED_HELP)

        signals = self._fetch()
        if not signals:
            return self.skipped(NO_NEW_ITEMS)

        if not llm.is_configured():
            # Şiddet değerlendirmesini model yazar. Model yoksa "kriz var/yok"
            # hükmünü uydurmak yanlış alarmdan da beter olur.
            return self.skipped(SKIP_NO_LLM)

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")
        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not self._configured() or not llm.is_configured():
            return None
        if not self._fetch():
            return None
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        return self.ok(f"{text.strip()}\n\n{CAVEAT}")

    # -- deduplication ---------------------------------------------------
    def new_finding_count(self) -> int:
        return len(self._fetch())

    # -- gathering -------------------------------------------------------
    @staticmethod
    def _configured() -> bool:
        return any(setting(name) for name, _label, _limit in FEEDS)

    def _fetch(self) -> List[Signal]:
        """Akışları bir kez çeker; yalnızca DAHA ÖNCE anlatılmamışları tutar.

        Ölü bir besleme bölümü düşürmez: itibar izleme zenginleştirmedir, bir
        ağ hatası koşuyu kaybettirmemelidir.
        """
        if self._fetched:
            return self._signals
        self._fetched = True

        pool: List[FeedItem] = []
        sources = {}
        seen = set()
        for name, label, limit in FEEDS:
            url = setting(name)
            if not url:
                continue
            try:
                fetched = fetch_feed_items(url, limit=limit)
            except Exception:
                continue
            for item in fetched:
                if item.title in seen:
                    continue  # aynı haber iki akıştan geldiyse bir kez sayılır
                seen.add(item.title)
                sources[item.title] = label
                pool.append(item)

        fresh = filter_new_items(self.key, pool)
        limit = _int_setting(MAX_ITEMS_ENV, DEFAULT_MAX_ITEMS)
        self._signals = [
            Signal(item=item, label=classify(item.title), source=sources.get(item.title, ""))
            for item in fresh[:limit]
        ]
        return self._signals

    # -- the prompt ------------------------------------------------------
    @staticmethod
    def _format(signals: Sequence[Signal]) -> str:
        return "\n".join(signal.describe() for signal in signals)

    def _context(self) -> str:
        watched = brands()
        if watched:
            return (
                "İZLENEN KENDİ ADLAR: "
                + ", ".join(watched)
                + ". Bir başlık bu adlardan birini içermiyorsa 'bizimle "
                "doğrudan ilgili değil' diye işaretle ve şiddeti düşür."
            )
        return (
            f"İzlenen kendi marka/kişi adları TANIMLI DEĞİL ({BRANDS_ENV}). "
            "Hangi başlığın doğrudan kullanıcıyla ilgili olduğunu BİLMİYORSUN; "
            "bunu tek cümleyle söyle ve değerlendirmeyi genel itibar riski "
            "olarak yap."
        )

    def _user_prompt(self) -> str:
        labels = ", ".join(label for label, _terms in RISK_TERMS)
        return (
            "Aşağıdaki başlıklar izleme akışlarına YENİ düştü. Her biri için "
            "itibar riskini değerlendir. Blokları bu sırayla ver:\n\n"
            "*🚦 Risk tablosu*: her başlık için tek satır — şiddet (düşük/orta/"
            "yüksek), yayılma ihtimali ve cevap penceresi (şimdi / bugün / bu "
            "hafta / izle). Köşeli parantez içindeki yerel etiketi kullan ama "
            "gerekiyorsa gerekçesiyle değiştir.\n\n"
            "*🔥 Bugünün tek yangını*: en yüksek riskli sinyal hangisi ve "
            "NEDEN? Yayılırsa ne olur, yayılmazsa ne olur — ikisini de yaz. "
            "Hiçbiri ciddi değilse 'bugün yangın yok' de, zorlama.\n\n"
            "*🗣️ Cevap duruşu*: en riskli sinyal için üç seçenek — sessiz "
            "kalmak, kısa bir açıklama, tam açıklama. Her seçeneğin maliyetini "
            "tek cümleyle yaz ve birini ÖNER.\n\n"
            "*🧾 Hazır cümle*: gerekirse kullanılacak 2-3 cümlelik bir taslak "
            "açıklama. Söz verilmemiş bir şey taahhüt etme; rakam kullanma.\n\n"
            "*👀 İzleme listesi*: önümüzdeki günlerde hangi işaret görülürse "
            "durum tırmanmış sayılır? En fazla 3 madde.\n\n"
            "İçerik/post koçluğu ve genel pazar trendi analizi YAZMA — onlar "
            "başka danışmanların bölümünde.\n\n"
            + RICH_BRIEFING_GUIDE
            + f"\n\nYEREL ETİKETLER (bu listeden gelir): {labels}, "
            f"{UNCLASSIFIED}.\n"
            + self._context()
            + "\n\nBAŞLIKLAR (yalnızca aşağıdakini kullan; içeriklerini "
            "okumadın):\n"
            + self._format(self._signals)
        )


__all__ = [
    "BRANDS_ENV",
    "CAVEAT",
    "DEFAULT_MAX_ITEMS",
    "FEEDS",
    "MAX_ITEMS_ENV",
    "NO_FEED_HELP",
    "NO_NEW_ITEMS",
    "RISK_TERMS",
    "SKIP_NO_LLM",
    "SYSTEM_PROMPT",
    "Signal",
    "SocialGuardianAdvisor",
    "UNCLASSIFIED",
    "brands",
    "classify",
]
