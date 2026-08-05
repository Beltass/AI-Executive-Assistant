"""Toplantı Hazırlık & Takip — bir yönetici asistanının hazırlık notu.

Bu danışman, kullanıcının YAKLAŞAN toplantısına girmeden önce masasında
duracak notu yazar: geçen sefer ne konuşuldu, gündemde ne vardı, kimin üstünde
ne kaldı ve bu sefer neyi konuşmak gerekiyor.

NE YAPAR
--------
1. Google Takvim'den yaklaşan toplantıları okur (paylaşılan OAuth,
   :mod:`ai_assistant.integrations.google_auth` — ``day_planner`` ve
   ``mail_analyst`` ile AYNI yol; ikinci bir kimlik yolu yoktur).
2. Google Drive'daki toplantı notlarını
   :class:`~ai_assistant.integrations.google_drive.DriveClient` ile listeler ve
   yaklaşan toplantıya BAŞLIK, KATILIMCI ve TAZELİK üzerinden eşler
   (:func:`score_note`).
3. Eşleşen notun içeriğini okumayı dener (:func:`read_note`). İçerik okumak
   ``drive.readonly`` kapsamını ister; kapsam listesi artık onu istiyor ama
   ESKİ bir refresh token yeni kapsamı kendiliğinden almaz, o yüzden yeniden
   onay verilene kadar içerik okuma 403 döner. O durumda not BAŞLIK ve TARİH
   düzeyinde kullanılır — bölüm yine üretilir, sadece daha az derinlikle.
4. Toplanan gerçekleri ekibin ORTAK toplu çağrısına (``advisors._batch``)
   verir; model geçen toplantının özetini, aksiyon maddelerini (KULLANICININ
   kendi işleri ile EKİBİN işleri ayrı ayrı) ve yeni gündem önerisini yazar.

TEMİZ DEVREDİLME: Google kimliği yoksa, yaklaşan toplantı yoksa ya da model
anahtarı yoksa Türkçe bir açıklamayla ``skipped`` döner. Bu bölüm koşuyu asla
düşürmez.

GİZLİLİK: toplantı başlıkları, katılımcılar ve not içeriği KİŞİSEL veridir, bu
yüzden ``private = True`` — panoya yazılmaz, yalnızca Slack'te durur.

Configuration (via environment):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
                                  Paylaşılan Google OAuth (bkz. google_auth).
    MEETING_PREP_LOOKAHEAD_DAYS   Kaç gün ilerisine bakılır (varsayılan 3).
    MEETING_PREP_NOTES_FOLDER_ID  Toplantı notlarının Drive klasörü; tanımsızsa
                                  ``GOOGLE_DRIVE_FOLDER_ID`` kullanılır.
    MEETING_PREP_MAX_NOTES        Eşlenecek en fazla geçmiş not (varsayılan 3).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from . import Advisor, BatchSection, Briefing
from ..integrations import google_auth, llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

DEFAULT_LOOKAHEAD_DAYS = 3
DEFAULT_MAX_NOTES = 3

#: En fazla kaç toplantı hazırlanır. Hazırlık notu bir gündür, bir hafta değil.
MAX_MEETINGS = 2

#: Bir nottan isteme taşınacak en fazla karakter. Token disiplini: hazırlık
#: için gereken şey notun tamamı değil, kararlar ve açık maddelerdir.
MAX_NOTE_CHARS = 1800

#: Bir notun eşleşmiş sayılması için gereken en düşük puan (bkz. score_note).
MIN_NOTE_SCORE = 1

NOTES_FOLDER_ENV = "MEETING_PREP_NOTES_FOLDER_ID"
FALLBACK_FOLDER_ENV = "GOOGLE_DRIVE_FOLDER_ID"

SKIP_NO_GOOGLE = (
    "missing env var(s): Google kimliği tanımlı değil. Toplantı hazırlığı "
    "takvimi okuyamıyor. `python -m ai_assistant.integrations.google_auth` ile "
    "bir kez giriş yapın, sonra GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / "
    "GOOGLE_REFRESH_TOKEN değerlerini tanımlayın."
)

SKIP_NO_MEETING = (
    "yaklaşan toplantı yok: takvimde önümüzdeki {days} gün içinde katılımcılı "
    "bir toplantı bulunamadı, bu yüzden hazırlanacak bir şey de yok."
)

SKIP_NO_LLM = "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"

#: Not bulunamadığında modele verilen ve kullanıcıya da görünen açıklama.
NO_NOTES_NOTE = (
    "Drive'da bu toplantıyla eşleşen bir geçmiş not bulunamadı; geçmiş özeti "
    "ve devreden maddeler bölümlerinde 'kayıt yok' de, uydurma."
)

#: Not içeriği okunamadığında (kapsam yetmiyor) verilen açıklama.
METADATA_ONLY_NOTE = (
    "Not dosyalarının İÇERİĞİ okunamadı (paylaşılan Google yetkisi yalnızca "
    "dosya bilgisini görüyor); aşağıda yalnızca dosya adı ve tarihi var. "
    "İçerikten emin gibi konuşma, notun başlığından çıkarılabilecek kadarını "
    "söyle ve '(notu açıp doğrulayın)' notu ekle."
)

SYSTEM_PROMPT = (
    "Sen üst düzey bir yöneticinin uzun yıllık YÖNETİCİ ASİSTANISIN. Türkçe "
    "yazıyorsun. İşin toplantı öncesinde patronunun masasına, iki dakikada "
    "okunup toplantıya hazır girmesini sağlayan bir not bırakmaktır.\n\n"
    "SESİN: sakin, net, kısa cümleli ve saygılı. Kurumsal dolgu cümlesi yok, "
    "abartı yok, 'sinerji' yok. Her satır ya bir olgu ya bir eylemdir.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: Yalnızca sana verilen takvim kaydından ve not "
    "içeriğinden konuş. Geçmiş bir karar, bir tarih, bir isim ya da bir söz "
    "verildiği bilgisi elinde YOKSA onu yazma; 'kayıtta yok, toplantıda "
    "netleştirin' de. Emin olmadığın her çıkarımı '(doğrulayın)' diye işaretle. "
    "Bir aksiyonun sahibi belli değilse sahip ATAMA, 'sahibi belirsiz' yaz.\n\n"
    "AKSİYON AYRIMI (bu notun en önemli kısmı): kullanıcının KENDİ üstünde "
    "kalan işler ile EKİBİN üstünde kalan işler ayrı başlıklarda durur; ikisi "
    "tek listede karışmaz. Ekip maddelerinde sahibi adıyla yaz.\n\n"
    "GİZLİLİK: bu not yalnızca kullanıcının kendi özel kanalına gider; yine de "
    "gereksiz kişisel ayrıntıyı (özel adres, sağlık, ücret) taşıma."
)

CAVEAT = (
    "📌 Hazırlık notu: Buradaki geçmiş özeti ve açık maddeler, Drive'da "
    "eşlenen not dosyalarından ve takvim kaydından çıkarılmıştır; toplantının "
    "resmî tutanağı değildir. Toplantıya girmeden önce notu açıp teyit edin.\n"
    "🔒 Not: Bu bölüm takvim ve doküman içeriği taşıdığı için panoya yazılmaz, "
    "yalnızca Slack'te durur."
)

#: Eşleme puanlamasında görmezden gelinen, hemen her not adında geçen kelimeler.
_STOPWORDS = frozenset(
    {
        "toplanti",
        "toplantisi",
        "not",
        "notlar",
        "notlari",
        "meeting",
        "notes",
        "minutes",
        "gundem",
        "agenda",
        "ile",
        "and",
        "the",
        "for",
        "review",
        "sync",
        "haftalik",
        "aylik",
        "weekly",
        "monthly",
    }
)

_TR_FOLD = str.maketrans(
    {"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
     "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u"}
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> List[str]:
    """Bir başlığı eşlemeye uygun sözcüklere böler (Türkçe harfler katlanır)."""
    folded = str(text or "").translate(_TR_FOLD).lower()
    return [
        word
        for word in _WORD_RE.findall(folded)
        if len(word) > 2 and word not in _STOPWORDS
    ]


def _int_setting(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def notes_folder_id() -> str:
    """Toplantı notlarının Drive klasörü, ya da tanımsızsa boş dize."""
    for env in (NOTES_FOLDER_ENV, FALLBACK_FOLDER_ENV):
        value = (os.getenv(env) or "").strip()
        if value:
            return value
    return ""


@dataclass
class Meeting:
    """Takvimden okunmuş, hazırlanacak tek bir toplantı."""

    summary: str
    start: str = ""
    end: str = ""
    attendees: List[str] = field(default_factory=list)
    location: str = ""
    description: str = ""

    @property
    def when_label(self) -> str:
        """``2026-08-02T14:00:00+03:00`` -> ``02.08.2026 14:00``."""
        raw = str(self.start or "").strip()
        if not raw:
            return "saati belirsiz"
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
        return moment.strftime("%d.%m.%Y %H:%M")


@dataclass
class Note:
    """Drive'da bulunmuş, bir toplantıya eşlenmiş geçmiş not."""

    id: str
    name: str
    modified: str = ""
    link: str = ""
    text: str = ""
    score: int = 0
    #: Drive'ın bildirdiği MIME tipi; içeriği okurken fazladan bir istek
    #: yapılmasın diye listelemeden taşınır (Google belgeleri export edilir,
    #: gerisi indirilir).
    mime_type: str = ""

    @property
    def modified_label(self) -> str:
        raw = str(self.modified or "").strip()
        if not raw:
            return ""
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
        return moment.strftime("%d.%m.%Y")


def parse_event(event: Dict[str, Any]) -> Optional[Meeting]:
    """Bir Google Takvim kaydını :class:`Meeting`e çevirir.

    Tüm gün süren kayıtlar ve katılımcısı olmayan kişisel bloklar (odaklanma,
    öğle arası) hazırlık gerektirmez, ``None`` döner.
    """
    start = (event.get("start") or {}).get("dateTime")
    end = (event.get("end") or {}).get("dateTime")
    if not start:
        return None  # tüm gün süren kayıt

    attendees = [
        str(person.get("email") or "").strip()
        for person in (event.get("attendees") or [])
        if person.get("email") and not person.get("resource")
    ]
    if not attendees:
        return None  # katılımcısız blok bir toplantı değil

    return Meeting(
        summary=str(event.get("summary") or "Başlıksız toplantı"),
        start=str(start),
        end=str(end or ""),
        attendees=attendees,
        location=str(event.get("location") or ""),
        description=str(event.get("description") or "")[:400],
    )


def score_note(meeting: Meeting, file_name: str) -> int:
    """Bir not dosyasının bu toplantıya ne kadar benzediği.

    Puan: başlıktaki her ortak sözcük 2, adı geçen her katılımcı 3. Tazelik
    puanlamaya girmez — dosyalar zaten en yeniden eskiye gelir, o yüzden eşit
    puanlı iki nottan yenisi doğal olarak önce durur.
    """
    name_tokens = set(_tokens(file_name))
    if not name_tokens:
        return 0

    score = 2 * len(name_tokens & set(_tokens(meeting.summary)))
    for email in meeting.attendees:
        local = email.split("@")[0]
        if set(_tokens(local)) & name_tokens:
            score += 3
    return score


#: :func:`read_note` sonucundaki sorun etiketleri. "" = sorun yok.
NOTE_READ_FORBIDDEN = "yetki"
NOTE_READ_FAILED = "hata"


@dataclass
class NoteText:
    """Bir notun İÇERİĞİNİ okuma denemesinin sonucu.

    Boş metin ile OKUNAMAYAN metin aynı şey değildir: ilki gerçekten boş bir
    dosya, ikincisi (neredeyse her zaman) yetersiz OAuth kapsamıdır. Çağıran
    ikisini ayırt edip kullanıcıya doğru cümleyi söyleyebilsin diye sonuç bir
    dize değil bu kayıttır.
    """

    text: str = ""
    #: "" | :data:`NOTE_READ_FORBIDDEN` | :data:`NOTE_READ_FAILED`
    problem: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem


def read_note(client: Any, note: Note, max_chars: int = MAX_NOTE_CHARS) -> NoteText:
    """Bir notun metnini okur; ASLA istisna fırlatmaz.

    İçeriği getirmek :meth:`~ai_assistant.integrations.google_drive.DriveClient.read_file_text`
    işidir; burada yalnızca hatanın TÜRÜ ayrıştırılır. Paylaşılan OAuth
    kapsamı ``drive.metadata.readonly`` ile verilmiş (ya da eski kapsamla
    üretilmiş bir refresh token kullanılıyor) ise içerik okuma 403 döner ve
    sonuç :data:`NOTE_READ_FORBIDDEN` olur — bu bir çökme değil, beklenen
    ve kullanıcıya söylenebilir bir durumdur.
    """
    if not getattr(note, "id", ""):
        return NoteText(problem=NOTE_READ_FAILED, detail="dosya kimliği yok")

    from ..integrations.google_drive import DrivePermissionError

    try:
        text = client.read_file_text(
            note.id, mime_type=getattr(note, "mime_type", ""), max_chars=max_chars
        )
    except DrivePermissionError as exc:
        logger.info("not içeriği yetki nedeniyle okunamadı (%s): %s", note.name, exc)
        return NoteText(problem=NOTE_READ_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        logger.info("not içeriği okunamadı (%s): %s", note.name, exc)
        return NoteText(problem=NOTE_READ_FAILED, detail=str(exc))
    return NoteText(text=str(text or "").strip())


def find_notes(
    client: Any,
    meetings: Sequence[Meeting],
    folder_id: str,
    limit: int = DEFAULT_MAX_NOTES,
) -> tuple[Dict[int, List[Note]], str]:
    """Her toplantı için Drive'daki en iyi eşleşen geçmiş notları bulur ve okur.

    Saf bir fonksiyon: hiçbir şeyi bir nesnenin üstünde biriktirmez, bulduğunu
    döner. İkinci dönüş değeri, hiçbir notun İÇERİĞİ okunamadıysa sorunun türü
    (:data:`NOTE_READ_FORBIDDEN` / :data:`NOTE_READ_FAILED`), okunduysa ``""``.
    """
    if not folder_id:
        return {}, ""

    files = client.list_documents_in_folder(folder_id, max_results=100) or []

    matched: Dict[int, List[Note]] = {}
    problem = ""
    for index, meeting in enumerate(meetings):
        scored = [
            note
            for note in (
                _note_from_item(meeting, item) for item in files if isinstance(item, dict)
            )
            if note is not None
        ]
        scored.sort(key=lambda note: note.score, reverse=True)
        picked = scored[:limit]
        for note in picked:
            result = read_note(client, note)
            note.text = result.text
            if result.problem and not problem:
                problem = result.problem
        if picked:
            matched[index] = picked
    return matched, problem


def _note_from_item(meeting: Meeting, item: Dict[str, Any]) -> Optional[Note]:
    """Bir Drive dosyasını, toplantıya yetecek kadar benziyorsa nota çevirir."""
    name = str(item.get("name") or "")
    score = score_note(meeting, name)
    if score < MIN_NOTE_SCORE:
        return None
    return Note(
        id=str(item.get("id") or ""),
        name=name,
        modified=str(item.get("modifiedTime") or ""),
        link=str(item.get("webViewLink") or ""),
        mime_type=str(item.get("mimeType") or ""),
        score=score,
    )


class MeetingPrepAdvisor(Advisor):
    """Yaklaşan toplantı için hazırlık ve takip notu yazar."""

    key = "meeting_prep"
    title = "Toplantı Hazırlık & Takip"
    #: Takvim ve doküman içeriği okur; pano herkese açıktır.
    private = True
    incremental_source = False

    def __init__(self) -> None:
        # Koşu başına bir kez toplanır; toplu yol da aynı sonucu kullanır.
        self._meetings: List[Meeting] = []
        self._notes: Dict[int, List[Note]] = {}
        self._gathered = False
        self._skip_reason = ""
        self._metadata_only = False

    # -- the run ---------------------------------------------------------
    def _generate(self) -> Briefing:
        self._gather()
        if self._skip_reason:
            return self.skipped(self._skip_reason)

        if not llm.is_configured():
            return self.skipped(SKIP_NO_LLM)

        try:
            # Structured inference: every fact in this note is already in the
            # calendar entry and the meeting notes handed to the model — the
            # prompt forbids inventing anything else — so a billed "thinking"
            # pass has nothing to work out. See ``STRUCTURED_THINKING_BUDGET``.
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
        """Takvim ve Drive okuması toplu çağrının DIŞINDA, burada yapılır."""
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

    # -- gathering -------------------------------------------------------
    def _gather(self) -> None:
        """Takvimi ve notları bir kez okur; sonucu ya da atlama nedenini tutar."""
        if self._gathered:
            return
        self._gathered = True

        if not google_auth.google_configured():
            self._skip_reason = SKIP_NO_GOOGLE
            return

        try:
            creds = google_auth.get_credentials()
        except google_auth.GoogleAuthError as exc:
            self._skip_reason = f"Google auth unavailable: {exc}"
            return

        days = _int_setting("MEETING_PREP_LOOKAHEAD_DAYS", DEFAULT_LOOKAHEAD_DAYS)
        try:
            events = self._fetch_events(creds, days)
        except Exception as exc:
            self._skip_reason = f"Takvim verisi alınamadı: {exc}"
            return

        meetings = [m for m in (parse_event(e) for e in events) if m]
        self._meetings = meetings[:MAX_MEETINGS]
        if not self._meetings:
            self._skip_reason = SKIP_NO_MEETING.format(days=days)
            return

        # Notlar isteğe bağlı zenginleştirmedir: Drive yoksa ya da hata verirse
        # hazırlık notu takvimle yazılır, bölüm düşmez.
        try:
            self._notes = self._fetch_notes(self._meetings)
        except Exception as exc:
            logger.warning("toplantı notları okunamadı: %s", exc)
            self._notes = {}

    def _fetch_events(self, creds: Any, days: int) -> List[Dict[str, Any]]:
        """Şu andan itibaren ``days`` gün içindeki takvim kayıtları."""
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = datetime.now(timezone.utc)
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=(now + timedelta(days=days)).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        return list(result.get("items") or [])

    def _fetch_notes(self, meetings: Sequence[Meeting]) -> Dict[int, List[Note]]:
        """Her toplantı için Drive'daki en iyi eşleşen geçmiş notlar.

        Bulma/okuma işi modül düzeyindeki :func:`find_notes` içindedir (sohbet
        katmanı da onu kullanır); burada kalan tek şey klasörü ve istemciyi
        vermek ve içerik okunamadıysa bunu bölümde işaretlemek.
        """
        folder = notes_folder_id()
        if not folder:
            return {}

        from ..integrations.google_drive import DriveClient

        client = DriveClient()
        limit = _int_setting("MEETING_PREP_MAX_NOTES", DEFAULT_MAX_NOTES)
        matched, problem = find_notes(client, meetings, folder, limit=limit)
        if problem:
            self._metadata_only = True
        return matched

    def _read_note(self, client: Any, note: Note) -> str:
        """Notun metnini okumayı dener; okunamazsa boş dize döner.

        Paylaşılan OAuth kapsamı (``google_auth.SCOPES``) Drive tarafında eski
        bir refresh token ile yalnızca DOSYA BİLGİSİ okuyabilir, bu yüzden
        burası çoğu kurulumda boş döner ve bölüm başlık düzeyinde çalışır.
        Kapsam yenilendiğinde aynı kod içeriği de getirir; hata durumu asla
        yukarı taşınmaz — yalnızca ``_metadata_only`` işaretlenir.
        """
        result = read_note(client, note)
        if result.problem:
            self._metadata_only = True
        return result.text

    # -- prompt ----------------------------------------------------------
    def _meeting_block(self, index: int, meeting: Meeting) -> str:
        lines = [
            f"[TOPLANTI {index + 1}]",
            f"Başlık: {meeting.summary}",
            f"Zaman: {meeting.when_label}",
            f"Katılımcılar: {', '.join(meeting.attendees) or 'belirtilmemiş'}",
        ]
        if meeting.location:
            lines.append(f"Yer: {meeting.location}")
        if meeting.description:
            lines.append(f"Takvim açıklaması: {meeting.description}")

        notes = self._notes.get(index) or []
        if not notes:
            lines.append(f"Geçmiş not: YOK. {NO_NOTES_NOTE}")
            return "\n".join(lines)

        lines.append("Eşleşen geçmiş notlar (en yakından uzağa):")
        for note in notes:
            head = f"- {note.name}"
            if note.modified_label:
                head += f" ({note.modified_label})"
            if note.link:
                head += f" — {note.link}"
            lines.append(head)
            if note.text:
                lines.append(f"  İçerik:\n{note.text}")
        if self._metadata_only and not any(note.text for note in notes):
            lines.append(METADATA_ONLY_NOTE)
        return "\n".join(lines)

    def _user_prompt(self) -> str:
        blocks = "\n\n".join(
            self._meeting_block(index, meeting)
            for index, meeting in enumerate(self._meetings)
        )
        return (
            "Aşağıdaki yaklaşan toplantı(lar) için, yöneticinin toplantıya "
            "girmeden önce okuyacağı bir HAZIRLIK NOTU yaz. Her toplantı için "
            "şu blokları bu sırayla ver:\n\n"
            "*🗓️ Toplantı*: başlık, zaman ve kimlerin geleceği — tek satır.\n\n"
            "*🔁 Geçen sefer ne konuşuldu*: önceki notlardan çıkan konular, "
            "alınan kararlar ve gündemde ne vardı. Not yoksa 'kayıt yok' de; "
            "olmayan bir kararı ASLA uydurma.\n\n"
            "*✅ Senin görevlerin*: KULLANICININ kendi üstünde kalan aksiyon "
            "maddeleri. Her madde için ne yapılacağı, varsa son tarih ve "
            "durumu (bitti / sürüyor / başlanmadı) yazılsın.\n\n"
            "*👥 Ekibin görevleri*: BAŞKALARININ üstünde kalan maddeler. Her "
            "maddede sahibinin adı olsun; sahibi belli değilse 'sahibi belirsiz "
            "— toplantıda netleştir' de.\n\n"
            "*📋 Önerilen gündem*: bu toplantı için 4-6 maddelik gündem. "
            "Kapanmamış maddeleri BAŞA al ve 'devreden' diye işaretle; her "
            "maddenin yanına kaç dakika sürmesi gerektiğini yaz.\n\n"
            "*❓ Sorulacak sorular*: toplantıda sorulacak 2-3 keskin soru — "
            "kapalı kalmış bir noktayı açan, karar zorlayan sorular.\n\n"
            "*⚠️ Dikkat*: risk, gecikme, tekrar eden bir söz ya da çelişki "
            "varsa nazikçe işaret et. Yoksa bu bloğu 'belirgin bir risk yok' "
            "diye tek satır geç.\n\n"
            "'✅ Bugünün görevi' bölümünde toplantıdan ÖNCE 15-30 dakikada "
            "yapılabilecek TEK somut hazırlık eylemi yaz.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nBİLGİ (yalnızca aşağıdakini kullan; eksik olanı uydurma):\n\n"
            + blocks
        )


__all__ = [
    "CAVEAT",
    "DEFAULT_LOOKAHEAD_DAYS",
    "MAX_MEETINGS",
    "MAX_NOTE_CHARS",
    "Meeting",
    "MeetingPrepAdvisor",
    "Note",
    "NOTES_FOLDER_ENV",
    "NOTE_READ_FAILED",
    "NOTE_READ_FORBIDDEN",
    "NoteText",
    "SKIP_NO_GOOGLE",
    "SKIP_NO_LLM",
    "SKIP_NO_MEETING",
    "find_notes",
    "notes_folder_id",
    "parse_event",
    "read_note",
    "score_note",
]
