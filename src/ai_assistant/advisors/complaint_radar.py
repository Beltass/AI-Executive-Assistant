"""Kapsamlı Pazar & Sentiment Analizi — dışarıdan gelen pazar sinyalleri.

Bu danışman, sektörün dışarıdan okunan tüm sinyallerini analiz eder:
müşteri şikâyet gündemi, haber akışından pazar trendleri, rakip hamlelerinin
yönü ve sektöre gelen tehdit/fırsat sinyalleri. Amacı bir yığın başlık vermek
değil, o başlıkları ANLAMAKTIR ve operasyonun KPI'larına ne basınç yapacağını
söylemektir.

VERİ KAYNAKLARI
---------------
Kaynaklar RSS/web akışıdır ve :mod:`ai_assistant.advisors._rss` ile çekilir:
  • Müşteri Şikâyeti: şikâyet platformlarının akışı
  • Sektör Haber: finans/bankacılık sektörü haber akışı
  • Pazar Trendleri: sektöre ilişkin ekonomi ve teknoloji haberleri
  • Rakip İzleme: adı geçen rakiplerin haber/haml akışı

Tıpkı :mod:`~ai_assistant.advisors.market_intelligence` gibi birden fazla
akış TEK havuzda birleştirilir, başlığa göre tekilleştirilir ve
:mod:`ai_assistant.memory` defterinden geçirilir — böylece günün ikinci
çalıştırması sabah anlatılan bulguyu tekrar anlatmaz.

TEMA & KATEGORILER
------------------
Şikâyetler :data:`COMPLAINT_THEMES` altında sabit temalara toplanır (bekleme,
çözümsüzlük, tekrar arama, ücret, dijital kanallar, iletişim, ürün, güvenlik).
Tema listesi modelin uyduracağı bir şey değil, bu dosyada yazılıdır: aynı
tema iki gün üst üste aynı adla anılsın diye.

Configuration (via environment):
    COMPLAINT_RADAR_RSS_URL         Ana şikâyet/itibar akışı (zorunlu değil).
    COMPLAINT_RADAR_SECTOR_RSS_URL  Sektör/finans kurumları şikâyet akışı.
    COMPLAINT_RADAR_BRANDS          Kendi markanız (virgülle ayrılmış).
    COMPLAINT_RADAR_COMPETITORS     Kıyaslanacak rakipler (virgülle ayrılmış).

Besleme çekimi LLM çağrısının DIŞINDA yapılır; yalnızca yazım işi ekibin ortak
toplu çağrısına (``advisors._batch``) katılır. Hiç besleme tanımlı değilse
bölüm Türkçe bir açıklamayla ``skipped`` olur ve koşuyu asla düşürmez.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ..memory import filter_new_items
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

#: ``(setting name, feed label, item limit)`` for every feed folded in here.
#: The label is what the model sees above that feed's headlines, so a merged
#: pool still says whether an item came from the brand desk or the sector desk.
FEEDS: Tuple[Tuple[str, str, int], ...] = (
    ("COMPLAINT_RADAR_RSS_URL", "Şikâyet & itibar akışı", 10),
    ("COMPLAINT_RADAR_SECTOR_RSS_URL", "Sektör / finans kurumları akışı", 8),
)

#: The themes complaints are grouped under. Fixed here rather than invented by
#: the model, so the same complaint carries the same label from day to day.
COMPLAINT_THEMES: Tuple[str, ...] = (
    "Bekleme süresi (IVR kuyruğu, çağrı karşılama, randevu gecikmesi)",
    "Çözümsüzlük (başvuru kapatıldı ama sorun sürüyor, yanıt gelmiyor)",
    "Tekrar arama (aynı konu için ikinci ve üçüncü temas)",
    "Ücret & komisyon (beklenmeyen kesinti, iade edilmeyen tutar, şeffaflık)",
    "Dijital kanal sorunları (mobil/internet şubesi hatası, giriş, doğrulama)",
    "İletişim dili ve tutum (bilgilendirme eksiği, temsilci tavrı)",
    "Ürün & karar süreçleri (limit, tahsis, kart/kredi başvurusu, iptal)",
    "Veri, güvenlik ve dolandırıcılık (izinsiz işlem, kimlik doğrulama)",
)

SYSTEM_PROMPT = (
    "Sen bankacılık ve finans sektöründe müşteri şikâyet yönetimi, pazar trendleri, "
    "rekabet izleme ve itibar takibi konularında kıdemli bir danışmansın. Türkçe yazıyorsun. "
    "İşin ham başlıkları listelemek değil, çoklu veri kaynağından gelen sinyalleri "
    "BİRLEŞTİREREK pazar ve operasyon için ne anlama geldiğini söylemektir.\n\n"
    "KAPSAMLI ANALİZ ÇERÇEVESİ:\n"
    "1. MÜŞTERİ SENTIMENTI & ŞIKÂYET: ARKASINDAKİ MEKANİZMA — hangi süreç kırılır, "
    "kurum nasıl yanıt verince kapanır. Hizmet telafisi, algılanan adalet, FCR, tekrar temas.\n"
    "2. PAZAR TRENDLERİ: Haber akışında sektör ve ekonomi — ne büyüyor, ne düşüyor, "
    "regülatör hamlesi, teknoloji adaptasyonu.\n"
    "3. RAKİP YÖNE: Rakiplerin stratejik hamleleri, pazarda kim ne yaşıyor, güç dengeleri.\n"
    "4. TEHDİT & FIRSAT: Şikâyet trendleri + pazar haberleri + rakip hareketinden "
    "operasyon için çıkan risk/fırsat sinyalleri.\n\n"
    "KANIT DİSİPLİNİ (mutlak kural): Sayı, oran veya yöne ilişkin her iddia SADECE "
    "elindeki akıştan çıkarılabiliyorsa ve kaynağı yazılıyorsa verilir. UYDURMA yapma. "
    "Başlık yoksa 'bu kaynakta veri yok' de. 'Bilinmiyor' kabul edilebilir cevaptır. "
    "Doğrulama gereken her şeyi '(doğrulayın)' işaretle.\n\n"
    "Ton: soğukkanlı, kanıta bakan, operasyonel odaklı. Müşteriyi kaydırma, kurumu cezalandırma."
)

CAVEAT = (
    "📌 Kaynak notu: Buradaki tüm temalar, trendler ve yorumlar YALNIZCA tanımlı "
    "beslemelerden okunan başlıklara dayanır; pazar istatistiğinin tamamını "
    "temsil etmez ve resmî bir pazar raporu değildir. Bir karar vermeden önce "
    "kendi verileriniz, şikâyet kayıtlarınız ve pazar araştırmanızla karşılaştırın.\n"
    "⚖️ Rakip değerlendirmesi, kamuya açık başlıklardan çıkarılmış bir izlenimdir; "
    "rakip stratejisi hakkında sonuç üretmeden önce doğrulayın.\n"
    "🔎 Tüm bağlantıları açılışta doğrulayın; başlıklar zamanla yer değiştirebilir."
)

#: Hiç besleme tanımlı değilken verilen Türkçe açıklama.
NO_FEED_HELP = (
    "missing env var(s): COMPLAINT_RADAR_RSS_URL — kapsamlı analiz için "
    "okunacak bir müşteri şikâyeti RSS akışı tanımlı değil. Bir şikâyet/itibar "
    "RSS adresi (ve istenirse COMPLAINT_RADAR_SECTOR_RSS_URL) tanımlandığında "
    "bu bölüm pazar trendleri, müşteri sentimenti ve rekabet analizi içerir."
)


def _names(name: str) -> List[str]:
    """Virgülle ayrılmış marka/rakip listesini okur. Tanımsızsa boş liste."""
    raw = setting(name) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


class ComplaintRadarAdvisor(Advisor):
    """Expanded comprehensive analysis advisor covering market, sentiment, and competition."""
    key = "complaint_radar"
    title = "Pazar Trendleri & Kapsamlı Analiz Danışmanı"

    #: Şikâyet akışları iki çalıştırma arasında gerçekten YENİ madde üretir.
    incremental_source = True

    def __init__(self) -> None:
        # Koşu başına bir kez çekilir, toplu yol da aynı sonucu kullanır.
        self._groups: List[Tuple[str, List[FeedItem]]] = []
        self._items: List[FeedItem] = []
        self._fetched = False

    def _generate(self) -> Briefing:
        items = self._fetch_items()

        if not self._configured():
            return self.skipped(NO_FEED_HELP)

        if not llm.is_configured():
            if items:
                # Gerçek başlıklar boş bir bölümden iyidir.
                return self.ok(f"{self._headline_list()}\n\n{CAVEAT}")
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            if items:
                return self.ok(f"{self._headline_list()}\n\n{CAVEAT}")
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not self._configured() or not llm.is_configured():
            return None
        self._fetch_items()  # gerçek başlıklar LLM çağrısının DIŞINDA toplanır
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
        return len(self._fetch_items())

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _configured() -> bool:
        """En az bir besleme tanımlı mı."""
        return any(setting(name) for name, _label, _limit in FEEDS)

    def _fetch_items(self) -> List[FeedItem]:
        """Beslemeleri bir kez çeker, YALNIZCA daha önce anlatılmamışları tutar.

        Akışlar TEK havuzda birleşir, böylece iki kaynağa birden düşen bir
        şikâyet haberi bir kez konuşulur; ama kaynak grubu istem için korunur.
        Ölü bir besleme asla ölümcül değildir — bu bölüm zengin­leştirmedir.
        """
        if self._fetched:
            return self._items
        self._fetched = True

        collected: List[Tuple[str, List[FeedItem]]] = []
        pool: List[FeedItem] = []
        seen = set()
        for name, label, limit in FEEDS:
            url = setting(name)
            if not url:
                continue
            try:
                fetched = fetch_feed_items(url, limit=limit)
            except Exception:
                # İsteğe bağlı zenginleştirme — besleme yüzünden bölüm düşmez.
                continue
            group: List[FeedItem] = []
            for item in fetched:
                if item.title in seen:
                    continue  # aynı haber iki akıştan geldiyse bir kez sayılır
                seen.add(item.title)
                group.append(item)
                pool.append(item)
            if group:
                collected.append((label, group))

        self._items = filter_new_items(self.key, pool)
        fresh = {id(item) for item in self._items}
        self._groups = [
            (label, [item for item in group if id(item) in fresh])
            for label, group in collected
        ]
        self._groups = [(label, group) for label, group in self._groups if group]
        return self._items

    @staticmethod
    def _format(items: Sequence[FeedItem]) -> str:
        return "\n".join(
            f"- {item.title}" + (f" ({item.link})" if item.link else "")
            for item in items
        )

    def _headline_list(self) -> str:
        """LLM'siz yedek yol: bugünün yeni başlıkları, kaynağına göre."""
        blocks = [
            f"*{label}*\n{self._format(group)}" for label, group in self._groups
        ]
        return "Bugünün yeni şikâyet başlıkları:\n\n" + "\n\n".join(blocks)

    def _feed_block(self) -> str:
        """Modele verilen gruplu başlık listesi, ya da akış yoksa uyarısı."""
        if not self._groups:
            return (
                "\n\nBugün beslemeden YENİ başlık gelmedi. Bu durumda sayı ve "
                "sıralama VERME; sektörde kalıcı olarak bilinen şikâyet "
                "mekanizmalarını anlat, hacim ve rakip kıyası bölümlerinde "
                "'bugün veri yok' de ve neyin ölçülmesi gerektiğini söyle."
            )
        blocks = "\n\n".join(
            f"[{label}]\n{self._format(group)}" for label, group in self._groups
        )
        return (
            "\n\nAşağıdaki başlıklar BUGÜN İLK KEZ geliyor ve KAYNAK AKIŞINA "
            "GÖRE gruplanmıştır. Her başlığı bir temaya yerleştir, "
            "'📚 Kaynaklar' bölümünde bu GERÇEK bağlantıları tercih et ve bir "
            "başlığın içeriğinden emin değilsen yorumunu '(başlığa göre, "
            f"doğrulayın)' diye işaretle:\n\n{blocks}"
        )

    def _user_prompt(self) -> str:
        brands = _names("COMPLAINT_RADAR_BRANDS")
        competitors = _names("COMPLAINT_RADAR_COMPETITORS")
        themes = "\n".join(f"- {theme}" for theme in COMPLAINT_THEMES)

        context = ""
        if brands:
            context += f"TAKİP EDİLEN KENDİ MARKALAR: {', '.join(brands)}.\n"
        if competitors:
            context += f"KIYASLANACAK RAKİPLER: {', '.join(competitors)}.\n"
        if not competitors:
            context += (
                "Rakip listesi tanımlı değil (COMPLAINT_RADAR_COMPETITORS); "
                "rakip kıyasını akışta ADI GEÇEN kurumlarla yap, kurum adı "
                "uydurma.\n"
            )

        return (
            "Bugün için bankacılık ve finans sektöründen gelen çoklu sinyal "
            "(müşteri şikâyeti, pazar haberleri, rakip hareketleri) kaynağından "
            "KAPSAMLI bir analiz brifingi yaz.\n"
            f"{context}\n"
            "Şu blokları bu sırayla ver:\n\n"
            "*🔥 En çok konuşulan şikâyetler*: sektörde bugün öne çıkan 3-5 "
            "şikâyet konusu; her biri için ne şikâyet ediliyor ve arkasındaki "
            "operasyon mekanizması hangisi.\n\n"
            "*🗂️ Temalara göre gruplama*: şikâyetleri AŞAĞIDAKİ sabit temalara "
            "dağıt (tema adlarını aynen kullan, yeni tema uydurma; boş kalan "
            "temayı 'bugün kayıt yok' diye geç):\n"
            f"{themes}\n\n"
            "*📰 Pazar trendleri*: haber akışında ön plana çıkan sektör ve ekonomi "
            "haberleri — regülatör hamleleri, teknoloji adaptasyonu, makro eğilimler. "
            "Bunlar müşteri şikâyetleri ile ne şekilde ilişkili.\n\n"
            "*⚔️ Rakip yöne & pazar haritası*: rakiplerin stratejik hamleleri, hangi "
            "kurumlar hangi konuda öne çıkıyor, pazar güç dengeleri nasıl değişiyor. "
            "Kendi markanız rakip trendine karşı nerede duruyor.\n\n"
            "*🏛️ Kurumlar nasıl yanıt veriyor*: gözlenen çözüm yaklaşımı — yanıt süresi, "
            "telafi biçimi, kanal değişikliği, süreç/ürün düzeltmesi. Hangi yanıt "
            "biçiminin şikâyeti kapattığını, hangisinin büyüttüğünü hizmet telafisi "
            "çerçevesiyle açıkla.\n\n"
            "*📈 Hacim, yön & mevsimsellik*: şikâyet hacminin değişimi — artıyor mu, "
            "azalıyor mu, mevsimsel mi. Elindeki başlık sayısı bir trend için yetersizse "
            "bunu söyle ve neyin ölçülmesi gerektiğini yaz.\n\n"
            "*⚠️ TEHDİT & FIRSAT*: şikâyet trendleri + pazar haberleri + rakip hareketleri "
            "kombinasyonundan operasyon için çıkan risk ve fırsat sinyalleri. Hangi sorun "
            "büyüyebilir, hangi alan açılıyor. Operasyon açısından hangi KPI'ya (FCR, "
            "tekrar temas, AHT, CES, NPS) ne zaman basınç girebilir.\n\n"
            "*🧭 Operasyon yorumu*: bu tablo pazar ve müşteri tarafında ne yapılması gerektiğini "
            "söyler. Hangi erken uyarı sinyalı izlenmeli, hangi yapısal sorun atacak, hangi "
            "hızlı kazanç alınabilir. Bu bölüm LİSTE DEĞİL, OPERASYONEL YORUM olsun.\n\n"
            "'✅ Bugünün görevi' bölümünde bugün 15-30 dakikada yapılabilecek "
            "TEK somut eylem yaz — tercihen doğrulanabilir (örn. 'geçen hafta kapatılan "
            "şikâyetlerden 10'unu aç, kaçında müşteri 7 gün içinde tekrar aramış' veya "
            "'rakip XYZ'nin yeni ürün hamlesi hakkında 2 müşteri görüşü yap').\n\n"
            + RICH_BRIEFING_GUIDE
            + self._feed_block()
        )


__all__ = [
    "COMPLAINT_THEMES",
    "CAVEAT",
    "ComplaintRadarAdvisor",
    "FEEDS",
    "NO_FEED_HELP",
]
