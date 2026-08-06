"""Karar Zekâsı — VERİLMİŞ kararların sonucu ve karar kalitesi geri bildirimi.

``operations_director`` şu soruyu yanıtlar: "bugün ne karar verilmeli?" Bu
bölüm onun TAM TERSİ yönde çalışır: "verdiklerimiz ne oldu?" Karar anına değil,
kararın SONRASINA bakar — gerçekleşen sonucu beklenenle karşılaştırır, kararın
kendisi mi yoksa şansın mı işe yaradığını ayırır ve bir sonraki benzer karara
taşınacak dersi çıkarır.

Bir kararı sonucuyla ölçmek yanıltıcıdır: iyi bir karar kötü sonuçlanabilir,
kötü bir karar şansa iyi sonuçlanabilir (bu ayrım literatürde *resulting*
diye geçer). Bu yüzden bölüm iki şeyi AYRI değerlendirir: karar anındaki
BİLGİYLE verilen kararın kalitesi, ve gerçekleşen sonuç.

NE YAPAR
--------
1. Kullanıcının kaydettiği kararları okur (:data:`DECISIONS_ENV`). Kayıt
   biçimi serbesttir; satır başına bir karar, istenirse ``karar | beklenen
   sonuç | gerçekleşen`` gibi ayrımlarla.
2. Her karar için sonucu beklenenle karşılaştırır, karar kalitesini süreç
   üzerinden değerlendirir ve tekrar eden bir örüntü varsa adını koyar.
3. Kayıt YOKSA hiçbir karar UYDURMAZ: bunun yerine önümüzdeki hafta için
   uygulanabilir bir karar günlüğü protokolü ve gözden geçirme soruları verir.

TETİKLEYİCİ: ``weekly``. Bir kararın sonucu bir günde belli olmaz; her sabah
"kararlarını gözden geçir" demek hem tekrar hem kota israfıdır.

TEMİZ DEVREDİLME: model anahtarı yoksa ``skipped``. Kullanıcının kararlarını
kendisi bildirmediği sürece bu bölüm bir karar, bir tarih ya da bir sonuç
İCAT ETMEZ.

GİZLİLİK: kullanıcının kendi kararlarını (kurum içi bilgi olabilir) taşır, bu
yüzden ``private = True`` — panoya yazılmaz, yalnızca Slack'te durur.

Configuration (via environment):
    DECISION_INTELLIGENCE_DECISIONS  Gözden geçirilecek kararlar; ``;`` ya da
                                     satır başıyla ayrılır. Tanımsızsa bölüm
                                     karar günlüğü protokolü verir.
"""

from __future__ import annotations

import re
from typing import List

from . import Briefing
from ..config import setting
from ..integrations import STATUS_OK
from ._llm_base import RICH_BRIEFING_GUIDE, LLMAdvisor

DECISIONS_ENV = "DECISION_INTELLIGENCE_DECISIONS"

#: Bir koşuda en fazla kaç karar incelenir. Token disiplini: gözden geçirme
#: derinliği, listenin uzunluğundan değerlidir.
MAX_DECISIONS = 5

#: Kararları ayıran işaretler: noktalı virgül ya da satır sonu.
_SPLIT = re.compile(r"[;\n]+")

SYSTEM_PROMPT = (
    "Sen bir üst düzey yöneticinin karar zekâsı danışmanısın. Türkçe "
    "yazıyorsun. İşin DAR ve nettir: GEÇMİŞTE verilmiş kararların nasıl "
    "sonuçlandığını değerlendirmek ve karar verme sürecine geri bildirim "
    "vermek.\n\n"
    "KAPSAMIN NE DEĞİL: 'bugün hangi kararı vermeliyim' listesi SENİN İŞİN "
    "DEĞİL — onu başka bir danışman yapıyor. Sen yeni karar önermezsin; "
    "verilmiş kararı geriye dönük okursun. Bir madde yazarken sor: bu bir "
    "geri bildirim mi, yoksa yeni bir karar önerisi mi? İkincisiyse yazma.\n\n"
    "YÖNTEMİN: sonucu kararın kalitesiyle KARIŞTIRMA. İyi bir karar kötü "
    "sonuçlanmış olabilir (şans), kötü bir karar iyi sonuçlanmış olabilir. Her "
    "kararı iki ayrı eksende değerlendir: (a) karar anındaki BİLGİYLE süreç ne "
    "kadar sağlamdı, (b) sonuç ne oldu. İkisini ayrı ayrı söyle.\n\n"
    "SESİN: sakin, yargılayıcı değil, örüntü arayan. Suçlu aramazsın; "
    "tekrarlanabilir bir ders çıkarırsın.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: yalnızca sana verilen karar kayıtlarını "
    "kullan. Bir karar, bir tarih, bir tutar, bir kişi ya da bir sonuç ICAT "
    "ETME. Kayıtta sonuç yazmıyorsa 'sonuç bildirilmemiş' de ve sonucu "
    "ölçmek için hangi tek verinin gerektiğini söyle."
)

CAVEAT = (
    "📌 Karar notu: Buradaki değerlendirme YALNIZCA sizin kaydettiğiniz "
    "kararlara ve bildirdiğiniz sonuçlara dayanır; kaydedilmemiş bir karar "
    "burada görünmez.\n"
    "🎲 Sonuç ile karar kalitesi ayrı şeylerdir; kötü sonuçlanan bir karar "
    "mutlaka kötü bir karar değildir.\n"
    "🔒 Not: Bu bölüm kendi kararlarınızı içerdiği için panoya yazılmaz, "
    "yalnızca Slack'te durur."
)

#: Kayıt yokken modele verilen yönerge — karar UYDURMAK yerine protokol yaz.
NO_LOG_INSTRUCTION = (
    "KAYITLI KARAR YOK. Kullanıcının geçmiş kararlarını GÖRMÜYORSUN, bu "
    "yüzden hiçbir karar, sonuç ya da örnek vaka UYDURMA. Bunun yerine: "
    "(1) bu hafta uygulanabilecek bir karar günlüğü biçimi öner — bir kararın "
    "kaydında hangi 5 alan bulunmalı ve neden; (2) bir kararı sonradan "
    "değerlendirmek için sorulacak 5 soruyu yaz; (3) 'sonuç' ile 'karar "
    "kalitesi' ayrımını kısa bir örnekle anlat (örneği GENEL bir örnek olarak "
    "kur, kullanıcının başına gelmiş gibi anlatma); (4) kullanıcıya "
    f"kararlarını {DECISIONS_ENV} değişkenine nasıl yazacağını tek satırda "
    "göster."
)


def recent_decisions() -> List[str]:
    """Kullanıcının kaydettiği kararlar; tanımsızsa boş liste.

    Biçim dayatılmaz: kullanıcı ``;`` ya da satır sonuyla ayırdığı sürece
    istediği ayrıntıyı yazabilir. Bu bölüm kaydı ayrıştırmaz, olduğu gibi
    modele taşır — ayrıştırmak, kullanıcının yazdığı bir bilgiyi kaybetme
    riskidir.
    """
    raw = setting(DECISIONS_ENV) or ""
    parts = [part.strip() for part in _SPLIT.split(raw)]
    return [part for part in parts if part][:MAX_DECISIONS]


def decisions_block() -> str:
    """Modele verilen karar bloğu — kayıt yoksa açık bir 'kayıt yok' yönergesi."""
    entries = recent_decisions()
    if not entries:
        return NO_LOG_INSTRUCTION
    lines = [
        "Aşağıdaki kararlar kullanıcının KENDİ kaydıdır. Yalnızca bunları "
        "değerlendir; kayıtta olmayan ayrıntıyı uydurma."
    ]
    lines.extend(
        f"[KARAR {index + 1}] {entry}" for index, entry in enumerate(entries)
    )
    return "\n".join(lines)


class DecisionIntelligenceAdvisor(LLMAdvisor):
    """Verilmiş kararların sonucunu ve karar kalitesini geriye dönük okur."""

    key = "decision_intelligence"
    title = "Karar Zekâsı (Sonuç Takibi · Karar Kalitesi)"
    #: Kullanıcının kendi kararlarını taşıyabilir; pano herkese açıktır.
    private = True
    #: Karar sonuçları gün içinde değişmez; artımlı koşularda sessiz kalır.
    incremental_source = False

    system_prompt = SYSTEM_PROMPT

    # -- the caveat rides on BOTH paths ----------------------------------
    def _generate(self) -> Briefing:
        briefing = super()._generate()
        if briefing.status != STATUS_OK:
            return briefing
        return self.briefing_from_batch(briefing.text)

    def briefing_from_batch(self, text: str) -> Briefing:
        return self.ok(f"{text.strip()}\n\n{CAVEAT}")

    @property  # type: ignore[override]
    def user_prompt(self) -> str:
        return (
            "Geçmiş kararlar üzerine bir GERİ BİLDİRİM notu yaz. Blokları bu "
            "sırayla ver:\n\n"
            "*📊 Ne olmuştu*: her karar için tek cümlede karar, beklenen sonuç "
            "ve gerçekleşen sonuç. Kayıtta olmayan alan için 'bildirilmemiş' "
            "yaz.\n\n"
            "*⚖️ Karar mı, şans mı*: her karar için süreç kalitesini (karar "
            "anındaki bilgiyle) ve sonucu AYRI AYRI değerlendir. İkisinin "
            "uyuşmadığı bir karar varsa özellikle onu işle.\n\n"
            "*🔁 Örüntü*: kararlar arasında tekrar eden bir eğilim (acele "
            "kapatma, aşırı analiz, tek kaynaktan bilgi, geri alınamaz adımı "
            "erken atma) görünüyorsa adını koy ve kanıtını göster. "
            "Görünmüyorsa 'tek kayıttan örüntü çıkmaz' de — zorlama.\n\n"
            "*🧪 Bir sonraki sefere*: benzer bir karar için TEK bir süreç "
            "değişikliği — ne değişecek, hangi adımda uygulanacak, neyi "
            "engelleyecek.\n\n"
            "*📓 Kayıt kalitesi*: bu değerlendirmeyi daha keskin yapmak için "
            "karar kaydına eklenmesi gereken en fazla 2 alan.\n\n"
            "Yeni karar ÖNERME ve bugünün gündemini yazma — onlar başka bir "
            "danışmanın bölümünde.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nKARAR KAYDI (yalnızca aşağıdakini kullan):\n\n"
            + decisions_block()
        )


__all__ = [
    "CAVEAT",
    "DECISIONS_ENV",
    "DecisionIntelligenceAdvisor",
    "MAX_DECISIONS",
    "NO_LOG_INSTRUCTION",
    "SYSTEM_PROMPT",
    "decisions_block",
    "recent_decisions",
]
