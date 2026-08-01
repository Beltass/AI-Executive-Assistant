"""Veri Analisti — otuz yıllık çağrı merkezi operasyonu okuyan analist.

Bu danışman :mod:`ai_assistant.analysis` motorunun ÜSTÜNE oturur. Motor sayıyı
üretir; buradaki persona sayının NE ANLAMA GELDİĞİNİ söyler. İkisi arasındaki
fark, bu modülün var oluş nedenidir:

* ``analysis.analyzer`` — "SLA %84,2, ilk yarıya göre 4,2 puan yukarıda".
* ``DataAnalystAdvisor`` — "SLA hedefin üzerinde ama AHT 48 sn uzadı; aynı
  kadroyla daha az çağrı karşılanıyor demektir. Bugün yapılmazsa yarınki
  yoğunluk eğrisinde kuyruk devir süresi büyür."

TASARIM KARARLARI (hepsi bilinçli):

1. **Bulgular SÜTUN SIRASINA GÖRE DEĞİL, OPERASYONEL ETKİYE göre sıralanır.**
   Motor bulguları hesaplama sırasıyla döndürür (toplam çağrı → SLA → terk →
   AHT …). Bir operasyon direktörü raporu bu sırayla okumaz: önce servis
   seviyesini bozan şeye bakar. :func:`rank_findings` üç ölçütü birleştirir —
   bulgunun tonu (kötü/uyarı önce), göstergenin operasyonel ağırlığı
   (SLA > terk > ASA > AHT > doluluk > FCR > CSAT > hacim) ve değişimin
   büyüklüğü.

2. **Her iddia dayandığı sayıyı taşır.** Sistem istemi bunu mutlak kural yapar
   ve modele YALNIZCA motorun hesapladığı kanıt bloğu verilir. Blokta olmayan
   bir sayı brifingde de olamaz.

3. **Verinin DESTEKLEMEDİĞİ şey açıkça yazılır.** :func:`unsupported_notes`
   veri kümesine bakıp neyin ölçülemediğini deterministik olarak çıkarır
   (eksik gösterge sütunları, yüksek boşluk oranı, tek dönemlik veri, neden
   kodu / temas kaydı yokluğu). Model bu listeyi genişletemez, sadece anlatır.

4. **Korelasyon nedensellik diye sunulmaz.** Motorun bulduğu ilişkiler ayrı
   bir başlıkta, "birlikte hareket ediyor, biri diğerini doğurur demek değil"
   çerçevesiyle verilir; sistem istemi nedensellik uydurmayı yasaklar.

TEK LLM ÇAĞRISI: veri yükleme ve analiz LLM'in DIŞINDA yapılır; yalnızca
yorumlama ekibin ortak toplu çağrısına (``advisors._batch``) katılır.

YAPISAL RAPOR: brifing metnine ek olarak ``briefing.report`` alanına
``ai_assistant.reports`` şeması (headline / key_metrics / sections /
action_items / sources) yazılır; böylece rapor okuma görünümünde tablo ve
grafikleriyle, Excel ve Markdown çıktısında ise aynı yapıyla görünür.

Yapılandırma (ortam değişkenleri):
    DATA_ANALYST_SOURCE            Veri kaynağı: yerel dosya yolu (.xlsx/.csv),
                                   Google E-Tablo bağlantısı ya da e-tablo kimliği.
    DATA_ANALYST_DRIVE_FOLDER_ID   Kaynak verilmediyse taranacak Drive klasörü;
                                   klasördeki EN SON değişen e-tablo kullanılır.
    DATA_ANALYST_SHEET             E-tabloda okunacak sayfa adı (boşsa ilki).
    DATA_ANALYST_LAST_DAYS         Yalnızca son N günü analiz et.
    DATA_ANALYST_SLA_TARGET        SLA hedefi (varsayılan 80).
    DATA_ANALYST_TOP_N             Kırılım tablolarında en fazla satır.
    DATA_ANALYST_QUESTION          Bu koşuda cevaplanmasını istediğin soru.

GİZLİLİK: analiz edilen tablo kurumun kendi operasyon verisidir; bu yüzden
``private = True`` — bölüm panoya yazılmaz, yalnızca Slack'te durur.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm

logger = logging.getLogger(__name__)

SOURCE_ENV = "DATA_ANALYST_SOURCE"
FOLDER_ENV = "DATA_ANALYST_DRIVE_FOLDER_ID"
SHEET_ENV = "DATA_ANALYST_SHEET"
LAST_DAYS_ENV = "DATA_ANALYST_LAST_DAYS"
SLA_TARGET_ENV = "DATA_ANALYST_SLA_TARGET"
TOP_N_ENV = "DATA_ANALYST_TOP_N"
QUESTION_ENV = "DATA_ANALYST_QUESTION"

#: Drive'da e-tablo sayılan MIME tipleri (Google E-Tablo + yüklenmiş Excel).
SPREADSHEET_MIME_TYPES = (
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
)

#: Hiçbir kaynak yapılandırılmadığında verilen TÜRKÇE kurulum açıklaması.
#: Traceback yerine ne yapılacağını söyler.
SETUP_HELP = (
    f"veri kaynağı yapılandırılmadı. Analiz için ikisinden BİRİNİ ayarlayın: "
    f"(1) {SOURCE_ENV} — yerel bir Excel/CSV dosya yolu, Google E-Tablo "
    f"bağlantısı (https://docs.google.com/spreadsheets/d/...) veya e-tablo "
    f"kimliği; (2) {FOLDER_ENV} — Drive klasör kimliği; klasördeki en son "
    f"değişen e-tablo otomatik seçilir. İsteğe bağlı: {SHEET_ENV} (sayfa adı), "
    f"{LAST_DAYS_ENV} (son N gün), {SLA_TARGET_ENV} (SLA hedefi), "
    f"{QUESTION_ENV} (bu koşuda cevaplanacak soru)."
)

#: Göstergelerin operasyonel ağırlığı — bir operasyon direktörünün bakma sırası.
#: Servis seviyesi ve terk müşteriyi ANINDA etkiler; hacim tek başına bir sorun
#: değil, diğerlerinin bağlamıdır ve en sona düşer.
IMPACT_ORDER: Tuple[str, ...] = (
    "sla",
    "abandon_rate",
    "asa",
    "aht",
    "occupancy",
    "fcr",
    "csat",
    "answered",
    "calls_total",
)

#: Ton sırası: önce operasyonu bozan, sonra uyaran, sonra iyi giden.
_TONE_RANK = {"bad": 0, "warn": 1, "good": 2, "info": 3}

#: Modelin AYNEN üreteceği alt başlıklar. Rapor bu başlıklardan bölünür.
SECTION_HEADINGS = (
    "## 🎯 Karar özeti",
    "## 📉 Etkiye göre sıralı bulgular",
    "## 🧭 Operasyonel sonuç",
    "## 🔗 Birlikte hareket edenler (nedensellik DEĞİL)",
    "## 🚧 Verinin desteklemediği şeyler",
)

SYSTEM_PROMPT = (
    "Sen otuz yıldır çağrı merkezi operasyonu yönetmiş, aynı zamanda Excel ve "
    "iş zekâsı raporlamasında ustalaşmış kıdemli bir veri analistisin. "
    "Türkçe yazıyorsun ve karşındaki kişi bir operasyon direktörü — ona "
    "sayıyı değil, sayının OPERASYONDA NE DEMEK OLDUĞUNU anlatırsın.\n\n"
    "DİLİN: vardiya planlama, doluluk–verimlilik dengesi, çağrı yoğunluk "
    "eğrisi, kuyruk devir süresi, temsilci bazlı sapma, SLA erozyonu, "
    "terk–bekleme ilişkisi, ilk temasta çözüm, kadro yeterliliği, mola "
    "dağılımı, geri arama (callback) tamponu. Bu kavramları YERİNDE kullan; "
    "süslemek için değil, mekanizmayı anlatmak için.\n\n"
    "İŞİN YORUMLAMAK, SAYI TEKRARLAMAK DEĞİL. Her bulguda üç soruyu sırayla "
    "yanıtla: (1) gösterge NEDEN bu yöne gitti — veriden okunabilen "
    "mekanizma; (2) OPERASYONEL SONUCU ne — kadro, kuyruk, müşteri ve "
    "temsilci tarafında bugün ne değişir; (3) NE YAPILMALI — somut, sahibi "
    "belli, bugün başlatılabilir bir hamle.\n\n"
    "MUTLAK KURALLAR:\n"
    "1. SAYI UYDURMA. Yalnızca sana verilen KANIT bloğundaki rakamları "
    "kullan. Blokta olmayan bir oran, süre veya adet cümlene giremez.\n"
    "2. HER İDDİA DAYANDIĞI SAYIYI TAŞISIN. 'AHT uzuyor' değil, 'AHT 4 dk "
    "55 sn; ilk yarıya göre 48 sn uzun' de. Sayısız cümle kurma.\n"
    "3. NEDENSELLİK UYDURMA. İki gösterge birlikte hareket ediyorsa 'birlikte "
    "hareket ediyor' de, 'buna yol açtı' DEME. Bir nedeni ancak veri "
    "gösteriyorsa öne sür; göstermiyorsa 'olası açıklamalar' diye ve "
    "'veriden doğrulanamıyor' notuyla ver.\n"
    "4. VERİNİN DESTEKLEMEDİĞİNİ SÖYLE. Sana verilen 'VERİNİN SINIRLARI' "
    "listesini olduğu gibi aktar ve genişletme; bu listede olmayan bir "
    "eksikliği kendin icat etme.\n"
    "5. SIRALAMAYI BOZMA. Bulgular sana ETKİ SIRASIYLA verildi; aynı sırayla "
    "yaz. Sütun sırası veya alfabetik sıra değil, operasyonel etki sırası.\n"
    "6. Emin olmadığın hiçbir şeyi kesinlik diliyle söyleme; 'bilinmiyor' "
    "kabul edilebilir bir cevaptır."
)

#: Her iki yolda da (LLM'li ve LLM'siz) brifingin sonuna eklenen deterministik
#: not. Raporun neye dayandığını ve neye dayanmadığını okuyucuya garanti eder.
CAVEAT = (
    "📌 Yöntem notu: Buradaki tüm rakamlar yukarıda adı geçen veri kümesinden "
    "hesaplandı; yorumlar bu rakamlara dayanır. İlişki (korelasyon) bulguları "
    "birlikte hareket ettiğini gösterir, birinin diğerine YOL AÇTIĞINI "
    "göstermez — nedensellik için deney veya kontrollü karşılaştırma gerekir.\n"
    "🔎 Kaynak dosya değiştiğinde rapor da değişir; karar öncesinde verinin "
    "kapsandığı dönemi ve boşluk oranlarını kontrol edin."
)


# --- yapılandırma ------------------------------------------------------------


def _int_setting(name: str) -> Optional[int]:
    raw = setting(name)
    if not raw:
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _float_setting(name: str) -> Optional[float]:
    raw = setting(name)
    if not raw:
        return None
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


class SourceMissing(RuntimeError):
    """Yapılandırılmış bir veri kaynağı yok — ``skipped`` sebebi."""


class SourceBroken(RuntimeError):
    """Kaynak yapılandırılmış ama okunamadı — ``failed`` sebebi."""


def newest_drive_spreadsheet(folder_id: str, client: Any = None) -> Dict[str, str]:
    """Drive klasöründeki EN SON değişen e-tabloyu döner.

    ``client`` verilirse (testler) o kullanılır. Google kimliği yoksa ya da
    çağrı patlarsa :class:`SourceBroken` fırlatır — traceback değil, Türkçe
    tek cümle.
    """
    if client is None:
        try:
            from ..integrations.google_drive import DriveClient

            client = DriveClient()
        except Exception as exc:
            raise SourceBroken(
                f"Drive klasörü okunamadı (Google kimlik doğrulaması "
                f"tamamlanmamış olabilir): {exc}"
            ) from exc
    try:
        files = client.list_documents_in_folder(folder_id)
    except Exception as exc:
        raise SourceBroken(f"Drive klasörü listelenemedi: {exc}") from exc

    sheets = [
        item
        for item in (files or [])
        if str(item.get("mimeType") or "") in SPREADSHEET_MIME_TYPES
    ]
    if not sheets:
        raise SourceBroken(
            f"'{folder_id}' klasöründe e-tablo bulunamadı. Klasör kimliğini ve "
            f"paylaşım iznini kontrol edin."
        )
    # list_documents_in_folder zaten modifiedTime'a göre azalan sıralı döner;
    # yine de kendimiz sıralarız: sıralama garantisine yaslanmak kırılgandır.
    sheets.sort(key=lambda item: str(item.get("modifiedTime") or ""), reverse=True)
    newest = sheets[0]
    return {
        "id": str(newest.get("id") or ""),
        "name": str(newest.get("name") or ""),
        "modified": str(newest.get("modifiedTime") or ""),
        "link": str(newest.get("webViewLink") or ""),
    }


def resolve_source(client: Any = None) -> Dict[str, str]:
    """Bu koşuda analiz edilecek kaynağı bulur.

    Öncelik: açıkça verilen ``DATA_ANALYST_SOURCE`` → Drive klasöründeki en
    son e-tablo. Hiçbiri yoksa :class:`SourceMissing`.
    """
    explicit = setting(SOURCE_ENV)
    if explicit:
        return {"source": explicit, "name": "", "link": "", "note": ""}

    folder = setting(FOLDER_ENV)
    if folder:
        newest = newest_drive_spreadsheet(folder, client=client)
        note = f"Drive klasöründeki en son değişen e-tablo seçildi: {newest['name']}"
        if newest["modified"]:
            note += f" (son değişiklik {newest['modified']})"
        return {
            "source": newest["id"],
            "name": newest["name"],
            "link": newest["link"],
            "note": note + ".",
        }

    raise SourceMissing(SETUP_HELP)


# --- bulguların etkiye göre sıralanması --------------------------------------


def impact_rank(finding: Any) -> Tuple[int, int, float]:
    """Bir bulgunun sıralama anahtarı: ton → gösterge ağırlığı → değişim."""
    tone = _TONE_RANK.get(str(getattr(finding, "tone", "") or ""), 4)
    key = str(getattr(finding, "key", "") or "")
    try:
        weight = IMPACT_ORDER.index(key)
    except ValueError:
        weight = len(IMPACT_ORDER)
    delta = getattr(finding, "delta_pct", None)
    magnitude = abs(float(delta)) if isinstance(delta, (int, float)) else 0.0
    return (tone, weight, -magnitude)


def rank_findings(findings: Sequence[Any]) -> List[Any]:
    """Bulguları OPERASYONEL ETKİYE göre sıralar (sütun sırasına göre değil)."""
    return sorted(findings, key=impact_rank)


# --- verinin sınırları -------------------------------------------------------

#: Bir çağrı merkezi operasyonunda karar için beklenen göstergeler. Eksik olan
#: her biri, raporun CEVAPLAYAMAYACAĞI soruyu tanımlar.
#:
#: Anahtarlar ÇOĞUL çünkü bir gösterge iki adla görünebilir: ham sütun etiketi
#: (``abandon`` — "Terk Edilen") ve motorun türettiği bulgu anahtarı
#: (``abandon_rate`` — terk ORANI). İkisinden biri varsa gösterge vardır.
_EXPECTED_METRICS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("sla",), "servis seviyesi (SLA) tutturma oranı"),
    (("abandon", "abandon_rate"), "terk oranı"),
    (("aht",), "ortalama görüşme süresi (AHT)"),
    (("asa",), "ortalama cevaplama süresi (ASA) / bekleme"),
    (("occupancy",), "doluluk"),
    (("fcr",), "ilk temasta çözüm (FCR)"),
    (("csat",), "müşteri memnuniyeti"),
)

#: Bu oranın üzerinde boşluk taşıyan sütun, üzerine karar kurulacak sütun değildir.
NULL_RATE_WARNING = 0.15


def unsupported_notes(result: Any) -> List[str]:
    """Verinin DESTEKLEMEDİĞİ şeyler — deterministik, modelden bağımsız.

    Bu liste modele "olduğu gibi aktar, genişletme" diye verilir. Amaç, eksik
    bir ölçünün sessizce yorumla doldurulmasını engellemek.
    """
    notes: List[str] = []
    dataset = getattr(result, "dataset", None)
    if dataset is None:
        return notes

    # Bir gösterge ya ham sütun olarak ya da motorun türettiği bulgu olarak
    # vardır; ikisine de bakmazsak "terk oranı yok" gibi yanlış bir sınır yazarız.
    present = {
        str(getattr(column, "metric", "") or "")
        for column in getattr(dataset, "columns", [])
    }
    present |= {
        str(getattr(finding, "key", "") or "")
        for finding in getattr(result, "findings", [])
    }
    missing = [
        label for keys, label in _EXPECTED_METRICS if not present.intersection(keys)
    ]
    if missing:
        notes.append(
            "Veride şu gösterge(ler) YOK, bu yüzden hakkında hüküm kurulamaz: "
            + ", ".join(missing)
            + "."
        )

    sparse = [
        f"{column.name} (%{column.null_rate * 100:.0f} boş)"
        for column in getattr(dataset, "columns", [])
        if getattr(column, "null_rate", 0.0) > NULL_RATE_WARNING
    ]
    if sparse:
        notes.append(
            "Boşluk oranı yüksek sütun(lar) — bu sütunlara dayanan yorum "
            "zayıftır: " + ", ".join(sparse[:5]) + "."
        )

    date_columns = list(getattr(dataset, "date_columns", lambda: [])())
    if not date_columns:
        notes.append(
            "Veride tarih sütunu yok: eğilim, dönem karşılaştırması ve çağrı "
            "yoğunluk eğrisi çıkarılamaz; rakamlar tek bir kesitin özetidir."
        )

    if not getattr(result, "series", None):
        notes.append(
            "Zaman serisi üretilemedi: 'artıyor/azalıyor' türü ifadeler dönem "
            "karşılaştırmasına değil, yalnızca mevcut kesite dayanır."
        )

    reason_like = any(
        str(getattr(column, "metric", "") or "") == "reason"
        for column in getattr(dataset, "columns", [])
    )
    if not reason_like:
        notes.append(
            "Çağrı neden/konu kodu yok: AHT ve tekrar temas için KÖK NEDEN "
            "veriden çıkarılamaz; kök neden ancak çağrı dinleme veya konu "
            "kırılımı eklenerek söylenebilir."
        )

    notes.append(
        "Veri gözlemseldir: hiçbir bulgu nedensellik kanıtı değildir; "
        "müdahalenin etkisi ancak öncesi-sonrası kontrollü karşılaştırmayla "
        "ölçülebilir."
    )
    return notes


# --- kanıt bloğu -------------------------------------------------------------


def evidence_block(result: Any, findings: Sequence[Any]) -> str:
    """Modele verilen TEK sayı kaynağı: hesaplanmış rakamlar, etki sırasıyla."""
    from ..analysis.analyzer import format_value

    dataset = result.dataset
    lines: List[str] = [
        f"VERİ KÜMESİ: {dataset.name} — {dataset.summary_tr()}",
        f"KAYNAK: {dataset.source or dataset.name}",
    ]
    request = getattr(result, "request", None)
    if request is not None:
        window = request.window_label()
        if window:
            lines.append(f"DÖNEM SÜZGECİ: {window}")
        if request.question:
            lines.append(f"CEVAPLANACAK SORU: {request.question}")

    lines.append("")
    lines.append("BULGULAR (ETKİ SIRASIYLA — bu sırayı koru):")
    for index, finding in enumerate(findings, start=1):
        parts = [f"{index}. {finding.metric}: {finding.display}"]
        if finding.baseline is not None:
            parts.append(
                f"karşılaştırma ({finding.baseline_label}) = "
                f"{format_value(finding.baseline, finding.unit)}"
            )
        if isinstance(finding.delta_pct, (int, float)):
            parts.append(f"değişim %{finding.delta_pct:+.1f}")
        parts.append(f"yön {finding.direction}, durum {finding.tone}")
        lines.append(" | ".join(parts))
        if finding.interpretation:
            lines.append(f"   motorun ham notu: {finding.interpretation}")

    for pivot in getattr(result, "pivots", [])[:3]:
        if not pivot.rows or not pivot.measures:
            continue
        measure = pivot.measures[0]
        dimension = pivot.dimensions[0]
        best, worst = pivot.rows[0], pivot.rows[-1]
        lines.append(
            f"KIRILIM — {pivot.title} ({measure.title()}): en yüksek "
            f"{best.get(dimension)} = {format_value(best.get(measure.key), measure.unit)}; "
            f"en düşük {worst.get(dimension)} = "
            f"{format_value(worst.get(measure.key), measure.unit)} "
            f"({len(pivot.rows)} satır)"
        )

    for series in getattr(result, "series", [])[:3]:
        if series.change_pct is None:
            continue
        lines.append(
            f"SERİ — {series.title} ({series.period}): {len(series.points)} dönem, "
            f"ikinci yarı ilk yarıya göre %{series.change_pct:+.1f} ({series.trend})"
        )

    for report in getattr(result, "outliers", []):
        if report.count:
            lines.append(
                f"AYKIRI — {report.column}: {report.count}/{report.total} ölçüm "
                f"normal bandın ({format_value(report.lower, report.unit)} – "
                f"{format_value(report.upper, report.unit)}) dışında"
            )

    correlations = getattr(result, "correlations", [])
    if correlations:
        lines.append("")
        lines.append(
            "İLİŞKİLER (yalnızca BİRLİKTE HAREKET — neden-sonuç DEĞİL):"
        )
        for item in correlations:
            lines.append(
                f"- {item.left} ↔ {item.right}: r = {item.r:+.2f} "
                f"({item.strength}, {item.pairs} gözlem)"
            )

    notes = list(getattr(result, "notes", []))
    if notes:
        lines.append("")
        lines.append("MOTOR NOTLARI: " + " ".join(notes[:5]))

    return "\n".join(lines)


def user_prompt(result: Any, findings: Sequence[Any], limits: Sequence[str]) -> str:
    """Günün brifing tarifi — kanıt bloğu ve sınırlar dâhil."""
    return (
        "Aşağıdaki KANIT bloğu, operasyon verisinden HESAPLANMIŞ rakamlardır. "
        "Yalnızca bunları kullanarak bir yönetici brifingi yaz.\n\n"
        f"=== KANIT ===\n{evidence_block(result, findings)}\n=== KANIT SONU ===\n\n"
        "=== VERİNİN SINIRLARI (olduğu gibi aktar, genişletme) ===\n"
        + "\n".join(f"- {note}" for note in limits)
        + "\n=== SINIRLAR SONU ===\n\n"
        "Brifingi TAM OLARAK şu yapıda yaz:\n\n"
        "İlk satır: `**Öne çıkan:** <tek cümlelik ana bulgu ve sayısı>` "
        "(en fazla 200 karakter).\n\n"
        + SECTION_HEADINGS[0]
        + "\nÜç cümle: bugün operasyonda ne oldu, bu neyi tehdit ediyor ya da "
        "neyi mümkün kılıyor, bugün hangi karar bekleniyor. Her cümlede en az "
        "bir sayı geçsin.\n\n"
        + SECTION_HEADINGS[1]
        + "\nKANIT bloğundaki sırayı KORUYARAK her bulgu için kısa bir madde: "
        "**<gösterge> — <değer>** ile başla, sonra (a) veriden okunan "
        "mekanizma, (b) operasyonel sonucu (kadro, kuyruk, müşteri, temsilci), "
        "(c) tek cümlelik hamle. Sayıyı tekrar etmekle yetinme — yorumla.\n\n"
        + SECTION_HEADINGS[2]
        + "\n2-4 madde: bu tablo vardiya planlamasına, doluluk–verimlilik "
        "dengesine ve çağrı yoğunluk eğrisine ne yapıyor. Temsilci bazlı sapma "
        "varsa kırılım sayılarıyla söyle; isimden çok örüntüyü anlat.\n\n"
        + SECTION_HEADINGS[3]
        + "\nKANIT'taki ilişkileri anlat ve her birinde AÇIKÇA 'birlikte "
        "hareket ediyor; hangisinin diğerini doğurduğu bu veriden "
        "SÖYLENEMEZ' de. Nedensellik iddiası kurma; ayırt etmek için hangi ek "
        "veriye ihtiyaç olduğunu yaz. İlişki verilmediyse bu bölümde bunu "
        "yaz.\n\n"
        + SECTION_HEADINGS[4]
        + "\nSINIRLAR listesindeki maddeleri madde madde ve okunur biçimde "
        "aktar; her birinin yanına 'bu yüzden şu soruyu cevaplayamıyoruz' "
        "notunu ekle.\n\n"
        "## ✅ Bugünün görevi\n"
        "Bugün 15-30 dakikada yapılabilecek TEK somut kontrol; sonunda "
        "`(Son tarih: bugün) (Sorumlu: Operasyon)` biçiminde sahibini ve "
        "süresini yaz.\n\n"
        "YAZIM: Slack'te okunacak Markdown, 350-550 kelime, akıcı Türkçe. "
        "Klişe yok, dolgu cümle yok, sayısız iddia yok."
    )


# --- yapısal rapor -----------------------------------------------------------


def build_key_metrics(findings: Sequence[Any], limit: int = 4) -> List[Dict[str, Any]]:
    """Metrik şeridi — ETKİ sırasının ilk maddeleri."""
    from ..analysis.analyzer import format_value

    out: List[Dict[str, Any]] = []
    for finding in list(findings)[:limit]:
        note = ""
        if finding.baseline is not None and finding.delta is not None:
            note = (
                f"{finding.baseline_label} "
                f"{format_value(finding.delta, finding.unit)} fark"
            )
        out.append(
            {
                "label": finding.metric,
                "value": finding.display,
                "trend": finding.direction
                if finding.direction in ("up", "down", "flat")
                else "",
                "note": note,
                "spark": [float(v) for v in list(finding.spark)[-12:]],
            }
        )
    return out


def build_action_items(findings: Sequence[Any], result: Any) -> List[Dict[str, str]]:
    """Aksiyonlar — yalnızca operasyonu BOZAN bulgulardan, etki sırasıyla."""
    recipes = {
        "sla": "SLA erozyonu: en düşük servis seviyeli saat dilimleri için "
               "vardiya takviyesi planla, kuyruk önceliklerini yeniden kur.",
        "abandon_rate": "Terk–bekleme ilişkisini kır: geri arama tamponu aç, "
                        "kuyruk anonsunu ve yoğun saat kadrosunu gözden geçir.",
        "asa": "Kuyruk devir süresi uzuyor: yoğun saatlerde ek kaynak ve "
               "taşma (overflow) kuralını devreye al.",
        "aht": "AHT uzaması: en uzun görüşme konularını ayıkla, bilgi tabanını "
               "ve yönlendirme akışını bu konular için güncelle.",
        "occupancy": "Doluluk–verimlilik dengesi bozuk: mola dağılımını ve "
                     "kadro büyüklüğünü yeniden hesapla.",
        "fcr": "İlk temasta çözüm düşük: tekrar temas nedenlerini sınıflandır, "
               "temsilci yetki sınırını genişlet.",
        "csat": "Memnuniyet geriliyor: düşük puanlı çağrıları dinleyip koçluk "
                "konularını çıkar.",
    }
    actions: List[Dict[str, str]] = []
    for finding in findings:
        if finding.tone not in ("bad", "warn"):
            continue
        text = recipes.get(finding.key) or (
            f"{finding.metric} istenmeyen yönde ({finding.display}). Nedenini "
            f"kırılım tablolarından ayıkla ve sorumlu ata."
        )
        actions.append(
            {
                "text": f"{text} Dayanak: {finding.metric} = {finding.display}.",
                "owner": "Operasyon",
                "deadline": "bugün",
            }
        )

    for report in getattr(result, "outliers", []):
        if report.count and report.examples:
            actions.append(
                {
                    "text": (
                        f"{report.column} için {report.count} aykırı ölçümü tek tek "
                        f"doğrula: veri hatası mı, gerçek bir operasyon olayı mı."
                    ),
                    "owner": "Raporlama",
                    "deadline": "bu hafta",
                }
            )
            break
    return actions[:12]


def build_sources(result: Any, link: str = "") -> List[Dict[str, str]]:
    """Raporun dayandığı kaynak — varsa e-tablonun kendisi."""
    dataset = result.dataset
    url = link
    if not url and getattr(dataset, "source_kind", "") == "google_sheet":
        source_id = getattr(dataset, "source_id", "")
        if source_id:
            url = f"https://docs.google.com/spreadsheets/d/{source_id}"
    if not url:
        return []
    return [
        {
            "title": dataset.name or "Kaynak e-tablo",
            "url": url,
            "note": "Bu raporun dayandığı ham veri.",
        }
    ]


def build_report_payload(
    result: Any,
    findings: Sequence[Any],
    narrative: str,
    limits: Sequence[str],
    link: str = "",
) -> Dict[str, Any]:
    """``ai_assistant.reports`` şemasına uyan yapısal rapor gövdesi.

    Analistin YORUMU ilk bölümdür; ardından motorun ürettiği tablo/grafikli
    bölümler gelir, en sona verinin sınırları eklenir. Böylece aynı belge hem
    okuma görünümünde hem Excel/Markdown çıktısında tam görünür.
    """
    from ..analysis.web_report import build_sections

    sections: List[Dict[str, Any]] = [
        {"title": "Analist yorumu", "body": narrative.strip()}
    ]
    try:
        for section in build_sections(result):
            payload: Dict[str, Any] = {"title": section.title, "body": section.body}
            if section.table:
                payload["table"] = section.table
            if section.chart:
                payload["chart"] = section.chart
            sections.append(payload)
    except Exception as exc:  # pragma: no cover - savunma amaçlı
        logger.warning("analiz bölümleri kurulamadı: %s", exc)

    sections.append(
        {
            "title": "Verinin desteklemediği şeyler",
            "body": "\n".join(f"- {note}" for note in limits),
        }
    )

    headline = str(getattr(result, "headline", "") or "").strip()
    return {
        "headline": headline,
        "key_metrics": build_key_metrics(findings),
        "sections": sections,
        "action_items": build_action_items(findings, result),
        "sources": build_sources(result, link=link),
    }


# --- LLM'siz yol -------------------------------------------------------------


def offline_narrative(result: Any, findings: Sequence[Any], limits: Sequence[str]) -> str:
    """LLM anahtarı yokken üretilen deterministik Türkçe brifing.

    Veri VAR ama yorumlayacak model yok: sayıları etki sırasıyla, motorun
    kendi Türkçe yorum cümleleriyle veririz. Bu bir analist yorumu değildir ve
    metin bunu açıkça söyler — yanlış izlenim vermek, eksik bilgiden kötüdür.
    """
    lines: List[str] = []
    headline = str(getattr(result, "headline", "") or "").strip()
    lines.append(f"**Öne çıkan:** {headline or 'Veri analizi tamamlandı.'}")
    lines.append("")
    lines.append(
        "_LLM sağlayıcı anahtarı yapılandırılmadığı için aşağıdaki bölüm "
        "analist YORUMU değil, motorun hesapladığı bulguların etki sırasıyla "
        "listesidir (GEMINI_API_KEY veya OPENAI_API_KEY ekleyin)._"
    )
    lines.append("")
    lines.append(f"**Kapsam:** {result.dataset.summary_tr()}")
    lines.append("")
    lines.append("## 📉 Etkiye göre sıralı bulgular")
    for finding in findings:
        lines.append(f"- **{finding.metric} — {finding.display}**: {finding.interpretation}")

    correlations = list(getattr(result, "correlations", []))
    if correlations:
        lines.append("")
        lines.append("## 🔗 Birlikte hareket edenler (nedensellik DEĞİL)")
        for item in correlations:
            lines.append(
                f"- {item.left} ↔ {item.right}: r = {item.r:+.2f} ({item.strength}). "
                f"Birlikte hareket ediyorlar; hangisinin diğerini doğurduğu bu "
                f"veriden söylenemez."
            )

    lines.append("")
    lines.append("## 🚧 Verinin desteklemediği şeyler")
    for note in limits:
        lines.append(f"- {note}")
    return "\n".join(lines)


class DataAnalystAdvisor(Advisor):
    """Veri analisti: motorun sayısını operasyon diline çeviren persona."""

    key = "data_analyst"
    title = "Veri Analisti (Çağrı Merkezi Operasyonu)"
    #: Analiz edilen tablo kurumun kendi operasyon verisidir.
    private = True
    #: Kaynak tablo gün içinde büyüyebilir, ama bir koşuda "yeni bulgu" sayımı
    #: yapmıyoruz; artımlı koşularda sessiz kalır.
    incremental_source = False

    def __init__(self) -> None:
        self._prepared = False
        self._result: Any = None
        self._findings: List[Any] = []
        self._limits: List[str] = []
        self._link: str = ""
        self._note: str = ""
        self._error: Optional[BaseException] = None

    # -- veri hazırlığı (LLM'in DIŞINDA) ---------------------------------
    def _prepare(self) -> None:
        """Kaynağı bul, yükle, analiz et. Hata fırlatmaz; ``_error``a yazar."""
        if self._prepared:
            return
        self._prepared = True
        try:
            self._run_analysis()
        except (SourceMissing, SourceBroken) as exc:
            self._error = exc
        except Exception as exc:  # veri motorunun her hatası dâhil
            self._error = SourceBroken(str(exc))

    def _run_analysis(self) -> None:
        from ..analysis.analyzer import AnalysisRequest, analyze
        from ..analysis.dataset import DatasetError, load_any

        found = resolve_source()
        self._link = found.get("link", "")
        self._note = found.get("note", "")

        try:
            dataset = load_any(found["source"], sheet=setting(SHEET_ENV))
        except DatasetError as exc:
            raise SourceBroken(str(exc)) from exc

        request = AnalysisRequest(
            last_days=_int_setting(LAST_DAYS_ENV),
            question=setting(QUESTION_ENV),
        )
        top_n = _int_setting(TOP_N_ENV)
        if top_n:
            request.top_n = top_n
        sla_target = _float_setting(SLA_TARGET_ENV)
        if sla_target is not None:
            request.sla_target = sla_target

        result = analyze(dataset, request)
        if not result.findings and not result.pivots:
            raise SourceBroken(
                f"'{dataset.name}' okundu ({dataset.summary_tr()}) ama analiz "
                f"edilecek gösterge bulunamadı. Sayısal sütun içeren bir sayfa "
                f"seçin ya da {SHEET_ENV} ile sayfa adını verin."
            )

        self._result = result
        self._findings = rank_findings(result.findings)
        self._limits = unsupported_notes(result)

    # -- ana yol ---------------------------------------------------------
    def _generate(self) -> Briefing:
        self._prepare()
        if isinstance(self._error, SourceMissing):
            return self.skipped(str(self._error))
        if self._error is not None:
            return self.failed(str(self._error))

        if not llm.is_configured():
            return self._briefing(
                offline_narrative(self._result, self._findings, self._limits)
            )

        try:
            body = llm.generate_text(
                SYSTEM_PROMPT, user_prompt(self._result, self._findings, self._limits)
            )
        except Exception as exc:
            # Sayılar zaten hesaplandı — modeli kaybetmek raporu kaybetmek değil.
            logger.warning("veri analisti LLM çağrısı başarısız: %s", exc)
            return self._briefing(
                offline_narrative(self._result, self._findings, self._limits)
            )

        return self.briefing_from_batch(body)

    # -- toplu çağrı -----------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """Yorumlama ekibin TEK toplu çağrısına katılır; veri hazırlığı katılmaz."""
        if not llm.is_configured():
            return None
        self._prepare()
        if self._error is not None or self._result is None:
            return None
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt(self._result, self._findings, self._limits),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        self._prepare()
        if self._error is not None or self._result is None:
            return self.skipped(str(self._error or SETUP_HELP))
        return self._briefing(text.strip())

    # -- yardımcılar -----------------------------------------------------
    def _briefing(self, narrative: str) -> Briefing:
        """Metni yapısal rapor gövdesiyle birlikte bir brifinge sarar."""
        parts = [narrative.strip()]
        if self._note:
            parts.append(f"🗂️ {self._note}")
        parts.append(CAVEAT)
        briefing = self.ok("\n\n".join(part for part in parts if part))
        try:
            briefing.report = build_report_payload(
                self._result, self._findings, narrative, self._limits, link=self._link
            )
        except Exception as exc:  # pragma: no cover - savunma amaçlı
            logger.warning("veri analisti yapısal raporu kurulamadı: %s", exc)
        return briefing


__all__ = [
    "CAVEAT",
    "DataAnalystAdvisor",
    "IMPACT_ORDER",
    "SECTION_HEADINGS",
    "SETUP_HELP",
    "SYSTEM_PROMPT",
    "SourceBroken",
    "SourceMissing",
    "build_action_items",
    "build_key_metrics",
    "build_report_payload",
    "evidence_block",
    "impact_rank",
    "newest_drive_spreadsheet",
    "offline_narrative",
    "rank_findings",
    "resolve_source",
    "unsupported_notes",
    "user_prompt",
]
