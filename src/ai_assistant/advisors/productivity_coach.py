"""Verimlilik Koçu — günün SAAT ve ENERJİ mimarisi.

Kadroda taahhüt takibi zaten var (``executive_coaching``: "ne söz verdin, ne
oldu"). Eksik olan ondan ÖNCEKİ soruydu: o sözlerin sığacağı gün nasıl
kurulur? Bu bölüm işin İÇERİĞİYLE değil, işin YERLEŞTİĞİ ZAMANLA ilgilenir.

NE YAPAR
--------
1. Haftanın odak blok mimarisini kurar: derin iş nereye, sığ iş nereye,
   toplantılar hangi kuşağa toplanır, tampon nerede durur.
2. Enerji eğrisini işin türüyle eşler — zirve saatlere yaratıcı/analitik iş,
   düşüş saatlerine mekanik iş.
3. Günün iskeletini somut saat aralıklarıyla verir ve bir tane ölçülebilir
   "bu hafta değiştireceğim tek şey" bırakır.

SINIR — ``executive_coaching`` DEĞİLDİR. Yönetici koçu TAAHHÜT takip eder
("dün söz verdiğin şey ne oldu, engel neydi, kazanımı kutlayalım") ve liderlik
gelişimi işler. Bu bölüm ise taahhüdün İÇERİĞİNE hiç karışmaz: yalnızca zamanın
ve enerjinin nasıl bölüneceğini söyler. Bir işin yapılıp yapılmadığı oranın
konusu, o işin güne nereye konacağı buranın konusudur. İki bölüm birbirinin
maddesini tekrar etmemelidir.

TETİKLEYİCİ: ``weekly``. Gün mimarisi günden güne değişmez; her sabah yeniden
"odak bloğu kur" demek hem kotayı hem kullanıcının dikkatini boşa harcar.
Haftada bir kurulan iskelet, hafta boyunca uygulanır.

TEMİZ DEVREDİLME: model anahtarı yoksa bölüm ``skipped`` döner. Kullanıcının
takvimini OKUMAZ ve okumuş gibi de yapmaz; "saat 14:00'te şu toplantın var"
diyemez, çünkü o veri bu bölüme hiç verilmiyor.

Configuration (via environment):
    PRODUCTIVITY_COACH_PEAK_HOURS   Kullanıcının en verimli saat aralığı
                                    (örn. "09:00-12:00"). Tanımsızsa koç
                                    genel bir enerji eğrisi varsayar ve bunu
                                    açıkça söyler.
    PRODUCTIVITY_COACH_CONSTRAINTS  Değiştirilemez kısıtlar, virgülle ayrılmış
                                    (örn. "her gün 10:00 ekip toplantısı").
"""

from __future__ import annotations

from typing import List

from ..config import setting
from ._llm_base import RICH_BRIEFING_GUIDE, LLMAdvisor

PEAK_HOURS_ENV = "PRODUCTIVITY_COACH_PEAK_HOURS"
CONSTRAINTS_ENV = "PRODUCTIVITY_COACH_CONSTRAINTS"

SYSTEM_PROMPT = (
    "Sen bir üst düzey yöneticinin verimlilik koçusun. Uzmanlık alanın DAR ve "
    "nettir: zaman ve enerji yönetimi, odak blokları, günün ve haftanın nasıl "
    "yapılandırılacağı. Türkçe yazıyorsun.\n\n"
    "KAPSAMIN NE DEĞİL: hedef koymak, taahhüt takibi, 'dün söz verdiğin iş ne "
    "oldu' hesabı ve liderlik gelişimi SENİN İŞİN DEĞİL — onları başka bir "
    "danışman yapıyor. Sen işin İÇERİĞİNİ değil, işin ZAMANDAKİ YERİNİ "
    "tasarlarsın. Bir maddeye 'şunu yap' diye başlıyorsan durup sor: bu bir "
    "zaman mimarisi kararı mı, yoksa başkasının alanına mı girdim?\n\n"
    "SESİN: net, kısa cümleli, uygulanabilir. Motivasyon sloganı yok. Her "
    "öneri bir saate, bir süreye ya da bir sıraya bağlanır.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: kullanıcının takvimini, toplantılarını, "
    "görevlerini ya da geçmiş haftasını GÖRMÜYORSUN. Somut bir randevu, bir "
    "kişi adı ya da bir iş adı uydurma. Yalnızca sana verilen kısıtları kullan; "
    "kalan her şeyi 'kendi takviminize göre yerleştirin' diye şablon olarak ver."
)


def _peak_hours() -> str:
    return (setting(PEAK_HOURS_ENV) or "").strip()


def constraints() -> List[str]:
    """Virgülle ayrılmış değiştirilemez kısıtlar; tanımsızsa boş liste."""
    raw = setting(CONSTRAINTS_ENV) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def context_block() -> str:
    """Modele verilen kişiselleştirme bloğu — yoksa 'bilinmiyor' der."""
    peak = _peak_hours()
    limits = constraints()
    lines = []
    if peak:
        lines.append(f"En verimli saat aralığı: {peak}")
    else:
        lines.append(
            "En verimli saat aralığı BİLİNMİYOR. Varsayılan bir enerji eğrisi "
            "(sabah zirve, öğleden sonra düşüş) kullan ve bunun bir VARSAYIM "
            "olduğunu tek cümleyle söyle."
        )
    if limits:
        lines.append("Değiştirilemez kısıtlar: " + "; ".join(limits))
    else:
        lines.append(
            "Değiştirilemez kısıt bildirilmedi; iskeleti kısıtsız kur ama "
            "kullanıcıya kendi sabit toplantılarını nereye oturtacağını göster."
        )
    return "\n".join(lines)


class ProductivityCoachAdvisor(LLMAdvisor):
    """Haftanın odak blok mimarisini ve enerji planını kurar."""

    key = "productivity_coach"
    title = "Verimlilik Koçu (Odak Blokları · Enerji Yönetimi)"
    #: Takvim okumaz, kişisel veri taşımaz: panoya yazılabilir.
    private = False
    #: Gün mimarisi iki koşu arasında değişmez; artımlı koşularda sessiz kalır.
    incremental_source = False

    system_prompt = SYSTEM_PROMPT

    @property  # type: ignore[override]
    def user_prompt(self) -> str:
        return (
            "Bu HAFTA için bir zaman ve enerji mimarisi kur. Bölümler bu "
            "sırayla olsun:\n\n"
            "*🧱 Haftanın iskeleti*: haftayı kuşaklara böl — derin iş kuşağı, "
            "toplantı kuşağı, sığ iş (mail, onay, idari) kuşağı. Her kuşak için "
            "hangi gün(ler) ve kaçar saat olduğunu yaz; neden orada olduğunu "
            "tek cümleyle gerekçelendir.\n\n"
            "*⚡ Enerji eşleşmesi*: hangi iş türü hangi saatte yapılırsa daha "
            "ucuza mal olur? Zirve saatlere ne konur, düşüş saatlerine ne "
            "konur, hangi iş ASLA günün son saatine konmaz — üçünü de somut "
            "yaz.\n\n"
            "*🎯 Odak bloğu protokolü*: tek bir derin çalışma bloğunun "
            "kurulumu — süresi, öncesinde yapılan 5 dakikalık hazırlık, blok "
            "sırasında kapatılanlar, bölünme gelirse ne yapılacağı ve blok "
            "sonunda 2 dakikalık kapanış. Adım adım, uygulanabilir olsun.\n\n"
            "*🚧 Tampon ve toparlanma*: toplantı geçişleri, gün ortası "
            "toparlanma ve haftanın kapanış ritüeli için somut süreler ver. "
            "Tamponun neden bir lüks değil kapasite kararı olduğunu açıkla.\n\n"
            "*📐 Bu haftanın tek değişikliği*: hafta boyunca uygulanacak TEK "
            "bir yapı değişikliği ve hafta sonunda 'işe yaradı mı' sorusunun "
            "cevaplanacağı tek ölçüt (bir sayı ya da evet/hayır).\n\n"
            "Taahhüt takibi, hedef belirleme ve liderlik gelişimi YAZMA — "
            "onlar başka bir danışmanın bölümünde.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nKULLANICI BAĞLAMI (yalnızca bunu kullan, eksik olanı "
            "uydurma):\n"
            + context_block()
        )


__all__ = [
    "CONSTRAINTS_ENV",
    "PEAK_HOURS_ENV",
    "ProductivityCoachAdvisor",
    "SYSTEM_PROMPT",
    "constraints",
    "context_block",
]
