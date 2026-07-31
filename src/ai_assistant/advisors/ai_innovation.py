"""AI & innovation advisor — Yapay Zeka & İnovasyon (PHASE 1B consolidation).

Folds TWO previously separate personas into ONE briefing produced by a SINGLE
LLM call:

* :mod:`~ai_assistant.advisors.ai_mastery` — the patient teacher who builds the
  user's own SKILL with AI tools, one lesson a day, from ``temel`` to ``ileri``,
  fed by the ``AI_MASTERY_RSS_URL`` training/certificate feed.
* :mod:`~ai_assistant.advisors.innovation_lab` — the strategist who reads the
  last few days of briefings, spots the gaps and proposes concrete projects and
  improvements, each scored for effort (1-5) and impact (1-5).

WHY ONE CALL. Both personas are about *capability that does not exist yet*: one
builds the skill, the other decides where to point it. Learning something and
then immediately being handed a project to apply it to is a better briefing
than two disconnected sections — and it is a 2 → 1 reduction in batch sections.

Be honest about where the saving is: this consolidation buys OUTPUT tokens and
one fewer section framing, not input tokens. The innovation lab's own prompt
was a terse JSON request, so the merged user prompt is slightly *longer* than
the two it replaces (~5.2 KB vs ~4.7 KB, guide excluded). What disappears is a
whole second section of the batched response — headline, intro, sources and
daily task included.

WHAT IS PRESERVED (deliberately, item by item):

* the LEVEL setting (``AI_MASTERY_LEVEL``) and its three teaching registers, so
  the same topic is taught differently to a beginner and to someone already
  shipping automations;
* the day-of-year CURRICULUM rotation, so consecutive days never repeat and the
  whole syllabus is covered over time with no stored state;
* the three deliverables the user asked for by name — **hap bilgi**, **eğitim
  videoları**, **ücretsiz sertifikalı eğitimler** — plus a hands-on task that is
  actually run inside an AI tool;
* the training-announcement RSS feed and its :mod:`ai_assistant.memory` dedup,
  so the extra daily runs only mention announcements the user has not seen yet;
* the innovation lab's gap analysis over the last three days of published
  briefings, its four idea categories (``process`` / ``feature`` / ``project`` /
  ``learning``) and its EFFORT (1-5) + IMPACT (1-5) scoring with concrete next
  steps;
* the "never invent a course name, a certificate or a link" rule, always closed
  with the "verify it is still free" reminder.

WHAT CHANGED. The innovation lab used to emit raw JSON. Consolidated, this
advisor writes Markdown like every other section — the scores are rendered
inline as ``Çaba 2/5 · Etki 4/5`` — because one batched response cannot mix a
JSON document into a Markdown briefing. Anything that consumed
``innovation_lab.json`` must read the ``## 💡 Proaktif Fikirler`` block instead.

PRIVACY. Like the innovation lab before it, this advisor is ``private``: its
idea section reasons about the user's own operation, backlog and gaps, which is
not something to publish to the public dashboard. Its section is delivered
inline in Slack instead (see :mod:`ai_assistant.reports`).

Configuration (via environment):
    AI_MASTERY_LEVEL     temel | orta | ileri (default ``temel``).
    AI_MASTERY_RSS_URL   Feed of free AI training/certificate announcements.
    RECENT_REPORTS_DIR   Directory of recent briefing JSON files
                         (default ``frontend/reports``).

The feed fetch and the report scan always happen locally, never inside the LLM
call; only the writing joins the batched team request. With no LLM provider key
the advisor is ``skipped``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ..memory import filter_new_items
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

logger = logging.getLogger(__name__)

DEFAULT_LEVEL = "temel"
LEVELS = ("temel", "orta", "ileri")

REPORTS_DIR_ENV = "RECENT_REPORTS_DIR"
DEFAULT_REPORTS_DIR = "frontend/reports"

#: How many past days of briefings feed the gap analysis, and how many of their
#: headlines are actually sent to the model.
RECENT_DAYS = 3
MAX_RECENT_FINDINGS = 15

#: The subsection headings the model MUST emit, in this order. Exported so the
#: report renderer can split one consolidated briefing back into two blocks.
SECTION_HEADINGS = (
    "## 🧠 Yapay Zeka Ustalaşma Görevi",
    "## 💡 Proaktif Fikirler (Proje & İyileştirme)",
)

LEVEL_GUIDE = {
    "temel": (
        "Öğrenci SIFIRDAN başlıyor. Jargon kullanma, kullanırsan hemen tek "
        "cümleyle açıkla. Her kavramı gündelik bir benzetmeyle anlat ve "
        "kopyalayıp yapıştırabileceği hazır örnekler ver."
    ),
    "orta": (
        "Öğrenci temel kullanımı biliyor; artık kaliteyi ve tekrarlanabilirliği "
        "öğreniyor. Kalıp (template) kur, öncesi/sonrası karşılaştırması göster, "
        "yaygın hataları ve düzeltmelerini adım adım işle."
    ),
    "ileri": (
        "Öğrenci ileri seviye: iş akışı kuruyor, ölçüyor ve maliyet yönetiyor. "
        "Mimari kararlar, değerlendirme (eval) tasarımı, hata modları, güvenlik "
        "ve maliyet ödünleşmeleri üzerinden konuş."
    ),
}

# The syllabus. One item per day, rotating by day-of-year, so the coach covers
# the whole ground over time instead of circling the same lesson.
CURRICULUM: List[str] = [
    "Prompt mühendisliğinin temelleri: iyi bir istemin anatomisi (rol, görev, "
    "bağlam, biçim, kısıt), belirsizliği azaltma, örnekle öğretme (few-shot) ve "
    "istemi yeniden yazarak iyileştirme döngüsü",
    "Sistem istemi ve bağlam yönetimi: kalıcı yönergeler, kişisel bağlam "
    "dosyası, konuşma bağlamının nasıl dolduğu, uzun belgelerle çalışırken "
    "parçalama ve özetleme taktikleri",
    "Adım adım düşündürme ve yapılandırılmış çıktı: 'önce planla sonra yaz', "
    "kontrol listeleri, tablo/JSON/madde biçiminde çıktı isteme ve çıktıyı "
    "doğrudan işine yapıştırabilir hâle getirme",
    "RAG'in temelleri: kendi belgelerinle konuşmak ne demek, gömme (embedding) "
    "ve arama mantığı, hangi durumda RAG hangi durumda uzun bağlam, kaynak "
    "gösterimi ve doğrulama",
    "Ajanlar ve araç kullanımı: modelin araç çağırması ne demek, hangi işler "
    "ajanlaştırılır hangileri ajanlaştırılmaz, insan onayı (human-in-the-loop) "
    "noktaları ve başarısızlık senaryoları",
    "Otomasyon: n8n, Zapier ve Make ile tetikleyici-eylem mantığı, e-posta/"
    "tablo/mesaj akışlarını yapay zekâ adımıyla birleştirme, ilk otomasyonu "
    "küçük ve geri alınabilir kurma",
    "API kullanımı: anahtar yönetimi, temel istek/yanıt döngüsü, sıcaklık ve "
    "çıktı uzunluğu gibi parametreler, hata ve kota yönetimi, ücretsiz "
    "katmanlarla çalışma disiplini",
    "Çıktıyı değerlendirme: küçük bir test seti kurmak, iyi/kötü örnek "
    "kıyaslaması, kabul kriterleri yazmak, aynı istemi iki modelde deneyip "
    "karşılaştırmak",
    "Halüsinasyondan kaçınma: modelden kaynak isteme, doğrulanabilir iddia ile "
    "yorum ayrımı, 'bilmiyorum' demesine izin veren istemler, sayısal iddiaları "
    "kaynağından teyit etme alışkanlığı",
    "Yapay zekâ kullanırken veri gizliliği: hangi veri asla yapıştırılmaz, "
    "kurumsal ve bireysel hesap farkı, verinin eğitimde kullanılması ayarları, "
    "maskeleme ve anonimleştirme pratikleri",
    "Maliyet kontrolü: token mantığı, uzun bağlamın faturaya etkisi, ücretsiz "
    "katman sınırları, toplu (batch) çalışma ve önbellekleme ile tasarruf",
    "Doğru modeli seçmek: hızlı/ucuz model ile güçlü modelin işleri, çok "
    "kipli (görsel/ses) ihtiyaçlar, karar tablosu kurma ve modeli işe göre "
    "değiştirme alışkanlığı",
]

# Providers whose ROOT domains are stable enough to cite without a live link.
STABLE_PROVIDERS = (
    "Google Cloud Skills Boost (https://www.cloudskillsboost.google), "
    "Microsoft Learn (https://learn.microsoft.com), "
    "DeepLearning.AI (https://www.deeplearning.ai), "
    "Coursera (https://www.coursera.org), edX (https://www.edx.org), "
    "Hugging Face (https://huggingface.co), "
    "Kaggle Learn (https://www.kaggle.com/learn), "
    "freeCodeCamp (https://www.freecodecamp.org), "
    "Anthropic dokümanları (https://docs.anthropic.com), "
    "OpenAI dokümanları (https://platform.openai.com)"
)

SYSTEM_PROMPT = (
    "Sen aynı anda İKİ rolü taşıyorsun. Birincisi 'Yapay Zeka Ustalığı Koçu': "
    "yapay zekâ uygulamalarını sıfırdan ileri seviyeye öğreten, sabırlı ve çok "
    "pratik bir eğitmensin; her kavramı örnekle, kopyalanabilir istem "
    "kalıplarıyla ve 'şimdi şunu dene' düzeyinde talimatlarla öğretirsin. "
    "İkincisi 'İnovasyon ve Stratejik Fırsatlar Uzmanı': son brifingleri ve "
    "sektör gelişmelerini okuyup yapılmamış işleri, eksikleri ve fırsatları "
    "tespit eder, bunları somut ve uygulanabilir öneriler hâline getirirsin. "
    "Türkçe konuşuyorsun.\n\n"
    "İki rolü BİRBİRİNE BAĞLA: öğrettiğin beceri, önerdiğin fikirlerden en az "
    "birinde işe yarasın. Öğrencin teknik bir uzman değil; onu her gün bir adım "
    "ileri taşımak ve bu beceriyi gerçek bir işe uygulatmak istiyorsun.\n\n"
    "Abartmazsın, moda sözcüklerle konuşmazsın. ASLA uydurma bağlantı, uydurma "
    "kurs adı veya uydurma sertifika vermezsin; emin olmadığında sağlayıcının "
    "ana adresini verip arama terimi önerirsin. Önerdiğin her fikirde çabayı "
    "(1-5) ve potansiyel etkiyi (1-5) dürüstçe puanlarsın — her şeyi 'düşük "
    "çaba, yüksek etki' diye etiketlemek işe yaramaz."
)

CAVEAT = (
    "ℹ️ Not: Eğitim ve sertifika koşulları (ücretsizlik, süre, dil) sağlayıcı "
    "tarafından değiştirilebilir; kaydolmadan önce sayfada teyit edin.\n"
    "📐 Çaba/etki puanları bir tahmindir; kendi ekip kapasitenize göre yeniden "
    "değerlendirin.\n"
    "🔎 Bağlantıları açılışta doğrulayın."
)


def _level() -> str:
    """Today's teaching level (``AI_MASTERY_LEVEL``), defaulting to ``temel``."""
    raw = (setting("AI_MASTERY_LEVEL") or DEFAULT_LEVEL).strip().lower()
    return raw if raw in LEVELS else DEFAULT_LEVEL


def _daily_topic(today: Optional[date] = None) -> str:
    """Today's curriculum topic (day-of-year rotation, so days differ)."""
    day = today or date.today()
    return CURRICULUM[day.toordinal() % len(CURRICULUM)]


class AiInnovationAdvisor(Advisor):
    key = "ai_innovation"
    title = "Yapay Zeka & İnovasyon (Ustalaşma · Fikirler)"

    # The idea half reasons about the user's own operation and backlog, so the
    # section is delivered inline in Slack and never published to the public
    # dashboard. Inherited from the innovation lab.
    private = True

    # Its free-training feed is a genuine source of NEW findings between two
    # runs on the same day.
    incremental_source = True

    def __init__(self) -> None:
        # Fetched once per run and reused by the batched path.
        self._items: List[FeedItem] = []
        self._fetched = False

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )
        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")
        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """ONE section for what used to be two separate batched sections."""
        if not llm.is_configured():
            return None
        self._fetch_items()  # real links gathered OUTSIDE the LLM call
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
    def _fetch_items(self) -> List[FeedItem]:
        """Fetch the training feed once, keeping only NOT-YET-REPORTED items."""
        if self._fetched:
            return self._items
        self._fetched = True
        url = setting("AI_MASTERY_RSS_URL")
        if not url:
            return self._items
        try:
            fetched = fetch_feed_items(url, limit=8)
        except Exception:
            # Optional enrichment only — never fail the lesson over a feed.
            return self._items
        self._items = filter_new_items(self.key, fetched)
        return self._items

    def _recent_report_dirs(self, limit: int) -> List[str]:
        """The ``limit`` most recent date directories under the reports dir."""
        reports_dir = (setting(REPORTS_DIR_ENV) or DEFAULT_REPORTS_DIR).strip()
        if not os.path.isdir(reports_dir):
            return []
        entries = sorted(
            (
                name
                for name in os.listdir(reports_dir)
                if os.path.isdir(os.path.join(reports_dir, name))
            ),
            reverse=True,
        )
        return [os.path.join(reports_dir, name) for name in entries[:limit]]

    def _gather_recent_findings(self) -> str:
        """Headlines from the last few days of briefings, for gap analysis.

        Only the PUBLISHED report files are read — private advisors never write
        there — so this scan can only ever see material the user has already
        been shown. Any unreadable file is skipped rather than failing the run.
        """
        try:
            findings: List[str] = []
            for day_path in self._recent_report_dirs(RECENT_DAYS):
                for name in sorted(os.listdir(day_path)):
                    if not name.endswith(".json"):
                        continue
                    try:
                        with open(
                            os.path.join(day_path, name), "r", encoding="utf-8"
                        ) as handle:
                            data = json.load(handle)
                    except Exception as exc:
                        logger.debug("rapor okunamadı %s: %s", name, exc)
                        continue
                    title = (data.get("title") or "").strip()
                    headline = (data.get("headline") or "").strip()
                    if title and headline:
                        findings.append(f"- {title}: {headline}")
            return "\n".join(findings[:MAX_RECENT_FINDINGS])
        except Exception as exc:  # defensive: never fail the briefing over I/O
            logger.debug("son bulgular toplanamadı: %s", exc)
            return ""

    def _gather_market_context(self) -> str:
        """A short excerpt of the most recent market-intelligence briefing.

        Falls back to the pre-consolidation ``sector_intel`` file so a rollback
        (or a report directory written before Phase 1B) still has context.
        """
        try:
            for day_path in self._recent_report_dirs(1):
                for name in ("market_intelligence.json", "sector_intel.json"):
                    path = os.path.join(day_path, name)
                    if not os.path.exists(path):
                        continue
                    with open(path, "r", encoding="utf-8") as handle:
                        text = (json.load(handle).get("text") or "").strip()
                    if text:
                        # Trimmed: this is context, not the subject matter.
                        return text[:500] + "..." if len(text) > 500 else text
            return ""
        except Exception as exc:  # defensive: never fail the briefing over I/O
            logger.debug("pazar bağlamı toplanamadı: %s", exc)
            return ""

    def _user_prompt(self) -> str:
        level = _level()

        prompt = (
            f"ÖĞRENCİ SEVİYESİ: {level}. {LEVEL_GUIDE[level]}\n"
            f"BUGÜNÜN KONUSU: {_daily_topic()}\n\n"
            "Bugün için TEK bir yapay zeka & inovasyon brifingi yaz. Brifing "
            "İKİ alt bölümden oluşacak; alt başlıkları AYNEN aşağıdaki gibi, bu "
            "sırayla ve bu yazımla ver (rapor bu başlıklardan bölünüyor):\n"
            + "\n".join(SECTION_HEADINGS)
            + "\n\n"
            "Alt bölümlerin içeriği:\n\n"
            f"{SECTION_HEADINGS[0]}\n"
            "Bugünün dersini yukarıdaki KONU etrafında kur; konuyu seviyeye "
            "göre derinleştir ve bir sonraki adımı da göster (bu konuda "
            "ustalaşınca sırada ne var). Şu blokları ver:\n"
            "(a) *💊 Hap bilgi*: bugünün tek cümlelik, hemen uygulanabilir püf "
            "noktası — kalın yazılmış, akılda kalıcı.\n"
            "(b) *📖 Dersin özü*: konuyu adım adım öğret; en az bir "
            "KOPYALANABİLİR istem (prompt) kalıbı ver ve aynı isteğin zayıf ve "
            "güçlü hâlini yan yana göster.\n"
            "(c) *🎬 Eğitim videoları*: 2-3 video kaynağı öner. Kanal/sağlayıcı "
            "adını ve ne arayacağını yaz; derin video URL'i UYDURMA, kanalın "
            "veya platformun ana adresini ver.\n"
            "(d) *🎓 Ücretsiz sertifikalı eğitimler*: 2-3 ücretsiz (veya "
            "ücretsiz izlenebilen) sertifikalı eğitim öner; her biri için "
            "sağlayıcı, yaklaşık süre, seviye ve sertifikanın gerçekten "
            "ücretsiz olup olmadığının nasıl kontrol edileceğini yaz.\n"
            "(e) *⚠️ Sık yapılan hata*: bu konuda yeni başlayanların düştüğü "
            "bir tuzak ve düzeltmesi.\n"
            f"Kaynak verirken yalnızca bilinen ve KALICI sağlayıcıların kök "
            f"alan adlarını kullan: {STABLE_PROVIDERS}. Var olduğundan emin "
            "olmadığın hiçbir derin URL'i yazma; onun yerine ana adres + "
            "önerilen arama terimi ver.\n\n"
            f"{SECTION_HEADINGS[1]}\n"
            "Önümüzdeki 1-3 ay içinde hayata geçirilebilecek 4-6 somut öneri "
            "üret. Aşağıdaki son brifing bulgularını ve pazar bağlamını "
            "kullanarak YAPILMAMIŞ işleri, eksikleri ve fırsatları tespit et; "
            "genel geçer 'yapay zeka kullanın' tavsiyesi verme.\n"
            "Her fikri TAM OLARAK şu biçimde yaz:\n"
            "**<Türkçe başlık>** — `<kategori>` · Çaba <1-5>/5 · Etki <1-5>/5\n"
            "  - *Ne*: 2-3 cümlelik açıklama.\n"
            "  - *Neden*: hangi problemi çözüyor, hangi bulgudan çıkıyor.\n"
            "  - *Adımlar*: 2-4 somut haftalık adım ve sonunda bir başarı "
            "ölçütü.\n"
            "Kategori şunlardan biri olsun: `process` (iş süreci iyileştirme), "
            "`feature` (yeni özellik/araç), `project` (yeni proje), `learning` "
            "(eğitim ve gelişim). Kategorileri dengeli seç — hepsi `project` "
            "olmasın.\n"
            "Puanlama dürüst olsun: çaba 1 = birkaç saat, 5 = aylar süren "
            "program; etki 1 = marjinal, 5 = dönüştürücü. Fikirleri etki/çaba "
            "oranına göre sırala; düşük çaba-yüksek etki olanlar başa gelsin. "
            "Ekip kapasitesi veya bütçe varsayımı yapıyorsan bunu açıkça yaz.\n"
            "Bölümü tek cümlelik bir *Genel çıkarım* ile kapat: bu önerilerin "
            "birlikte hangi stratejik boşluğu kapattığı.\n\n"
            "'✅ Bugünün görevi' bölümünde bugün 15-30 dakikada bir yapay zekâ "
            "aracında BİZZAT çalıştırılacak somut bir alıştırma yaz — istemi "
            "aynen ver, neye bakılacağını ve başarının nasıl anlaşılacağını "
            "söyle. Mümkünse bu alıştırma yukarıdaki fikirlerden birinin ilk "
            "adımı olsun.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nUZUNLUK İSTİSNASI: Bu bölüm iki alt bölümden oluştuğu için "
            "ortak kurallardaki 300-500 kelime hedefi BÜTÜN için 550-750 "
            "kelimeye çıkar; iki alt bölüm de kendi başına doyurucu olsun ama "
            "hiçbiri atlanmasın."
        )

        findings = self._gather_recent_findings()
        if findings:
            prompt += f"\n\nSON BRİFİNG BULGULARI:\n{findings}"
        else:
            prompt += (
                "\n\nSON BRİFİNG BULGULARI: son raporlara erişilemedi; "
                "fikirleri kullanıcının alanına dair genel bilgine dayandır ve "
                "bu varsayımı açıkça belirt."
            )

        context = self._gather_market_context()
        if context:
            prompt += f"\n\nPAZAR BAĞLAMI (son pazar istihbaratı):\n{context}"

        items = self._fetch_items()
        if items:
            listing = "\n".join(
                f"- {item.title}" + (f" ({item.link})" if item.link else "")
                for item in items
            )
            prompt += (
                "\n\nAşağıdaki eğitim/sertifika duyuruları BUGÜN İLK KEZ "
                "geliyor; ilgili olanları 'Ücretsiz sertifikalı eğitimler' "
                "bloğuna yedir ve '📚 Kaynaklar' bölümünde bu GERÇEK "
                f"bağlantıları tercih et:\n{listing}"
            )
        else:
            prompt += (
                "\n\nBugün yeni bir eğitim duyurusu akışı yok; kaynak olarak "
                "yalnızca yukarıdaki kalıcı sağlayıcıların ana adreslerini "
                "kullan ve derin URL uydurma."
            )
        return prompt


__all__ = [
    "AiInnovationAdvisor",
    "SECTION_HEADINGS",
    "CURRICULUM",
    "LEVEL_GUIDE",
]
