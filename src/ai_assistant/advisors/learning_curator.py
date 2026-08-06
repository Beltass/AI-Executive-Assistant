"""Öğrenme Küratörü — beceri boşluğu ve öğrenme SIRASI.

Kadroda kariyer tarafı zaten dolu. Eksik olan, o kariyerin altındaki
mühendislik sorusuydu: **hangi beceri, hangi SIRAYLA öğrenilmeli?**

SINIR — ``career_development`` DEĞİLDİR. Kariyer danışmanı FIRSAT sunar:
hedef roller, ilanlar, başvuru malzemesi, iş İngilizcesi, ücretsiz sertifika
duyuruları. Onun sorusu "nereye başvurayım, kendimi nasıl sunayım".
Bu bölümün sorusu tek başına şudur: "bugünkü becerilerimle hedefteki beceriler
arasındaki FARK ne, o farkı kapatmak için ÖNCE hangisini öğrenmeliyim ve
sonrakinin ön koşulu hangisi?" Kariyer danışmanı bir ilan gösterir; küratör o
ilanın istediği becerilerin ÖĞRENME SIRASINI kurar. Biri pazara bakar, diğeri
müfredata.

İkisi bir maddede buluşursa kural nettir: "şu kursa/sertifikaya başvur" cümlesi
kariyerin, "şu konuyu şu konudan önce öğren, çünkü ön koşulu" cümlesi
küratörün.

NE YAPAR
--------
1. Bildirilen mevcut becerileri hedef rolün gerektirdikleriyle karşılaştırır ve
   boşlukları adlandırır.
2. Boşlukları bir SIRAYA dizer: ön koşul zinciri, ilk kazanılacak beceri ve
   erken bırakılabilecek olan.
3. Sıranın ilk halkası için somut bir öğrenme bloğu kurar — haftalık saat
   bütçesine sığan, ölçülebilir bir çıktı bırakan.

TETİKLEYİCİ: ``weekly``. Bir öğrenme sırası günden güne değişmez; haftada bir
kurulur, hafta boyunca uygulanır. Her sabah "şunu öğren" demek hem kotayı hem
dikkati boşa harcar.

TEMİZ DEVREDİLME: model anahtarı yoksa bölüm ``skipped`` döner. Kullanıcının
CV'sini, sertifikalarını ya da kurs geçmişini OKUMAZ; yalnızca ortam
değişkenleriyle bildirilenleri kullanır ve eksik olanı "bilinmiyor" diye
söyler.

Configuration (via environment):
    LEARNING_CURATOR_SKILLS       Mevcut beceriler, virgülle ayrılmış
                                  (örn. "SQL, Excel, ekip yönetimi").
                                  Tanımsızsa küratör sıfır noktasını
                                  BİLMEDİĞİNİ söyler ve sırayı hedef rolün
                                  tipik giriş seviyesine göre kurar.
    LEARNING_CURATOR_TARGET_ROLE  Hedeflenen rol / seviye
                                  (örn. "veri analitiği yöneticisi").
    LEARNING_CURATOR_WEEKLY_HOURS Haftada öğrenmeye ayrılabilen saat
                                  (varsayılan 3). Sıra bu bütçeye göre
                                  boyutlandırılır.
"""

from __future__ import annotations

from typing import List

from ..config import setting
from ._llm_base import RICH_BRIEFING_GUIDE, LLMAdvisor

SKILLS_ENV = "LEARNING_CURATOR_SKILLS"
TARGET_ROLE_ENV = "LEARNING_CURATOR_TARGET_ROLE"
WEEKLY_HOURS_ENV = "LEARNING_CURATOR_WEEKLY_HOURS"

#: Haftalık öğrenme bütçesi bildirilmediğinde varsayılan saat. Küçük tutuldu:
#: tutulabilen üç saat, tutulamayan on saatten değerlidir.
DEFAULT_WEEKLY_HOURS = 3

SYSTEM_PROMPT = (
    "Sen bir öğrenme küratörüsün. Türkçe yazıyorsun. İşin DAR ve nettir: "
    "kullanıcının bugünkü becerileri ile hedefindeki rolün gerektirdiği "
    "beceriler arasındaki FARKI adlandırmak ve o farkı kapatacak öğrenme "
    "SIRASINI kurmak.\n\n"
    "KAPSAMIN NE DEĞİL: iş ilanı bulmak, hedef şirket önermek, CV/ön yazı "
    "yazmak, mülakat hazırlığı ve sertifika duyurusu taşımak SENİN İŞİN "
    "DEĞİL — onları kariyer danışmanı yapıyor. O 'nereye başvur' der, sen "
    "'önce neyi öğren' dersin. Bir maddeye 'şuraya başvur' ya da 'şu şirket "
    "ilan açtı' diye başlıyorsan durup sor: bu bir müfredat kararı mı, yoksa "
    "kariyer danışmanının alanına mı girdim?\n\n"
    "SIRALAMA SENİN ANA ÜRÜNÜN: her beceri için ÖN KOŞULUNU söyle. 'A'yı "
    "öğrenmeden B'ye başlama' cümlesi kurulabiliyorsa kur; kurulamıyorsa "
    "hangisinin daha erken getiri sağladığını gerekçelendir. Sırasız bir "
    "beceri listesi işe yaramaz — o listeyi kullanıcı zaten yapabilir.\n\n"
    "SESİN: net, kısa cümleli, ölçülebilir. Motivasyon sloganı yok. Her "
    "öneri bir süreye, bir ön koşula ya da bir çıktıya bağlanır.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: kullanıcının CV'sini, sertifikalarını, kurs "
    "geçmişini ya da performans değerlendirmesini GÖRMÜYORSUN. Belirli bir "
    "kurs adı, eğitmen, fiyat ya da bağlantı UYDURMA; emin olmadığın bir "
    "kaynağı adıyla anma, bunun yerine kaynağın TÜRÜNÜ tarif et (örn. "
    "'temel düzey bir SQL alıştırma platformu'). Yalnızca sana verilen "
    "becerileri ve hedefi kullan; verilmeyeni 'bilinmiyor' diye işaretle."
)


def current_skills() -> List[str]:
    """Bildirilen mevcut beceriler; tanımsızsa boş liste."""
    raw = setting(SKILLS_ENV) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def target_role() -> str:
    """Hedeflenen rol; tanımsızsa boş dize."""
    return (setting(TARGET_ROLE_ENV) or "").strip()


def weekly_hours() -> int:
    """Haftalık öğrenme bütçesi; hatalı ya da eksik değer varsayılana düşer."""
    raw = (setting(WEEKLY_HOURS_ENV) or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WEEKLY_HOURS
    return value if value > 0 else DEFAULT_WEEKLY_HOURS


def context_block() -> str:
    """Modele verilen kişiselleştirme bloğu — eksik olanı 'bilinmiyor' der."""
    lines: List[str] = []

    skills = current_skills()
    if skills:
        lines.append("Bildirilen mevcut beceriler: " + ", ".join(skills))
    else:
        lines.append(
            f"Mevcut beceriler BİLDİRİLMEDİ ({SKILLS_ENV}). Kullanıcının "
            "başlangıç noktasını BİLMİYORSUN; bunu tek cümleyle söyle ve "
            "sırayı hedef rolün tipik giriş seviyesinden başlatarak kur."
        )

    role = target_role()
    if role:
        lines.append(f"Hedeflenen rol: {role}")
    else:
        lines.append(
            f"Hedef rol BİLDİRİLMEDİ ({TARGET_ROLE_ENV}). Tek bir rol "
            "uydurma; bunun yerine mevcut becerilerin doğal bir üst basamağını "
            "VARSAYIM olarak adlandır ve varsayım olduğunu açıkça yaz."
        )

    lines.append(
        f"Haftalık öğrenme bütçesi: {weekly_hours()} saat. Sırayı bu bütçeye "
        "göre boyutlandır; bütçeye sığmayan bir plan kurma."
    )
    return "\n".join(lines)


class LearningCuratorAdvisor(LLMAdvisor):
    """Beceri boşluğunu adlandırır ve öğrenme sırasını kurar."""

    key = "learning_curator"
    title = "Öğrenme Küratörü (Beceri Boşluğu · Öğrenme Sırası)"
    #: Yalnızca ortam değişkenleriyle bildirilen becerileri işler; panoya
    #: yazılabilir.
    private = False
    #: Bir öğrenme sırası iki koşu arasında değişmez; artımlı koşularda susar.
    incremental_source = False

    system_prompt = SYSTEM_PROMPT

    @property  # type: ignore[override]
    def user_prompt(self) -> str:
        return (
            "Bu HAFTA için bir beceri boşluğu değerlendirmesi ve öğrenme "
            "sırası kur. Bölümler bu sırayla olsun:\n\n"
            "*🧭 Boşluk haritası*: hedefteki rolün gerektirdiği beceriler ile "
            "bildirilen mevcut beceriler arasındaki farkı en fazla 5 madde "
            "olarak yaz. Her madde için boşluğun büyüklüğünü (küçük / orta / "
            "büyük) ve neden bu büyüklükte olduğunu tek cümleyle söyle. "
            "Bildirilen becerilerden HANGİSİNİN zaten yeterli olduğunu da "
            "söyle — kapatılmış bir boşluğu tekrar açma.\n\n"
            "*🪜 Öğrenme sırası*: yukarıdaki boşlukları 1'den başlayarak "
            "SIRALA. Her basamak için: neden bu sırada (ön koşulu hangisi), "
            "kabaca kaç hafta sürer ve 'öğrendim' demenin ölçütü ne. Ön koşul "
            "zinciri kurulamıyorsa bunu açıkça yaz ve sırayı erken getiriye "
            "göre gerekçelendir.\n\n"
            "*🎯 İlk basamak*: sıranın BİRİNCİ maddesi için haftalık saat "
            "bütçesine sığan somut bir çalışma bloğu — hangi gün(ler), kaçar "
            "dakika, hangi alıştırma türü. Kurs adı ya da bağlantı uydurma; "
            "kaynağın TÜRÜNÜ tarif et.\n\n"
            "*⏳ Şimdi öğrenilmeyecekler*: cazip ama SIRASI GELMEMİŞ en fazla "
            "3 beceri ve her biri için 'ne olursa sırası gelir' eşiği. Bu "
            "bölüm zorunlu: neyi öğrenmeyeceğini bilmek, sıranın yarısıdır.\n\n"
            "*📏 Hafta sonu ölçütü*: hafta sonunda ilerlemeyi ölçecek TEK "
            "soru — bir sayı ya da evet/hayır ile cevaplanabilsin.\n\n"
            "İş ilanı, hedef şirket, CV/ön yazı, mülakat hazırlığı ve belirli "
            "sertifika duyurusu YAZMA — onlar kariyer danışmanının bölümünde. "
            "Sen yalnızca sırayı kurarsın.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nKULLANICI BAĞLAMI (yalnızca bunu kullan, eksik olanı "
            "uydurma):\n"
            + context_block()
        )


__all__ = [
    "DEFAULT_WEEKLY_HOURS",
    "LearningCuratorAdvisor",
    "SKILLS_ENV",
    "SYSTEM_PROMPT",
    "TARGET_ROLE_ENV",
    "WEEKLY_HOURS_ENV",
    "context_block",
    "current_skills",
    "target_role",
    "weekly_hours",
]
