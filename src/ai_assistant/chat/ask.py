"""Toplantı notu ÖZETİ — Slack'te sorulan tek bir cümlenin cevabı.

    toplantı notlarını özetle
    geçen toplantıda ne konuştuk?
    yarınki toplantıya hazırla

Bu modül rapor siparişi akışının YANINDA durur, içinde değil. Şekli
:mod:`ai_assistant.chat.templates` ile birebir aynıdır: :func:`handle` bir
:class:`Result` döner ve ``handled`` yanlışsa çağıran hiçbir şey olmamış gibi
normal akışa devam eder (bkz. ``session.SessionEngine._start``).

İŞ YERİNDE YAPILIR (kuyruğa alınmaz). Bir rapor üretmek e-tablo indirmek,
grafik çizmek ve ``.xlsx`` yazmaktır; bu ise TEK bir model çağrısıdır. Ayrı bir
iş devri, yoklama aralığı kadar (5 dakika) gecikme eklerdi. Buna karşılık uzun
çağrıdan ÖNCE ``notify`` ile bir "bakıyorum" satırı düşülür, böylece kullanıcı
isteğinin düştüğünü hemen görür.

TAHMİN YOK: birden çok not aday olduğunda motor birini seçmez, aynı numaralı
menü (:mod:`ai_assistant.chat.menu`) ile sorar. Seçim beklerken kullanıcının
yazdığı numara diske yazılmış bekleyen menüden çözülür — bir sonraki yoklama
YENİ BİR SÜREÇTİR, bellekte tutulan menü orada yoktur.

HER ÇIKMAZ TÜRKÇE ANLATILIR: Google kimliği yok, kapsam yetmiyor, klasör
tanımsız, not bulunamadı, model anahtarı yok — hiçbiri sessiz kalmaz.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..advisors import meeting_prep as prep_mod
from ..integrations import google_auth, llm
from .menu import (
    COMMAND_BACK,
    COMMAND_CANCEL,
    COMMAND_RESTART,
    Option,
    Prompt,
    TextRenderer,
    command_of,
    normalize,
    resolve,
)
from .store import ChatStore, session_key

logger = logging.getLogger(__name__)

STEP_NOTE = "toplanti_notu"

#: Menüde en çok bu kadar not gösterilir; daha uzunu menü olmaktan çıkar.
MAX_CHOICES = 6

#: Bekleyen not menüsü, rapor oturumundan AYRI bir anahtarda durur. Aynı sözlüğü
#: kullanır (böylece TTL temizliği ve disk yazımı bedava gelir) ama
#: ``store.get_session`` onu görmez — yani açık bir özet menüsü rapor akışını
#: kilitlemez.
PENDING_SUFFIX = ":ozet"

#: Not sayılmayan MIME tipleri: klasör, tablo, görsel, ses, video. Bir toplantı
#: notu bir belgedir; e-tablo rapor akışının işidir.
_SKIP_MIME_PREFIXES = ("image/", "video/", "audio/")
_SKIP_MIMES = {
    "application/vnd.google-apps.folder",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.form",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
}

# --- tetikleyiciler ---------------------------------------------------------
#
# Türkçe kalıp eşleme, LLM yönlendirici DEĞİL (bkz. :mod:`ai_assistant.chat.intent`
# — aynı üslup). Harf sınıfları hem noktalı hem noktasız yazımı kabul eder:
# "toplantı"/"toplanti", "konuştuk"/"konustuk"/"konuşduk". :func:`menu.normalize`
# zaten küçük harfe indirir ve Türkçe "İ"yi tek "i" yapar.

_T = r"toplant[ıi]"

_TRIGGERS = (
    # "toplantı notlarını özetle", "toplantı notu özeti çıkar"
    re.compile(rf"{_T}\w*\s+not\w*.{{0,20}}\b[öo]zet"),
    # "özetle bana toplantı notlarını"
    re.compile(rf"\b[öo]zetle\w*\b.{{0,25}}{_T}"),
    # "toplantı özeti", "son toplantının özeti"
    re.compile(rf"{_T}\w*\s+(?:\w+\s+)?[öo]zet"),
    # "toplantıya hazırla", "toplantıya hazırlan", "toplantı hazırlığı"
    re.compile(rf"{_T}\w*\s*(?:ya|ye)?\s*haz[ıi]rl"),
    re.compile(rf"haz[ıi]rl\w*\s+{_T}"),
    # "geçen toplantıda ne konuştuk / konuşduk / konuşuldu / görüşüldü"
    re.compile(rf"{_T}\w*\s*(?:da|de|ta|te)?\s+ne\s+\w*\s*konu[şs][dt]?u"),
    re.compile(rf"{_T}\w*\s*(?:da|de|ta|te)?\s+ne\s+\w*\s*g[öo]r[üu][şs][üu]"),
    # "geçen toplantıda neler konuşuldu"
    re.compile(rf"{_T}\w*\s*(?:da|de|ta|te)?\s+neler"),
)

#: Not adını daraltmak için işe yaramayan, isteğin kendi kelimeleri.
_REQUEST_STOPWORDS = frozenset(
    {
        "toplanti",
        "toplantida",
        "toplantiya",
        "toplantinin",
        "toplantiyi",
        "toplantilar",
        "not",
        "notu",
        "notlar",
        "notlari",
        "notlarini",
        "ozet",
        "ozeti",
        "ozetle",
        "ozetler",
        "cikar",
        "bana",
        "lutfen",
        "hazirla",
        "hazirlan",
        "hazirlik",
        "hazirligi",
        "gecen",
        "son",
        "ne",
        "neler",
        "konustuk",
        "konusduk",
        "konusuldu",
        "gorusuldu",
        "dun",
        "dunku",
        "yarin",
        "yarinki",
        "bugun",
        "bugunku",
        "yap",
        "ver",
    }
)

_TR_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ç": "c",
        "Ç": "c",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _fold(text: str) -> str:
    return str(text or "").translate(_TR_FOLD).lower()


def _words(text: str) -> List[str]:
    return [word for word in _WORD_RE.findall(_fold(text)) if len(word) > 2]


def is_summary_request(text: str) -> bool:
    """Bu mesaj bir toplantı notu özeti isteği mi?"""
    body = normalize(text)
    if not body:
        return False
    return any(pattern.search(body) for pattern in _TRIGGERS)


# --- Türkçe çıkmaz cümleleri -------------------------------------------------

NO_LLM = (
    "Özeti yazacak model anahtarı tanımlı değil (`GEMINI_API_KEY` ya da "
    "`OPENAI_API_KEY`). Anahtar tanımlanınca aynı isteği tekrar yazın."
)

NO_GOOGLE = (
    "Google kimliği tanımlı değil, bu yüzden Drive'daki toplantı notlarına "
    "bakamıyorum. Bir kez `python -m ai_assistant.integrations.google_auth` "
    "çalıştırıp `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / "
    "`GOOGLE_REFRESH_TOKEN` değerlerini tanımlayın."
)

NO_FOLDER = (
    "Toplantı notlarının durduğu Drive klasörü tanımlı değil. "
    "`MEETING_PREP_NOTES_FOLDER_ID` (ya da `GOOGLE_DRIVE_FOLDER_ID`) "
    "değişkenine klasör kimliğini yazın, sonra tekrar isteyin."
)

NO_NOTES = (
    "Drive klasöründe özetlenecek bir toplantı notu bulamadım. Klasörde "
    "belge var mı, doğru klasörü mü gösteriyorum — bir bakabilir misiniz?"
)

#: EN ÖNEMLİ ÇIKMAZ: kapsam yetmiyor. Bu bir hata değil, bir izin durumudur ve
#: kullanıcının yapması gereken şey bellidir.
SCOPE_PROBLEM = (
    "Notun ADINI görebiliyorum ama İÇERİĞİNİ açamıyorum: paylaşılan Google "
    "yetkisi Drive tarafında yalnızca dosya bilgisi okuyor "
    "(`drive.metadata.readonly`). İçerik okumak için `drive.readonly` kapsamı "
    "gerekiyor ve ESKİ REFRESH TOKEN yeni kapsamı KENDİLİĞİNDEN ALMAZ.\n"
    "Yapılacak: `.google_token.json` dosyasını silin, "
    "`python -m ai_assistant.integrations.google_auth` ile yeniden onay verin, "
    "çıkan yeni `GOOGLE_REFRESH_TOKEN` değerini ortama/GitHub gizli anahtarına "
    "yazın. Ondan sonra aynı isteği tekrar yazmanız yeterli."
)

ACK = "Toplantı notlarına bakıyorum, özeti birazdan yazacağım…"

_EMPTY_NOTE = (
    "*{name}* notunu açtım ama içi boş görünüyor; özetlenecek bir metin yok."
)

_CANCELLED = "Tamam, not özetini bıraktım."


@dataclass
class Result:
    """Bir özet isteğinin sonucu — :class:`ai_assistant.chat.templates.Result` ile aynı şekil."""

    messages: List[str] = field(default_factory=list)
    #: İstek tanındı mı? (``False`` ise çağıran normal akışa devam eder.)
    handled: bool = False
    #: Özet gerçekten yazıldı mı (test ve günlük kolaylığı).
    summarised: bool = False


def handle(
    text: str,
    store: ChatStore,
    user: str,
    channel: str = "",
    client_factory: Optional[Callable[[], Any]] = None,
    generator: Optional[Callable[[str, str], str]] = None,
    notify: Optional[Callable[[str], None]] = None,
    now: Optional[datetime] = None,
) -> Result:
    """Toplantı notu özeti isteğini karşılar.

    ``client_factory`` ve ``generator`` testlerde (ve ileride başka bir
    çağırıcıda) Drive ile modelin yerine geçer; varsayılanları gerçek
    :class:`~ai_assistant.integrations.google_drive.DriveClient` ve
    :func:`ai_assistant.integrations.llm.generate_text`.

    ``notify`` verilirse uzun çağrıdan önce kanala bir satır düşülür; motor
    ağa çıkmadığı için bu işi çağıran (yoklayıcı) yapar.
    """
    pending = _load_pending(store, channel, user)
    if pending:
        return _resolve_pending(
            pending, text, store, channel, user, client_factory, generator, notify, now
        )

    if not is_summary_request(text):
        return Result()

    return _begin(text, store, channel, user, client_factory, generator, notify, now)


# --- akış --------------------------------------------------------------------


def _begin(
    text: str,
    store: ChatStore,
    channel: str,
    user: str,
    client_factory: Optional[Callable[[], Any]],
    generator: Optional[Callable[[str, str], str]],
    notify: Optional[Callable[[str], None]],
    now: Optional[datetime],
) -> Result:
    """Kimlikleri doğrula, notları listele, gerekirse sor."""
    if not llm.is_configured():
        return Result(handled=True, messages=[NO_LLM])
    if not google_auth.google_configured():
        return Result(handled=True, messages=[NO_GOOGLE])

    folder = prep_mod.notes_folder_id()
    if not folder:
        return Result(handled=True, messages=[NO_FOLDER])

    _announce(notify, ACK)

    try:
        client = (client_factory or _default_client)()
        files = client.list_documents_in_folder(folder, max_results=50) or []
    except Exception as exc:
        logger.warning("toplantı notları listelenemedi: %s", exc)
        return Result(
            handled=True,
            messages=[
                "Drive'daki not klasörünü okuyamadım "
                f"(`{type(exc).__name__}`: {exc}). Klasör kimliğini ve Google "
                "yetkisini kontrol edip tekrar deneyin."
            ],
        )

    notes = _candidate_notes(files)
    if not notes:
        return Result(handled=True, messages=[NO_NOTES])

    narrowed = _narrow(notes, text)
    if len(narrowed) == 1:
        return _summarise(narrowed[0], client, generator, notify)

    _save_pending(store, channel, user, narrowed, now)
    return Result(handled=True, messages=[TextRenderer().text(_menu(narrowed))])


def _resolve_pending(
    pending: Dict[str, Any],
    text: str,
    store: ChatStore,
    channel: str,
    user: str,
    client_factory: Optional[Callable[[], Any]],
    generator: Optional[Callable[[str, str], str]],
    notify: Optional[Callable[[str], None]],
    now: Optional[datetime],
) -> Result:
    """Bekleyen not menüsüne verilen cevabı çözer."""
    command = command_of(text)
    if command in (COMMAND_CANCEL, COMMAND_BACK):
        _drop_pending(store, channel, user)
        return Result(handled=True, messages=[_CANCELLED])

    # "baştan" ya da yeni bir özet isteği: menüyü at, sıfırdan başla.
    if command == COMMAND_RESTART or is_summary_request(text):
        _drop_pending(store, channel, user)
        return _begin(text, store, channel, user, client_factory, generator, notify, now)

    notes = [_note_from_dict(item) for item in pending.get("notes") or []]
    prompt = _menu(notes)
    selection = resolve(prompt, text)
    if not selection.ok or not selection.value:
        prompt.clarification = selection.error or "Bunu anlayamadım."
        return Result(handled=True, messages=[TextRenderer().text(prompt)])

    chosen = next((note for note in notes if note.id == selection.value), None)
    if chosen is None:
        _drop_pending(store, channel, user)
        return Result(handled=True, messages=[NO_NOTES])

    _drop_pending(store, channel, user)
    _announce(notify, ACK)
    try:
        client = (client_factory or _default_client)()
    except Exception as exc:
        logger.warning("Drive istemcisi kurulamadı: %s", exc)
        return Result(handled=True, messages=[NO_GOOGLE])
    return _summarise(chosen, client, generator, notify)


def _summarise(
    note: prep_mod.Note,
    client: Any,
    generator: Optional[Callable[[str, str], str]],
    notify: Optional[Callable[[str], None]],
) -> Result:
    """Notu oku, tek model çağrısıyla özetle."""
    read = prep_mod.read_note(client, note)
    if read.problem == prep_mod.NOTE_READ_FORBIDDEN:
        return Result(handled=True, messages=[SCOPE_PROBLEM])
    if read.problem:
        return Result(
            handled=True,
            messages=[
                f"*{note.name}* notunu açamadım ({read.detail or 'bilinmeyen hata'}). "
                "Dosya silinmiş ya da erişilemiyor olabilir."
            ],
        )
    if not read.text:
        return Result(handled=True, messages=[_EMPTY_NOTE.format(name=note.name)])

    call = generator or llm.generate_text
    try:
        body = call(prep_mod.SYSTEM_PROMPT, _user_prompt(note, read.text))
    except Exception as exc:
        logger.warning("özet üretilemedi: %s", exc)
        return Result(
            handled=True,
            messages=[
                f"Özeti yazarken model isteği başarısız oldu (`{type(exc).__name__}`). "
                "Birazdan tekrar deneyebilirsiniz."
            ],
        )

    head = f"*Toplantı notu özeti — {note.name}*"
    when = note.modified_label
    if when:
        head += f" _({when})_"
    link = f"\n_Kaynak: {note.link}_" if note.link else ""
    return Result(
        handled=True,
        summarised=True,
        messages=[f"{head}\n\n{str(body or '').strip()}{link}"],
    )


# --- notlar ------------------------------------------------------------------


def _candidate_notes(files: Any) -> List[prep_mod.Note]:
    """Drive listesini not adaylarına çevirir (en yeniden eskiye)."""
    notes: List[prep_mod.Note] = []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("mimeType") or "")
        if mime in _SKIP_MIMES or mime.startswith(_SKIP_MIME_PREFIXES):
            continue
        if not str(item.get("id") or ""):
            continue
        notes.append(
            prep_mod.Note(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or "adsız not"),
                modified=str(item.get("modifiedTime") or ""),
                link=str(item.get("webViewLink") or ""),
                mime_type=mime,
            )
        )
    return notes[:MAX_CHOICES]


def _narrow(notes: List[prep_mod.Note], text: str) -> List[prep_mod.Note]:
    """İstekte geçen bir ad TEK bir notu işaret ediyorsa listeyi ona indirger.

    "Tahsilat toplantısının notlarını özetle" cümlesinde "tahsilat" bir
    dosyayı seçiyorsa kullanıcıya menü göstermek gereksiz bir adımdır. Birden
    çok dosyayı işaret ediyorsa liste daraltılır ama seçim yine SORULUR.
    """
    terms = {word for word in _words(text) if word not in _REQUEST_STOPWORDS}
    if not terms:
        return notes
    hits = [note for note in notes if terms & set(_words(note.name))]
    return hits or notes


def _menu(notes: List[prep_mod.Note]) -> Prompt:
    """Not seçimi için numaralı menü."""
    return Prompt(
        step=STEP_NOTE,
        title="Hangi toplantı notunu özetleyeyim?",
        options=[
            Option(value=note.id, label=note.name, hint=note.modified_label)
            for note in notes
        ],
        note="_Vazgeçmek için `iptal` yazın._",
        footer=False,
    )


def _user_prompt(note: prep_mod.Note, text: str) -> str:
    """Model isteği — hazırlık danışmanının sözleşmesinin sohbet karşılığı."""
    when = note.modified_label
    return (
        "Aşağıdaki TOPLANTI NOTUNU, yöneticinin iki dakikada okuyacağı bir "
        "özete çevir. Şu blokları bu sırayla ver:\n\n"
        "*🗣️ Ne konuşuldu*: notun konu başlıkları, 3-6 madde.\n\n"
        "*✅ Alınan kararlar*: net kararlar. Karar yoksa 'kayıtta karar yok' de, "
        "uydurma.\n\n"
        "*🙋 Senin görevlerin*: KULLANICININ kendi üstünde kalan maddeler; varsa "
        "son tarihiyle.\n\n"
        "*👥 Ekibin görevleri*: BAŞKALARININ üstünde kalan maddeler; her maddede "
        "sahibinin adı olsun, sahibi belirsizse 'sahibi belirsiz' yaz.\n\n"
        "*📋 Bir sonraki toplantı için gündem önerisi*: 3-5 madde; kapanmamış "
        "maddeleri başa al ve 'devreden' diye işaretle.\n\n"
        "Kısa cümleler kur, dolgu yapma ve NOTTA OLMAYAN hiçbir şeyi yazma.\n\n"
        f"NOT DOSYASI: {note.name}"
        + (f" (son değişiklik {when})" if when else "")
        + "\n\nİÇERİK:\n"
        + text
    )


def _default_client() -> Any:
    from ..integrations.google_drive import DriveClient

    return DriveClient()


def _announce(notify: Optional[Callable[[str], None]], text: str) -> None:
    """Uzun işten önceki "bakıyorum" satırı. Gönderilemezse akış sürer."""
    if notify is None:
        return
    try:
        notify(text)
    except Exception as exc:  # pragma: no cover - savunma
        logger.warning("bilgilendirme gönderilemedi: %s", exc)


# --- bekleyen menü (diskte) --------------------------------------------------


def pending_key(channel: str, user: str) -> str:
    """Bekleyen not menüsünün oturum anahtarı (rapor oturumundan AYRI)."""
    return f"{session_key(channel, user)}{PENDING_SUFFIX}"


def _load_pending(store: ChatStore, channel: str, user: str) -> Dict[str, Any]:
    payload = store.sessions.get(pending_key(channel, user))
    return payload if isinstance(payload, dict) and payload.get("notes") else {}


def _save_pending(
    store: ChatStore,
    channel: str,
    user: str,
    notes: List[prep_mod.Note],
    now: Optional[datetime],
) -> None:
    """Menüyü DİSKE yazar; numarayı okuyacak süreç bu süreç değildir.

    ``updated_at`` alanı :meth:`ChatStore.prune_sessions` ile aynı biçimdedir,
    böylece unutulmuş bir menü de rapor oturumlarıyla aynı TTL'de temizlenir.
    """
    store.sessions[pending_key(channel, user)] = {
        "kind": "ask_note",
        "updated_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "notes": [_note_as_dict(note) for note in notes],
    }
    store.save()


def _drop_pending(store: ChatStore, channel: str, user: str) -> None:
    if store.sessions.pop(pending_key(channel, user), None) is not None:
        store.save()


def _note_as_dict(note: prep_mod.Note) -> Dict[str, str]:
    return {
        "id": note.id,
        "name": note.name,
        "modified": note.modified,
        "link": note.link,
        "mime_type": note.mime_type,
    }


def _note_from_dict(payload: Any) -> prep_mod.Note:
    data = payload if isinstance(payload, dict) else {}
    return prep_mod.Note(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or "adsız not"),
        modified=str(data.get("modified") or ""),
        link=str(data.get("link") or ""),
        mime_type=str(data.get("mime_type") or ""),
    )


__all__ = [
    "ACK",
    "MAX_CHOICES",
    "NO_FOLDER",
    "NO_GOOGLE",
    "NO_LLM",
    "NO_NOTES",
    "PENDING_SUFFIX",
    "Result",
    "SCOPE_PROBLEM",
    "STEP_NOTE",
    "handle",
    "is_summary_request",
    "pending_key",
]
