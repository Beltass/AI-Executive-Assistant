"""Drive Dosya Analisti — Drive'a DÜŞEN yeni dosyayı okuyup karara çevirir.

Projede Drive zaten iki yönde kullanılıyordu: rapor ARŞİVİ olarak (koşu
sonunda ``operations_manager`` her danışmanın raporunu klasöre yazar) ve
``meeting_prep``in yaptığı gibi, BİLİNEN bir toplantıya eşlenen not dosyasını
okumak için. Eksik olan üçüncü yön buydu: kullanıcının klasöre ATTIĞI ve
sistemin haberi olmadığı bir dosya — bir teklif, bir vendor raporu, bir Excel
dökümü, bir sunum — hiçbir yerde okunmuyordu.

NE YAPAR
--------
1. Bir Drive klasörünü listeler (``DRIVE_INSIGHT_FOLDER_ID``, tanımsızsa
   ``GOOGLE_DRIVE_FOLDER_ID``) — mevcut
   :class:`~ai_assistant.integrations.google_drive.DriveClient` ile; ikinci bir
   Drive istemcisi YOKTUR.
2. Son ``DRIVE_INSIGHT_LOOKBACK_DAYS`` gün içinde değişmiş dosyaları alır,
   klasörleri ve SİSTEMİN KENDİ yazdığı rapor dosyalarını (``<danışman>.md``)
   eler — yoksa asistan kendi raporunu analiz edip kendi kuyruğunu kovalar.
3. Kalanları :mod:`ai_assistant.memory` defterinden geçirir: daha önce
   RAPORLANMIŞ bir dosya bir daha anlatılmaz. Yeni dosya yoksa bölüm
   ``skipped`` döner ve model hiç çağrılmaz.
4. Yeni dosyaların içeriğini okumayı dener
   (:meth:`DriveClient.read_file_text`; Docs/Sheets/Slides düz metne export
   edilir) ve toplanan GERÇEKLERİ ekibin ORTAK toplu çağrısına verir.

TETİKLEYİCİ: ``data_triggered``. Manifestteki ``data_owner`` alanı
``drive_files``; :meth:`~ai_assistant.operations_manager.OperationsManager._data_gate`
bu bölümün isteminin içerik özetini alır, klasör değişmediyse model hiç
çağrılmaz. Yani "Drive'da yeni dosya varsa çalış" kuralı iki katmanlı: dosya
düzeyinde defter, kaynak düzeyinde içerik özeti.

SLACK: ayrı bir bildirim kodu YOKTUR. Danışman kadroya girdiği an mevcut
kanal dağıtımı (``integrations.slack_channels``) bölümü kendi kanalına
(``SLACK_CHANNEL_DRIVE_INSIGHT``) yollar, özet de ana kanala düşer.

SUNUM: brifing bir *sunum taslağı* bloğu üretir (slayt başlıkları + madde
madde içerik). Google Slides dosyasının kendisini OLUŞTURMAZ — Drive
entegrasyonunda Slides API'si yok; onu eklemek yeni bir kapsam (scope) ve yeni
bir istemci demek, ayrı bir iş.

TEMİZ DEVREDİLME: Google kimliği yoksa, klasör tanımlı değilse, yeni dosya
yoksa ya da model anahtarı yoksa Türkçe bir açıklamayla ``skipped`` döner.
Model anahtarı yokken ASLA uydurma bir analiz üretmez. Bu bölüm koşuyu asla
düşürmez.

GİZLİLİK: dosya adları ve içerikleri KİŞİSEL/kurumsal veridir, bu yüzden
``private = True`` — panoya yazılmaz, yalnızca Slack'te durur.

Configuration (via environment):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
                                 Paylaşılan Google OAuth (bkz. google_auth).
    DRIVE_INSIGHT_FOLDER_ID      İzlenecek Drive klasörü; tanımsızsa
                                 ``GOOGLE_DRIVE_FOLDER_ID`` kullanılır.
    DRIVE_INSIGHT_LOOKBACK_DAYS  Kaç gün geriye bakılır (varsayılan 7).
    DRIVE_INSIGHT_MAX_FILES      Bir koşuda en fazla kaç dosya (varsayılan 3).
    DRIVE_INSIGHT_MAX_CHARS      Bir dosyadan okunacak en fazla karakter
                                 (varsayılan 3000).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import Advisor, BatchSection, Briefing
from .. import memory
from ..integrations import google_auth, llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

FOLDER_ENV = "DRIVE_INSIGHT_FOLDER_ID"
FALLBACK_FOLDER_ENV = "GOOGLE_DRIVE_FOLDER_ID"
LOOKBACK_ENV = "DRIVE_INSIGHT_LOOKBACK_DAYS"
MAX_FILES_ENV = "DRIVE_INSIGHT_MAX_FILES"
MAX_CHARS_ENV = "DRIVE_INSIGHT_MAX_CHARS"

DEFAULT_LOOKBACK_DAYS = 7

#: Bir koşuda en fazla kaç dosya analiz edilir. Token disiplini: bu bölüm
#: "klasörün tamamını özetle" değil, "bugün ne düştü" sorusunu yanıtlar.
DEFAULT_MAX_FILES = 3

#: Bir dosyadan isteme taşınacak en fazla karakter. 200 sayfalık bir PDF'in
#: tamamı tek bir çağrıya sığmaz ve zaten gereken şey ilk bölümlerdir.
DEFAULT_MAX_CHARS = 3000

#: Drive'dan bir seferde listelenecek en fazla kayıt. Eleme (klasör, kendi
#: raporlarımız, eski dosyalar, daha önce anlatılanlar) bunun üzerinde yapılır.
MAX_LISTED = 50

#: Google'ın klasör MIME tipi — listeleme sorgusu klasörleri de döndürür.
FOLDER_MIME = "application/vnd.google-apps.folder"

SKIP_NO_GOOGLE = (
    "missing env var(s): Google kimliği tanımlı değil. Drive dosya analizi "
    "klasörü okuyamıyor. `python -m ai_assistant.integrations.google_auth` ile "
    "bir kez giriş yapın, sonra GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / "
    "GOOGLE_REFRESH_TOKEN değerlerini tanımlayın."
)

SKIP_NO_FOLDER = (
    f"missing env var(s): izlenecek Drive klasörü tanımlı değil. {FOLDER_ENV} "
    f"(ya da {FALLBACK_FOLDER_ENV}) değerine klasör kimliğini yazın."
)

SKIP_NO_NEW_FILES = (
    "Drive'da yeni dosya yok: izlenen klasörde son {days} gün içinde, daha "
    "önce anlatılmamış bir dosya bulunamadı. Analiz edilecek bir şey olmadığı "
    "için model çağrılmadı."
)

SKIP_NO_LLM = "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"

#: İçerik okunamadığında (kapsam yetmiyor ya da ikili dosya) modele ve
#: kullanıcıya verilen açıklama.
METADATA_ONLY_NOTE = (
    "Bu dosyanın İÇERİĞİ okunamadı (paylaşılan Google yetkisi dosyayı "
    "listeleyebiliyor ama açamıyor, ya da biçim düz metne çevrilemiyor); "
    "aşağıda yalnızca dosya adı, türü ve tarihi var. İçeriğinden emin gibi "
    "konuşma; yalnızca ADINDAN çıkarılabilecek kadarını söyle, '(dosyayı açıp "
    "doğrulayın)' notu ekle ve kullanıcıya dosyayı ne için açması gerektiğini "
    "yaz."
)

SYSTEM_PROMPT = (
    "Sen bir üst düzey yöneticinin doküman analistisin. Türkçe yazıyorsun. "
    "İşin, patronunun Drive klasörüne YENİ düşen dosyayı onun yerine okuyup "
    "iki dakikada okunacak bir analiz notuna çevirmektir.\n\n"
    "SESİN: net, kısa cümleli, iş odaklı. Kurumsal dolgu cümlesi yok. Her "
    "satır ya bir olgu ya bir eylemdir.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: Yalnızca sana verilen dosya adından, "
    "türünden, tarihinden ve İÇERİK ALINTISINDAN konuş. Bir rakam, bir tarih, "
    "bir taraf adı ya da bir taahhüt elinde YOKSA onu yazma; 'dosyada yok, "
    "açıp kontrol edin' de. İçeriği verilmemiş bir dosya için yalnızca adından "
    "çıkarım yap ve çıkarımı '(doğrulayın)' diye işaretle. Alıntı KISALTILMIŞ "
    "olabilir; sonunu bildiğini varsayma.\n\n"
    "ÖNCELİK: kullanıcı bu dosyayı neden umursamalı? Karar gerektiren, para, "
    "risk, süre ya da taahhüt içeren maddeleri BAŞA al; biçimsel ayrıntıyı "
    "sona bırak ya da hiç yazma.\n\n"
    "GİZLİLİK: bu not yalnızca kullanıcının kendi özel kanalına gider; yine de "
    "gereksiz kişisel ayrıntıyı (özel adres, sağlık, ücret) taşıma."
)

CAVEAT = (
    "📌 Doküman notu: Buradaki özet ve bulgular Drive'daki dosyanın "
    "OKUNABİLEN bölümünden çıkarılmıştır; dosyanın tamamının yerine geçmez. "
    "Karar vermeden önce dosyayı açıp teyit edin.\n"
    "🖼️ Sunum taslağı metindir; Google Slides dosyası otomatik "
    "OLUŞTURULMAZ.\n"
    "🔒 Not: Bu bölüm dosya adı ve içeriği taşıdığı için panoya yazılmaz, "
    "yalnızca Slack'te durur."
)


def _int_setting(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def insight_folder_id() -> str:
    """İzlenecek Drive klasörü, ya da tanımsızsa boş dize."""
    for env in (FOLDER_ENV, FALLBACK_FOLDER_ENV):
        value = (os.getenv(env) or "").strip()
        if value:
            return value
    return ""


def is_own_report(name: str) -> bool:
    """Bu dosyayı SİSTEM mi yazdı?

    ``operations_manager`` her danışmanın raporunu ``<danışman anahtarı>.md``
    adıyla Drive'a yükler. Onları analiz etmek asistanı kendi çıktısını
    özetlemeye sokar — bulgu üretmez, kota yer. Manifestten okunur, böylece
    kadroya eklenen her danışman bu elemenin kapsamına kendiliğinden girer.
    """
    lowered = str(name or "").strip().lower()
    if not lowered.endswith(".md"):
        return False
    from ..status_report import ADVISOR_META

    return lowered[: -len(".md")] in ADVISOR_META


@dataclass
class DriveFile:
    """Klasöre düşmüş tek bir dosya.

    ``title``/``link`` adları rastgele değil: :mod:`ai_assistant.memory`
    parmak izini bu iki alandan üretir, böylece dosya defterden aynı feed
    öğeleri gibi geçer ve ikinci kez anlatılmaz.
    """

    file_id: str
    title: str
    link: str = ""
    mime_type: str = ""
    modified: str = ""
    #: Okunabildiyse dosyanın (kırpılmış) metni.
    text: str = ""
    #: İçerik okunamadıysa nedeni — kullanıcıya da gösterilir.
    read_error: str = ""

    @property
    def modified_label(self) -> str:
        """``2026-08-06`` biçiminde tarih, ya da bilinmiyorsa boş dize."""
        return str(self.modified or "")[:10]

    @property
    def kind(self) -> str:
        """İnsan okunur dosya türü ('Google Doküman', 'PDF', …)."""
        return FRIENDLY_TYPES.get(self.mime_type, self.mime_type or "bilinmiyor")


#: Sık görülen MIME tiplerinin Türkçe karşılığı. Bilinmeyen tip olduğu gibi
#: yazılır — modele "bilmiyorum" demek uydurmaktan iyidir.
FRIENDLY_TYPES: Dict[str, str] = {
    "application/vnd.google-apps.document": "Google Doküman",
    "application/vnd.google-apps.spreadsheet": "Google E-Tablo",
    "application/vnd.google-apps.presentation": "Google Slaytlar",
    "application/pdf": "PDF",
    "text/plain": "Düz metin",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word belgesi",  # noqa: E501
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel tablosu",  # noqa: E501
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint sunumu",  # noqa: E501
}


def parse_file(item: Dict[str, Any]) -> Optional[DriveFile]:
    """Drive listeleme kaydını :class:`DriveFile`a çevirir.

    Klasörler, adsız kayıtlar ve sistemin kendi rapor dosyaları ``None``
    döner — bu bölümün konusu KULLANICININ attığı dosyadır.
    """
    if not isinstance(item, dict):
        return None
    file_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not file_id or not name:
        return None
    mime = str(item.get("mimeType") or "").strip()
    if mime == FOLDER_MIME:
        return None
    if is_own_report(name):
        return None
    return DriveFile(
        file_id=file_id,
        title=name,
        link=str(item.get("webViewLink") or "").strip(),
        mime_type=mime,
        modified=str(item.get("modifiedTime") or "").strip(),
    )


def is_recent(modified: str, days: int, now: Optional[datetime] = None) -> bool:
    """Dosya son ``days`` gün içinde mi değişmiş?

    Tarihi okunamayan dosya YENİ sayılır: defter zaten ikinci kez
    anlatılmasını engeller, ama bir biçim sürprizi yüzünden gerçekten yeni bir
    dosyayı kaçırmak geri dönüşü olmayan bir kayıptır.
    """
    raw = str(modified or "").strip()
    if not raw:
        return True
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return stamp >= current - timedelta(days=days)


class DriveInsightAdvisor(Advisor):
    """Drive'a düşen yeni dosyayı okur, analiz eder ve sunum taslağı çıkarır."""

    key = "drive_insight"
    title = "Drive Dosya Analisti"
    #: Dosya adı ve içeriği okur; pano herkese açıktır.
    private = True
    #: Yeni dosya = yeni bulgu, yani artımlı koşularda da konuşabilir.
    incremental_source = True

    def __init__(self) -> None:
        # Koşu başına bir kez toplanır; toplu yol da aynı sonucu kullanır.
        self._files: List[DriveFile] = []
        self._gathered = False
        self._skip_reason = ""

    # -- the run ---------------------------------------------------------
    def _generate(self) -> Briefing:
        self._gather()
        if self._skip_reason:
            return self.skipped(self._skip_reason)

        if not llm.is_configured():
            # Model yoksa ANALİZ de yok. Dosya adlarından "analiz" uydurmak
            # kullanıcıyı yanıltır; bölüm sessiz kalır.
            return self.skipped(SKIP_NO_LLM)

        try:
            # Structured inference: notun içindeki her olgu zaten modele
            # verilen dosya bilgisinde ve alıntıda var — istem başka bir şey
            # uydurmayı yasaklıyor — yani ücretli bir "düşünme" turunun
            # çözeceği bir şey yok (bkz. ``STRUCTURED_THINKING_BUDGET``).
            body = llm.generate_text(
                SYSTEM_PROMPT,
                self._user_prompt(),
                thinking_budget=llm.STRUCTURED_THINKING_BUDGET,
            )
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """Drive okuması toplu çağrının DIŞINDA, burada yapılır."""
        if not llm.is_configured():
            return None
        self._gather()
        if self._skip_reason:
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
        self._gather()
        return len(self._files)

    # -- gathering -------------------------------------------------------
    def _gather(self) -> None:
        """Klasörü bir kez okur; yeni dosyaları ya da atlama nedenini tutar."""
        if self._gathered:
            return
        self._gathered = True

        if not google_auth.google_configured():
            self._skip_reason = SKIP_NO_GOOGLE
            return

        folder = insight_folder_id()
        if not folder:
            self._skip_reason = SKIP_NO_FOLDER
            return

        days = _int_setting(LOOKBACK_ENV, DEFAULT_LOOKBACK_DAYS)
        try:
            client = self._client()
            listing = client.list_documents_in_folder(folder, max_results=MAX_LISTED)
        except Exception as exc:
            self._skip_reason = f"Drive klasörü okunamadı: {exc}"
            return

        candidates = [
            parsed
            for parsed in (parse_file(item) for item in listing or [])
            if parsed and is_recent(parsed.modified, days)
        ]
        # Drive zaten modifiedTime'a göre sıralı döndürüyor; kendi sıramızı
        # dayatmak, tarihi okunamayan dosyayı listenin sonuna atardı.
        self._files = self._take_new(candidates)
        if not self._files:
            self._skip_reason = SKIP_NO_NEW_FILES.format(days=days)
            return

        self._read_contents(client)

    def _client(self) -> Any:
        """Paylaşılan Drive istemcisi (tembel içe aktarma: SDK'yı erken çekme)."""
        from ..integrations.google_drive import DriveClient

        return DriveClient()

    def _take_new(self, candidates: List[DriveFile]) -> List[DriveFile]:
        """Daha önce ANLATILMAMIŞ ilk ``MAX_FILES`` dosya.

        :func:`ai_assistant.memory.filter_new_items` yerine defterin kendi
        temel işlemleri kullanılır, çünkü o yardımcı listenin TAMAMINI
        "anlatıldı" diye işaretler; buradaki sınır anlatılmayan dosyayı da
        yakardı. Burada yalnızca RAPORLANACAK dosyalar işaretlenir.
        """
        limit = _int_setting(MAX_FILES_ENV, DEFAULT_MAX_FILES)
        ledger = memory.shared()
        fresh: List[DriveFile] = []
        for item in candidates:
            if len(fresh) >= limit:
                break
            prints = memory.item_fingerprints(item.title, item.link)
            if not prints or not ledger.are_new(self.key, prints):
                continue
            ledger.stage(self.key, prints)
            fresh.append(item)
        ledger.note_new(self.key, len(fresh))
        return fresh

    def _read_contents(self, client: Any) -> None:
        """Her yeni dosyanın metnini okumaya çalışır; hata bölümü düşürmez.

        İçerik isteğe bağlı zenginleştirmedir: okunamayan dosya notta ADIYLA
        ve "içeriği okunamadı" işaretiyle durur, çünkü kullanıcının bilmesi
        gereken ilk şey dosyanın DÜŞTÜĞÜDÜR.
        """
        max_chars = _int_setting(MAX_CHARS_ENV, DEFAULT_MAX_CHARS)
        for item in self._files:
            try:
                item.text = (
                    client.read_file_text(
                        item.file_id,
                        mime_type=item.mime_type,
                        max_chars=max_chars,
                    )
                    or ""
                ).strip()
            except Exception as exc:
                item.read_error = str(exc)
                logger.warning("Drive dosyası okunamadı (%s): %s", item.title, exc)

    # -- the prompt ------------------------------------------------------
    def _file_block(self, index: int, item: DriveFile) -> str:
        lines = [
            f"[DOSYA {index + 1}]",
            f"Ad: {item.title}",
            f"Tür: {item.kind}",
        ]
        if item.modified_label:
            lines.append(f"Son değişiklik: {item.modified_label}")
        if item.link:
            lines.append(f"Bağlantı: {item.link}")
        if item.text:
            lines.append(f"İçerik (kırpılmış olabilir):\n{item.text}")
        else:
            lines.append(f"İçerik: OKUNAMADI. {METADATA_ONLY_NOTE}")
        return "\n".join(lines)

    def _user_prompt(self) -> str:
        blocks = "\n\n".join(
            self._file_block(index, item) for index, item in enumerate(self._files)
        )
        return (
            "Aşağıdaki dosya(lar) kullanıcının Drive klasörüne YENİ düştü ve "
            "kullanıcı henüz okumadı. Her dosya için, dosyayı açmadan önce "
            "okunacak bir ANALİZ NOTU yaz. Blokları bu sırayla ver:\n\n"
            "*📄 Bu dosya ne*: tek cümlede ne olduğu, kim için hazırlanmış "
            "göründüğü ve neden bugün önemli olduğu.\n\n"
            "*🧩 Özet*: içeriğin 4-6 maddelik özeti. Yalnızca dosyada geçen "
            "bilgiyi yaz; içerik verilmediyse 'içerik okunamadı' de ve bu "
            "bloğu tek satır geç.\n\n"
            "*🔑 Kritik bulgular*: para, süre, taahhüt, risk ya da karar "
            "içeren maddeler — her birinde sayı/tarih varsa AYNEN aktar, "
            "yoksa 'dosyada belirtilmemiş' yaz. Uydurma sayı YOK.\n\n"
            "*✅ Aksiyonlar*: bu dosya yüzünden yapılması gereken 2-4 somut "
            "iş. Her maddede ne yapılacağı, kimin yapması gerektiği ve "
            "yapılmazsa ne olacağı olsun; sahibi belli değilse 'sahibi "
            "belirsiz' yaz.\n\n"
            "*🖼️ Sunum taslağı*: bu dosyadan çıkarılacak 5-7 slaytlık bir "
            "sunumun İSKELETİ — her slayt için başlık ve 2-3 madde. Kullanıcı "
            "bunu doğrudan bir sunuma yapıştırabilmeli. (Slayt dosyasını sen "
            "OLUŞTURMUYORSUN, yalnızca taslağı yazıyorsun.)\n\n"
            "*⚠️ Eksikler ve sorular*: dosyada olmayan ama karar için gereken "
            "bilgiler; dosyayı gönderene sorulacak 2-3 keskin soru.\n\n"
            "'✅ Bugünün görevi' bölümünde bu dosyayla ilgili 15-30 dakikada "
            "yapılabilecek TEK somut eylem yaz.\n\n"
            "'📚 Kaynaklar' bölümünde dosyanın KENDİ Drive bağlantısını ver; "
            "başka bağlantı uydurma.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nBİLGİ (yalnızca aşağıdakini kullan; eksik olanı uydurma):"
            + f"\n\n{blocks}"
        )


__all__ = [
    "CAVEAT",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MAX_FILES",
    "DriveFile",
    "DriveInsightAdvisor",
    "FOLDER_ENV",
    "FALLBACK_FOLDER_ENV",
    "METADATA_ONLY_NOTE",
    "SKIP_NO_FOLDER",
    "SKIP_NO_GOOGLE",
    "SKIP_NO_LLM",
    "SKIP_NO_NEW_FILES",
    "SYSTEM_PROMPT",
    "insight_folder_id",
    "is_own_report",
    "is_recent",
    "parse_file",
]
