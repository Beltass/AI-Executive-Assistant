"""Operasyon Direktörü — günün BİRİKMİŞ bulgularını KARARA çeviren persona.

Bu danışman EN SON çalışır (``work_analyst``tan da sonra) ve kendi başına
hiçbir veri toplamaz: bu koşuda üretilmiş TÜM brifingleri okur, Veri
Analisti'nin yapısal bulgularını alır ve tek bir çıktı üretir — **öncelik
sırasına dizilmiş karar listesi**. Her maddede üç şey vardır ve üçü de
zorunludur: SAHİBİ, SON TARİHİ ve AKSİYON ALINMAZSA NE OLACAĞI.

WORK_ANALYST'TAN FARKI (bu modülün en kritik sınırı)
----------------------------------------------------
``work_analyst`` SİSTEMİN teknik sağlığını izler: hangi danışman çalıştı,
başarı oranı ne, zaman aşımı/token sorunu var mı, entegrasyon koptu mu. Onun
öznesi YAZILIMDIR.

``operations_director``ün öznesi İŞTİR. Baktığı sorular:

* kadro yeterliliği — beklenen çağrı hacmine karşı vardiya kapasitesi,
* önümüzdeki günler için SLA riski,
* bekleyen iş (backlog) ve eskalasyon duruşu,
* bugünün bulgularından hangisi KULLANICIDAN BUGÜN karar bekliyor,
* neyin DEVREDİLEBİLECEĞİ ve kime.

Sınır kod düzeyinde de çizilidir: :data:`SYSTEM_HEALTH_KEYS` içindeki
danışmanların içeriği karar listesine hiç girmez (bkz.
:meth:`OperationsDirectorAdvisor._business_inputs`) ve sistem istemi "danışman
başarı oranı, API hatası, token tüketimi gibi SİSTEM konularını yazma; onlar
İş Analisti'nin işi" der. Aynı cümle brifingin sonunda kullanıcıya da
görünür, böylece iki bölümün neden farklı olduğu okurken de bellidir.

TEK LLM ÇAĞRISI
---------------
Bu persona toplu çağrıya (``advisors._batch``) KATILAMAZ: toplu istem, hiçbir
danışman çalışmadan ÖNCE kurulur, oysa buranın girdisi diğerlerinin ÇIKTISIDIR
(bkz. :meth:`observe`). Bu yüzden kendi tek çağrısını yapar — toplu çağrı +
bu çağrı, günde toplam iki istek.

TEMİZ DEVREDİLME
----------------
* Hiç brifing görmediyse (tek başına çalıştırıldı) → ``skipped``, nasıl
  çalıştırılacağını anlatan Türkçe not.
* Brifingler var ama hiçbiri içerik üretmemişse → ``skipped``, neyin
  yapılandırılması gerektiğini anlatan Türkçe not.
* İçerik var ama LLM anahtarı yoksa ya da çağrı patlarsa → deterministik
  karar listesi (sahip/son tarih/sonuç yine dolu). Traceback asla.

GİZLİLİK: diğer danışmanların kişisel içeriğini sentezler, bu yüzden
``private = True`` — panoya yazılmaz, yalnızca Slack'te durur.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm

logger = logging.getLogger(__name__)

BUSINESS_ENV = "OPERATIONS_DIRECTOR_BUSINESS"
FORECAST_ENV = "OPERATIONS_DIRECTOR_FORECAST"
SLA_TARGET_ENV = "OPERATIONS_DIRECTOR_SLA_TARGET"

DEFAULT_BUSINESS = "çağrı merkezi operasyonu"

#: Sistemin TEKNİK sağlığını raporlayan danışman(lar). İçerikleri bu personanın
#: karar listesine GİRMEZ — orayı İş Analisti kapsar ve iki bölümün aynı şeyi
#: söylemesi kullanıcıya bilgi değil gürültü olur.
SYSTEM_HEALTH_KEYS = frozenset({"work_analyst"})

#: Kendi kendini okumasın.
_SELF_KEYS = frozenset({"operations_director"})

#: Bir danışmanın brifinginden karar istemine taşınacak en fazla karakter.
#: Token disiplini: on danışman × sınırsız metin tek çağrıya sığmaz ve zaten
#: karar için gereken şey başlık + ilk paragraftır.
MAX_INPUT_CHARS = 700

#: İstemin tamamı için üst sınır.
MAX_PROMPT_CHARS = 9000

#: Karar listesinin en fazla madde sayısı — "her şey acil" bir öncelik listesi
#: değildir.
MAX_DECISIONS = 6

#: Hiç girdi yokken verilen Türkçe açıklama.
NO_RUN_HELP = (
    "bu danışman diğer TÜM danışmanlardan sonra çalışır ve onların çıktısını "
    "sentezler; tek başına çalıştırıldığında sentezleyecek bir şey bulamaz. "
    "Tam çalıştırma modunu kullanın (BRIEFING_MODE=full)."
)

NO_CONTENT_HELP = (
    "bugün karar verilecek bir iş bulgusu üretilmedi: diğer danışmanların "
    "hiçbiri içerik döndürmedi. En az bir iş kaynağı yapılandırın — örneğin "
    "DATA_ANALYST_SOURCE (operasyon verisi), GOOGLE_* kimlikleri (takvim ve "
    "posta) veya ASANA_ACCESS_TOKEN/TODOIST_API_TOKEN (bekleyen iş)."
)

#: Modelin üreteceği karar satırının BİÇİMİ. Bu biçim rastgele değil:
#: ``ai_assistant.reports`` aksiyon ayrıştırıcısının okuduğu "(Son tarih: …)
#: (Sorumlu: …)" düzenidir, yani satır hem Slack'te okunur hem de yapısal
#: raporun aksiyon listesine sahibi ve tarihiyle düşer.
DECISION_FORMAT = (
    "- **<karar>** — Dayanak: <sayı veya bulgu>. Aksiyon alınmazsa: <somut "
    "sonuç>. (Son tarih: <bugün / bu hafta / gün>) (Sorumlu: <kişi/rol>)"
)

SECTION_HEADINGS = (
    "## 🚦 Bugünün kararları (öncelik sırasıyla)",
    "## 👥 Kadro ve SLA riski",
    "## 📥 Bekleyen iş ve eskalasyon duruşu",
    "## 🤝 Devredilecekler",
)

SYSTEM_PROMPT = (
    "Sen bir işletmenin operasyon direktörüsün. Günün sonunda ekibin bütün "
    "raporlarını okuyup KARAR veren kişisin. Türkçe yazıyorsun ve karşındaki "
    "kişi işin sahibi — ona rapor özeti değil, KARAR LİSTESİ verirsin.\n\n"
    "KAPSAMIN İŞ OPERASYONUDUR: kadro yeterliliği ve vardiya kapasitesi, "
    "beklenen hacme karşı SLA riski, bekleyen iş (backlog) ve eskalasyon "
    "duruşu, bugün karar bekleyen konular, devredilebilecek işler.\n\n"
    "KAPSAMIN DIŞINDA — YAZMA: danışman/ajan başarı oranı, API hataları, "
    "token tüketimi, zaman aşımı, yazılım sağlığı. Bunlar İş Analisti "
    "bölümünün konusudur; burada tekrar edilirse kullanıcı aynı şeyi iki kez "
    "okur. Bir teknik arıza iş sonucunu etkiliyorsa bile onu 'sistem sorunu' "
    "olarak değil, 'şu iş kararı şu yüzden bugün verilemiyor' biçiminde yaz.\n\n"
    "MUTLAK KURALLAR:\n"
    "1. Her karar maddesi TAM OLARAK şu biçimde olsun:\n"
    f"{DECISION_FORMAT}\n"
    "2. SAHİP ve SON TARİH boş bırakılamaz. Sahibi belli değilse en yakın "
    "rolü yaz (Operasyon, Ekip Lideri, Sen).\n"
    "3. 'Aksiyon alınmazsa' kısmı SOMUT olsun: hangi gösterge, hangi müşteri "
    "grubu, hangi süre. 'Sorun olur' gibi cümle yazma.\n"
    "4. SAYI UYDURMA. Yalnızca sana verilen GÜNÜN GİRDİLERİ bloğundaki "
    "rakamları kullan; blokta yoksa sayı verme, niteliksel yaz.\n"
    "5. EN FAZLA "
    f"{MAX_DECISIONS} karar. Her şeyi öne almak öncelik değildir; en çok "
    "etkiyi yaratacak olanı en üste koy.\n"
    "6. Kısa yaz. Bu bir brifing değil, bir karar listesidir."
)

CLOSING_NOTE = (
    "🔒 Not: Bu bölüm İŞ operasyonunu yönetir — kadro, SLA riski, bekleyen iş "
    "ve bugünün kararları. Sistemin teknik sağlığı (danışman başarı oranı, API "
    "ve token durumu) bilerek buraya alınmaz; o İş Analisti bölümündedir. "
    "Kişisel veri içerir, panoya yazılmaz."
)

#: Karar satırından sahip/son tarih ayıklayan desenler. ``reports`` tarafındaki
#: ayrıştırıcıyla AYNI etiketleri okur; burada ayrıca kendimiz ayıklıyoruz ki
#: yapısal aksiyon listesi metnin biçimine bağlı kalmasın.
_OWNER_RE = re.compile(r"\(\s*sorumlu\s*[:：]\s*([^)]{1,60})\)", re.IGNORECASE)
_DEADLINE_RE = re.compile(r"\(\s*son\s+tarih\s*[:：]\s*([^)]{1,40})\)", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.+)$")


def business_label() -> str:
    return setting(BUSINESS_ENV) or DEFAULT_BUSINESS


# --- girdi derleme -----------------------------------------------------------


def headline_of(briefing: Any) -> str:
    """Bir brifingin ``**Öne çıkan:**`` satırı (yoksa ilk anlamlı satır)."""
    from .. import reports

    try:
        return reports.extract_headline(str(getattr(briefing, "text", "") or ""))
    except Exception:  # pragma: no cover - savunma amaçlı
        return ""


def compact_input(briefing: Any, limit: int = MAX_INPUT_CHARS) -> str:
    """Bir danışmanın çıktısının karar için gereken KADARI.

    Başlık cümlesi + gövdenin başı. Tam metni taşımak tek çağrıya sığmaz ve
    karar için gerekli değildir.
    """
    text = str(getattr(briefing, "text", "") or "").strip()
    headline = headline_of(briefing)
    body = text
    if headline and headline in body:
        body = body.split(headline, 1)[1]
    body = " ".join(body.split())
    if len(body) > limit:
        body = body[:limit].rsplit(" ", 1)[0] + "…"
    parts = [part for part in (headline, body) if part]
    return " — ".join(parts)


def analyst_evidence(briefing: Any) -> str:
    """Veri Analisti'nin YAPISAL bulguları: göstergeler ve önerdiği aksiyonlar.

    Metni yeniden özetlemek yerine analistin ``report`` gövdesindeki sayıları
    okuruz; bu hem daha kısa hem de rakamı bozulmadan taşır.
    """
    payload = getattr(briefing, "report", None)
    if not isinstance(payload, dict):
        return ""
    lines: List[str] = []
    for metric in list(payload.get("key_metrics") or [])[:6]:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip()
        value = str(metric.get("value") or "").strip()
        if not label or not value:
            continue
        note = str(metric.get("note") or "").strip()
        lines.append(f"  · {label} = {value}" + (f" ({note})" if note else ""))
    actions = []
    for item in list(payload.get("action_items") or [])[:5]:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            actions.append(f"  · {text}")
    out: List[str] = []
    if lines:
        out.append("  Ölçülen göstergeler:")
        out.extend(lines)
    if actions:
        out.append("  Analistin önerdiği aksiyonlar:")
        out.extend(actions)
    return "\n".join(out)


def build_inputs_block(entries: Sequence[Tuple[str, str, str]]) -> str:
    """``(key, title, content)`` üçlülerinden istemin girdi bloğu."""
    lines: List[str] = []
    for _, title, content in entries:
        lines.append(f"[{title}]")
        lines.append(content)
        lines.append("")
    block = "\n".join(lines).strip()
    if len(block) > MAX_PROMPT_CHARS:
        block = block[:MAX_PROMPT_CHARS].rsplit("\n", 1)[0] + "\n…(kısaltıldı)"
    return block


def user_prompt(entries: Sequence[Tuple[str, str, str]]) -> str:
    """Günün karar istemi — girdiler, kapsam ve çıktı sözleşmesi."""
    forecast = setting(FORECAST_ENV)
    sla_target = setting(SLA_TARGET_ENV)
    context: List[str] = [f"İŞLETME: {business_label()}"]
    if forecast:
        context.append(f"BEKLENEN HACİM / TAHMİN: {forecast}")
    if sla_target:
        context.append(f"SLA HEDEFİ: {sla_target}")

    return (
        "\n".join(context)
        + "\n\nAşağıda BUGÜNKÜ çalıştırmada ekibinin ürettiği bulgular var. "
        "Bunları oku ve iş operasyonu adına KARAR listesi çıkar.\n\n"
        f"=== GÜNÜN GİRDİLERİ ===\n{build_inputs_block(entries)}\n"
        "=== GİRDİLER SONU ===\n\n"
        "Çıktıyı TAM OLARAK şu yapıda yaz:\n\n"
        "İlk satır: `**Öne çıkan:** <bugün verilmesi gereken EN kritik karar>` "
        "(en fazla 200 karakter).\n\n"
        + SECTION_HEADINGS[0]
        + f"\nEn fazla {MAX_DECISIONS} madde, EN ÖNEMLİSİ EN ÜSTTE. Her madde "
        "aynen şu biçimde:\n"
        + DECISION_FORMAT
        + "\nBugün KULLANICIDAN karar bekleyen maddeleri en üste koy ve "
        "başlarına `⏱️ BUGÜN:` yaz.\n\n"
        + SECTION_HEADINGS[1]
        + "\n2-3 cümle: eldeki kadro beklenen hacme yetiyor mu, önümüzdeki "
        "günlerde servis seviyesi nerede risk altında, hangi vardiya/gün. "
        "Girdilerde sayı varsa kullan; yoksa neyin ölçülemediğini söyle.\n\n"
        + SECTION_HEADINGS[2]
        + "\n2-3 cümle: biriken iş, geciken konular ve eskalasyon duruşu — "
        "neyin bekletilmesi güvenli, neyin bekletilmesi maliyetli.\n\n"
        + SECTION_HEADINGS[3]
        + "\n1-3 madde: bugün DEVREDİLEBİLECEK işler; her birinde kime "
        "devredileceği ve devredilirken verilecek tek cümlelik talimat.\n\n"
        "YAZIM: Slack Markdown, en fazla 350 kelime, doğrudan ve net Türkçe. "
        "Girdileri özetleme — karara çevir."
    )


# --- LLM'siz yol -------------------------------------------------------------


def fallback_decisions(
    entries: Sequence[Tuple[str, str, str]], analyst: Any
) -> List[Dict[str, str]]:
    """Model olmadan üretilen karar listesi.

    Analistin kendi aksiyonları zaten sahibi ve süresi belli maddelerdir;
    onları önceliklendirip başa alırız. Kalan danışmanların başlık cümleleri
    "gözden geçir ve karar ver" maddesine dönüşür — uydurma bir sonuç
    yazmadan, ne yapılacağı belli biçimde.
    """
    decisions: List[Dict[str, str]] = []
    payload = getattr(analyst, "report", None) if analyst is not None else None
    if isinstance(payload, dict):
        for item in list(payload.get("action_items") or []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            decisions.append(
                {
                    "text": f"{text} Aksiyon alınmazsa: bulgunun etkisi bir "
                    f"sonraki dönemde büyür ve düzeltme maliyeti artar.",
                    "owner": str(item.get("owner") or "Operasyon"),
                    "deadline": str(item.get("deadline") or "bugün"),
                }
            )

    for key, title, _ in entries:
        if key == "data_analyst" or len(decisions) >= MAX_DECISIONS:
            continue
        decisions.append(
            {
                "text": (
                    f"{title} bölümündeki bulguyu gözden geçir ve bir karar ver "
                    f"(uygula / ertele / devret). Aksiyon alınmazsa: bulgu "
                    f"kayda geçmez ve yarınki brifingde tekrar eder."
                ),
                "owner": "Sen",
                "deadline": "bugün",
            }
        )
    return decisions[:MAX_DECISIONS]


def fallback_narrative(
    entries: Sequence[Tuple[str, str, str]], decisions: Sequence[Dict[str, str]]
) -> str:
    """Deterministik karar listesi metni (LLM anahtarı yokken)."""
    lines = [
        f"**Öne çıkan:** Bugün {len(decisions)} karar bekliyor; "
        f"{len(entries)} danışman bulgusu değerlendirildi.",
        "",
        "_LLM sağlayıcı anahtarı yapılandırılmadığı için karar listesi "
        "sentezlenmedi, bulgulardan doğrudan türetildi "
        "(GEMINI_API_KEY veya OPENAI_API_KEY ekleyin)._",
        "",
        SECTION_HEADINGS[0],
    ]
    for item in decisions:
        lines.append(
            f"- **{item['text']}** (Son tarih: {item['deadline']}) "
            f"(Sorumlu: {item['owner']})"
        )
    lines.append("")
    lines.append(SECTION_HEADINGS[1])
    if any(key == "data_analyst" for key, _, _ in entries):
        lines.append(
            "Operasyon verisi okundu ve göstergeler yukarıdaki kararlara "
            "dayanak yapıldı; kadro–hacim karşılaştırmasının YORUMU için "
            "bir LLM sağlayıcı anahtarı gerekiyor."
        )
    else:
        lines.append(
            "Kadro ve SLA riski için sayısal değerlendirme yapılamadı: bu "
            "koşuda operasyon verisi okunmadı. DATA_ANALYST_SOURCE ile "
            "bağlarsanız kadro–hacim karşılaştırması da buraya düşer."
        )
    return "\n".join(lines)


def parse_decisions(text: str, limit: int = MAX_DECISIONS) -> List[Dict[str, str]]:
    """Model çıktısındaki karar maddelerini sahip/son tarihle ayıklar.

    Model biçimi bozarsa madde yine listeye girer; yalnızca sahip/son tarih
    boş kalır. Ayrıştırma, raporu KAYBETTİRMEZ.
    """
    out: List[Dict[str, str]] = []
    in_decisions = False
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            in_decisions = "karar" in line.casefold()
            continue
        match = _BULLET_RE.match(line)
        if not match:
            continue
        if not in_decisions and not _DEADLINE_RE.search(line):
            continue
        body = match.group(1).strip()
        owner = ""
        deadline = ""
        found = _OWNER_RE.search(body)
        if found:
            owner = found.group(1).strip()
            body = _OWNER_RE.sub("", body)
        found = _DEADLINE_RE.search(body)
        if found:
            deadline = found.group(1).strip()
            body = _DEADLINE_RE.sub("", body)
        body = body.replace("**", "").strip(" —-–·,;")
        if not body:
            continue
        out.append({"text": body, "owner": owner, "deadline": deadline})
        if len(out) >= limit:
            break
    return out


class OperationsDirectorAdvisor(Advisor):
    """İş operasyonunun sahibi: günün bulgularını karar listesine çevirir."""

    key = "operations_director"
    title = "Operasyon Direktörü"
    #: Diğer danışmanların kişisel içeriğini sentezler.
    private = True
    incremental_source = False

    def __init__(self) -> None:
        self._observed: List[Briefing] = []

    # -- sıralama kancası -------------------------------------------------
    def observe(self, briefings: Sequence[Briefing]) -> None:
        """Bu koşuda ÖNCE üretilmiş tüm brifingleri alır (kendisi hariç)."""
        self._observed = [b for b in briefings if b.key not in _SELF_KEYS]

    # -- girdiler ---------------------------------------------------------
    def _business_inputs(self) -> List[Tuple[str, str, str]]:
        """Karar listesine girecek İŞ bulguları.

        Sistem sağlığı danışmanları (:data:`SYSTEM_HEALTH_KEYS`) burada
        BİLEREK atlanır — o alan İş Analisti'nin ve iki bölümün aynı şeyi
        anlatması kullanıcı için tekrardır.
        """
        entries: List[Tuple[str, str, str]] = []
        for briefing in self._observed:
            if briefing.key in SYSTEM_HEALTH_KEYS:
                continue
            if not getattr(briefing, "ok", False):
                continue
            title = str(getattr(briefing, "title", "") or briefing.key)
            if briefing.key == "data_analyst":
                evidence = analyst_evidence(briefing)
                content = compact_input(briefing)
                if evidence:
                    content = f"{content}\n{evidence}"
            else:
                content = compact_input(briefing)
            if content.strip():
                entries.append((briefing.key, title, content))
        return entries

    def _analyst(self) -> Optional[Briefing]:
        for briefing in self._observed:
            if briefing.key == "data_analyst" and getattr(briefing, "ok", False):
                return briefing
        return None

    # -- ana yol ----------------------------------------------------------
    def _generate(self) -> Briefing:
        if not self._observed:
            return self.skipped(NO_RUN_HELP)

        entries = self._business_inputs()
        if not entries:
            return self.skipped(NO_CONTENT_HELP)

        if not llm.is_configured():
            return self._fallback(entries)

        try:
            body = llm.generate_text(SYSTEM_PROMPT, user_prompt(entries))
        except Exception as exc:
            logger.warning("operasyon direktörü LLM çağrısı başarısız: %s", exc)
            return self._fallback(entries)

        narrative = str(body or "").strip()
        if not narrative:
            return self._fallback(entries)

        decisions = parse_decisions(narrative)
        if not decisions:
            # Model biçimi tutturamadı: kararların sahibi/tarihi kaybolmasın.
            decisions = fallback_decisions(entries, self._analyst())
        return self._briefing(narrative, decisions, entries)

    # -- toplu çağrı ------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """Toplu çağrıya KATILMAZ: istemi diğerlerinin çıktısından doğar.

        ``run_batch`` bütün bölümleri hiçbir danışman çalışmadan önce toplar;
        o anda bu personanın söyleyecek bir şeyi yoktur. Kendi TEK çağrısını
        :meth:`_generate` içinde yapar.
        """
        return None

    # -- yardımcılar ------------------------------------------------------
    def _fallback(self, entries: Sequence[Tuple[str, str, str]]) -> Briefing:
        decisions = fallback_decisions(entries, self._analyst())
        return self._briefing(
            fallback_narrative(entries, decisions), decisions, entries
        )

    def _briefing(
        self,
        narrative: str,
        decisions: Sequence[Dict[str, str]],
        entries: Sequence[Tuple[str, str, str]],
    ) -> Briefing:
        briefing = self.ok(f"{narrative.strip()}\n\n{CLOSING_NOTE}")
        try:
            briefing.report = self._report_payload(narrative, decisions, entries)
        except Exception as exc:  # pragma: no cover - savunma amaçlı
            logger.warning("operasyon direktörü yapısal raporu kurulamadı: %s", exc)
        return briefing

    def _report_payload(
        self,
        narrative: str,
        decisions: Sequence[Dict[str, str]],
        entries: Sequence[Tuple[str, str, str]],
    ) -> Dict[str, Any]:
        """``ai_assistant.reports`` şemasına uyan yapısal rapor gövdesi."""
        from .. import reports

        today_count = sum(
            1
            for item in decisions
            if "bugün" in str(item.get("deadline", "")).casefold()
        )
        key_metrics = [
            {"label": "Karar sayısı", "value": str(len(decisions))},
            {"label": "Bugün karar bekleyen", "value": str(today_count)},
            {"label": "Değerlendirilen bulgu", "value": str(len(entries))},
        ]

        sections: List[Dict[str, Any]] = [
            {"title": "Karar listesi", "body": narrative.strip()},
            {
                "title": "Kaynak bulgular",
                "body": "\n".join(f"- {title}" for _, title, _ in entries),
                "table": {
                    "title": "Bu karar listesini besleyen bölümler",
                    "columns": [
                        {"key": "advisor", "label": "Danışman", "type": "text"},
                        {"key": "headline", "label": "Öne çıkan", "type": "text"},
                    ],
                    "rows": [
                        {
                            "advisor": title,
                            "headline": content.split(" — ", 1)[0][:180],
                        }
                        for _, title, content in entries
                    ],
                    "caption": "Karar listesinin dayandığı bölümler",
                    "note": (
                        "Sistem sağlığı bölümü (İş Analisti) bilerek dışarıda "
                        "bırakıldı; kapsam iş operasyonudur."
                    ),
                },
            },
        ]

        action_items = [
            {
                "text": str(item.get("text") or ""),
                "owner": str(item.get("owner") or "Operasyon"),
                "deadline": str(item.get("deadline") or "bugün"),
            }
            for item in decisions
            if str(item.get("text") or "").strip()
        ]

        headline = ""
        try:
            headline = reports.extract_headline(narrative)
        except Exception:  # pragma: no cover - savunma amaçlı
            headline = ""

        return {
            "headline": headline,
            "key_metrics": key_metrics,
            "sections": sections,
            "action_items": action_items,
            "sources": [],
        }


__all__ = [
    "CLOSING_NOTE",
    "DECISION_FORMAT",
    "MAX_DECISIONS",
    "NO_CONTENT_HELP",
    "NO_RUN_HELP",
    "OperationsDirectorAdvisor",
    "SECTION_HEADINGS",
    "SYSTEM_HEALTH_KEYS",
    "SYSTEM_PROMPT",
    "analyst_evidence",
    "build_inputs_block",
    "compact_input",
    "fallback_decisions",
    "fallback_narrative",
    "headline_of",
    "parse_decisions",
    "user_prompt",
]
