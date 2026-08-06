"""Konuşma dilindeki Türkçe tarih ifadelerini ``datetime``a çeviren dilbilgisi.

NEDEN KODDA, MODELDE DEĞİL
--------------------------

Bir toplantıda tarih neredeyse hiç takvimle söylenmez: "cuma gününe kadar",
"iki hafta içinde", "ayın 15'i", "haftaya çarşamba". Bunları
:class:`~ai_assistant.advisors.meeting_notes.ActionItem` üzerindeki gerçek bir
``deadline``a çevirmenin iki yolu var:

* modelden doğrudan ISO 8601 tarih istemek — tek satır, ama dil modelleri gün
  sayarken yanılır ("cuma" hangi cuma, "ayın 15'i" hangi ay) ve yanılgı sessiz
  olur: takvime düşen tarih güvenilir görünür, çünkü tarih gibi görünür;
* ifadeyi burada, toplantı tarihine göre ÇÖZMEK — belirlenimci, ağsız test
  edilebilir ve yanlışsa test kırmızıya döner.

Bu modül ikinciyi yapar. Model yine de bir ISO tahmini gönderir; o tahmin
YALNIZCA buradaki dilbilgisi ifadeyi tanımadığında (örneğin "bütçe toplantısı
sonrası" gibi anlatısal bir tarif ya da bu dilbilgisinde olmayan bir kalıp)
yedek olarak kullanılır.

Tanınmayan ifade ``None`` döner. Tarih UYDURULMAZ: boş bir ``deadline``,
uydurulmuş bir cumadan iyidir.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Dict, Optional

#: Süresi "gün sonuna kadar" olan bir işin saati. "Cuma gününe kadar" cumanın
#: sonuna kadar demektir; sabah 00:00 vermek işi bir gün öne çekerdi.
END_OF_DAY_HOUR = 23
END_OF_DAY_MINUTE = 59

WEEKDAYS: Dict[str, int] = {
    "pazartesi": 0,
    "salı": 1,
    "sali": 1,
    "çarşamba": 2,
    "carsamba": 2,
    "perşembe": 3,
    "persembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}

MONTHS: Dict[str, int] = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
}

#: Sayılar konuşmada yazıyla geçer ("iki hafta içinde").
NUMBER_WORDS: Dict[str, int] = {
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "uc": 3,
    "dört": 4,
    "dort": 4,
    "beş": 5,
    "bes": 5,
    "altı": 6,
    "alti": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "onbir": 11,
    "on bir": 11,
    "oniki": 12,
    "on iki": 12,
    "onbeş": 15,
    "onbes": 15,
    "on beş": 15,
    "on bes": 15,
    "yirmi": 20,
    "yirmi beş": 25,
    "otuz": 30,
    "kırk": 40,
    "kirk": 40,
    "elli": 50,
    "altmış": 60,
    "altmis": 60,
}

#: "Bir sonraki" anlamı taşıyan ekler — haftayı bir tur ileri atarlar.
NEXT_WEEK_MARKERS = (
    "gelecek",
    "önümüzdeki",
    "onumuzdeki",
    "haftaya",
    "sonraki",
    "öbür",
    "obur",
)

_WEEKDAY_RE = re.compile(
    r"\b(pazartesi|cumartesi|çarşamba|carsamba|perşembe|persembe|salı|sali|cuma|pazar)\b"
)
_MONTH_NAME_RE = re.compile(
    r"\b(\d{1,2})\s*(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|"
    r"ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)\b"
    r"(?:\s*(\d{4}))?"
)
_DURATION_RE = re.compile(
    r"(?:(\d{1,3})|([a-zçğıöşü]+(?:\s+[a-zçğıöşü]+)?))\s*"
    r"\b(gün|gun|hafta|ay|iş günü|is gunu)\b"
)
_MONTH_DAY_RE = re.compile(r"\bay[ıi]n\s*(\d{1,2})\b")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DOTTED_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")


def normalise(text: str) -> str:
    """Türkçeye uygun küçük harfe indirger ve kesme işaretlerini sadeleştirir.

    ``str.lower()`` tek başına yetmez: ``"İ"`` Python'da noktalı bir birleşik
    karaktere düşer ve ``"I"`` ``"i"`` olur — ikisi de Türkçede yanlış.
    """
    raw = str(text or "")
    raw = raw.replace("I", "ı").replace("İ", "i")
    raw = raw.lower()
    raw = raw.replace("’", "'").replace("`", "'").replace("´", "'")
    # "15'i", "cuma'ya" gibi eklerdeki kesmeyi boşluğa çevirmek yerine
    # kaldırıyoruz ki "ayın 15'i" kalıbı tek parça kalsın.
    raw = re.sub(r"'\w*", "", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _end_of_day(moment: datetime) -> datetime:
    return moment.replace(
        hour=END_OF_DAY_HOUR, minute=END_OF_DAY_MINUTE, second=0, microsecond=0
    )


def _shift_days(anchor: datetime, days: int) -> datetime:
    return _end_of_day(anchor + timedelta(days=days))


def _with_day(anchor: datetime, year: int, month: int, day: int) -> Optional[datetime]:
    """Belirli bir takvim gününü, ayın uzunluğuna kırparak kurar."""
    last = calendar.monthrange(year, month)[1]
    if day < 1:
        return None
    day = min(day, last)
    try:
        return _end_of_day(anchor.replace(year=year, month=month, day=day))
    except ValueError:  # pragma: no cover - kırpma sonrası oluşmaz
        return None


def _add_months(anchor: datetime, months: int) -> datetime:
    total = (anchor.year * 12 + anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return _end_of_day(anchor.replace(year=year, month=month, day=day))


def _number(digits: Optional[str], word: Optional[str]) -> Optional[int]:
    if digits:
        try:
            return int(digits)
        except ValueError:  # pragma: no cover - regex zaten rakam garantiler
            return None
    if not word:
        return None
    phrase = word.strip()
    if phrase in NUMBER_WORDS:
        return NUMBER_WORDS[phrase]
    tail = phrase.split()[-1]
    return NUMBER_WORDS.get(tail)


def _parse_weekday(text: str, anchor: datetime) -> Optional[datetime]:
    match = _WEEKDAY_RE.search(text)
    if not match:
        return None
    target = WEEKDAYS[match.group(1)]
    delta = (target - anchor.weekday()) % 7
    prefix = text[: match.start()]
    # "bu cuma" bugünü de kapsayabilir; çıplak "cuma" ise HER ZAMAN ileriye
    # bakar — geçmiş bir cuma teslim tarihi olamaz.
    if delta == 0 and "bu " not in prefix:
        delta = 7
    if any(marker in prefix for marker in NEXT_WEEK_MARKERS):
        delta += 7
    return _shift_days(anchor, delta)


def _parse_duration(text: str, anchor: datetime) -> Optional[datetime]:
    for match in _DURATION_RE.finditer(text):
        amount = _number(match.group(1), match.group(2))
        if amount is None:
            continue
        unit = match.group(3)
        if unit in ("hafta",):
            return _shift_days(anchor, amount * 7)
        if unit == "ay":
            return _add_months(anchor, amount)
        if unit in ("iş günü", "is gunu"):
            return _shift_business_days(anchor, amount)
        return _shift_days(anchor, amount)
    return None


def _shift_business_days(anchor: datetime, days: int) -> datetime:
    moment = anchor
    remaining = max(0, days)
    while remaining:
        moment += timedelta(days=1)
        if moment.weekday() < 5:
            remaining -= 1
    return _end_of_day(moment)


def _parse_explicit(text: str, anchor: datetime) -> Optional[datetime]:
    iso = _ISO_RE.search(text)
    if iso:
        return _with_day(
            anchor, int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        )

    dotted = _DOTTED_RE.search(text)
    if dotted:
        day, month = int(dotted.group(1)), int(dotted.group(2))
        if 1 <= month <= 12:
            year_part = dotted.group(3)
            if year_part:
                year = int(year_part)
                if year < 100:
                    year += 2000
            else:
                year = anchor.year
            resolved = _with_day(anchor, year, month, day)
            if resolved and not year_part and resolved < anchor:
                resolved = _with_day(anchor, year + 1, month, day)
            return resolved

    named = _MONTH_NAME_RE.search(text)
    if named:
        day = int(named.group(1))
        month = MONTHS[named.group(2)]
        year = int(named.group(3)) if named.group(3) else anchor.year
        resolved = _with_day(anchor, year, month, day)
        if resolved and not named.group(3) and resolved < anchor:
            resolved = _with_day(anchor, year + 1, month, day)
        return resolved

    month_day = _MONTH_DAY_RE.search(text)
    if month_day:
        day = int(month_day.group(1))
        resolved = _with_day(anchor, anchor.year, anchor.month, day)
        if resolved is None or resolved < anchor:
            following = _add_months(anchor.replace(day=1), 1)
            resolved = _with_day(anchor, following.year, following.month, day)
        return resolved
    return None


def _parse_named_offset(text: str, anchor: datetime) -> Optional[datetime]:
    if "bugün" in text or "bugun" in text or "gün sonuna" in text:
        return _end_of_day(anchor)
    if "yarından sonra" in text or "yarindan sonra" in text:
        return _shift_days(anchor, 2)
    if "yarın" in text or "yarin" in text:
        return _shift_days(anchor, 1)
    if "öbür gün" in text or "obur gun" in text or "ertesi gün" in text:
        return _shift_days(anchor, 2)
    if "hafta sonu" in text:
        # En yakın cumartesi.
        delta = (5 - anchor.weekday()) % 7 or 7
        return _shift_days(anchor, delta)
    if "ay sonu" in text or "ayın sonu" in text or "ayin sonu" in text:
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return _with_day(anchor, anchor.year, anchor.month, last)
    if "yıl sonu" in text or "yil sonu" in text:
        return _with_day(anchor, anchor.year, 12, 31)
    if "hafta başı" in text or "hafta basi" in text:
        delta = (0 - anchor.weekday()) % 7 or 7
        return _shift_days(anchor, delta)
    if any(
        marker in text for marker in ("gelecek ay", "önümüzdeki ay", "onumuzdeki ay")
    ):
        return _add_months(anchor, 1)
    if any(
        marker in text
        for marker in (
            "gelecek hafta",
            "önümüzdeki hafta",
            "onumuzdeki hafta",
            "haftaya",
        )
    ):
        return _shift_days(anchor, 7)
    return None


def parse_turkish_date(text: str, anchor: datetime) -> Optional[datetime]:
    """Bir tarih ifadesini ``anchor`` gününe göre çözer.

    Args:
        text: Deşifre metninde geçtiği hâliyle ifade ("cuma gününe kadar").
        anchor: Toplantının tarihi — göreli ifadelerin sayıldığı gün.

    Returns:
        Gün sonuna (23:59) ayarlanmış ``datetime`` (``anchor``ın saat dilimiyle)
        veya ifade tanınmadıysa ``None``. Tarih asla uydurulmaz.
    """
    normalised = normalise(text)
    if not normalised:
        return None

    for rule in (_parse_explicit, _parse_weekday, _parse_named_offset, _parse_duration):
        resolved = rule(normalised, anchor)
        if resolved is not None:
            return resolved
    return None


def parse_iso_date(text: str, anchor: datetime) -> Optional[datetime]:
    """Modelin gönderdiği ISO 8601 tahminini okur — yedek yol.

    Saatsiz bir tarih gün sonuna, saat dilimsiz bir damga ``anchor``ın saat
    dilimine tamamlanır. Okunamayan değer ``None`` döner.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    parsed: Optional[datetime] = None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        match = _ISO_RE.search(candidate)
        if not match:
            return None
        return _with_day(
            anchor, int(match.group(1)), int(match.group(2)), int(match.group(3))
        )
    if parsed.tzinfo is None and anchor.tzinfo is not None:
        parsed = parsed.replace(tzinfo=anchor.tzinfo)
    if parsed.tzinfo is not None and anchor.tzinfo is None:
        parsed = parsed.replace(tzinfo=None)
    if len(raw) <= 10:
        # Yalnızca tarih verilmiş: iş gün sonuna kadar.
        parsed = _end_of_day(parsed)
    return parsed


__all__ = [
    "END_OF_DAY_HOUR",
    "END_OF_DAY_MINUTE",
    "MONTHS",
    "NUMBER_WORDS",
    "WEEKDAYS",
    "normalise",
    "parse_iso_date",
    "parse_turkish_date",
]
