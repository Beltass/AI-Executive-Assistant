"""Block Kit sunumu — bir danışman raporunun Slack'te NASIL göründüğü.

Bu modül tek bir işi yapar: elinde bir :class:`ai_assistant.reports.PublishedReport`
(ya da özel bir ``Briefing``) olan çağıranlara, Slack'e olduğu gibi verilebilecek
``(text, blocks)`` çifti üretir. Gönderme işini yapmaz, ağa dokunmaz.

NEDEN AYRI BİR MODÜL
--------------------

Aynı sunum iki yerden gidiyor:

* :mod:`ai_assistant.notifiers.slack_notifier` — ana kanaldaki özet indeks;
* :mod:`ai_assistant.integrations.slack_channels` — her danışmanın kendi kanalı.

Biçimlendirme ikisinde de kopyalanınca biri düzelirken diğeri eski kalıyordu.
Artık ikisi de buradaki yapıcıları çağırıyor.

TASARIM: ÖNCE TELEFON
---------------------

Kullanıcı bu mesajları iPhone'da okuyor. Eski biçim üst üste yığılmış üç düz
``section`` bloğuydu — "alt alta çok karışık". Yeni düzen birkaç saniyede
taranacak şekilde kurulur:

1. ``header`` — emoji + danışman adı (telefonda tek bakışta okunan tek şey);
2. ``context`` — çalışma saati (İstanbul), okuma süresi, "yeni bulgu" rozeti;
3. ``section`` — ÖNE ÇIKAN cümle, alıntı çubuğuyla (``>``) ayrılmış;
4. ``section`` + ``fields`` — sayısal göstergeler; Slack bunları telefonda iki
   sütun hâlinde dizer, tablo hissi verir;
5. ``section`` — en çok :data:`MAX_BULLETS` kısa madde: bölüm başlığı + ilk cümle;
6. ``section`` — aksiyonlar (varsa), numaralı;
7. ``context`` — kaynaklar (varsa);
8. ``divider`` + ``context`` — panodaki TAM rapora bağlantı.

``actions`` bloğu ve düğme YOK: düğme tıklaması Slack'ten bir HTTPS ucuna POST
edilir, bu proje ise cron üzerinde açık uç olmadan çalışır (bkz.
:class:`ai_assistant.chat.menu.BlockRenderer`). Bağlantılar bu yüzden metin içi
``<url|etiket>`` biçiminde.

SLACK SINIRLARI
---------------

Sınırı aşan mesajı Slack tümden reddeder ve reddedilen brifing kaybolmuş
brifingdir. Bu yüzden her yapıcı kendini kırpar (:data:`MAX_SECTION_CHARS`,
:data:`MAX_BLOCKS`) ve kırpma SESSİZ OLMAZ: metin
:data:`TRUNCATION_NOTE` ile biter ve tam rapor bağlantısı her koşulda mesajda
kalır.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- Slack'in sert sınırları, güvenlik payıyla -------------------------------

#: Slack: 50 blok. Alt sınır bırakıyoruz ki altbilgi her zaman sığsın.
MAX_BLOCKS = 45
#: Slack: 3000 karakter (``section.text``).
MAX_SECTION_CHARS = 2900
#: Slack: 150 karakter, düz metin (``header``).
MAX_HEADER_CHARS = 145
#: Slack: 2000 karakter (``section.fields[]``).
MAX_FIELD_CHARS = 400
#: Slack: 10 alan (``section.fields``). Telefonda 5 satır × 2 sütun.
MAX_FIELDS = 10
#: Bildirim önizlemesi — bilerek kısa.
MAX_FALLBACK_CHARS = 300

#: Özet mesajda en çok kaç madde gösterilir.
MAX_BULLETS = 4
#: Bir maddenin uzunluğu (telefonda ~3 satır).
MAX_BULLET_CHARS = 200
#: En çok kaç aksiyon listelenir.
MAX_ACTIONS = 3
#: En çok kaç kaynak bağlantısı gösterilir.
MAX_SOURCES = 3
#: Öne çıkan cümlenin uzunluğu.
MAX_LEAD_CHARS = 400

#: Kırpma yapıldığında metnin sonuna düşen işaret — sessiz kayıp yok.
TRUNCATION_MARKER = "… devamı raporda"
TRUNCATION_NOTE = "… _devamı raporda_"

DASHBOARD_BASE_URL_ENV = "DASHBOARD_BASE_URL"
DEFAULT_DASHBOARD_BASE_URL = "https://beltass.github.io/AI-Executive-Assistant/"


# --- metin dönüşümleri ------------------------------------------------------

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_MD_BULLET = re.compile(r"^([ \t]*)[*+-][ \t]+", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def to_mrkdwn(text: str) -> str:
    """Danışmanların Markdown'ını Slack'in ``mrkdwn`` lehçesine çevirir.

    Slack ``*kalın*`` kullanır (``**kalın**`` değil), bağlantıları
    ``<url|etiket>`` yazar, başlığı hiç tanımaz ve Markdown listesi RENDER
    ETMEZ — ``- madde`` satırı olduğu gibi görünür. Bu yüzden liste imleri
    gerçek madde işaretine (``•``) çevrilir; telefonda okunaklı tek biçim bu.
    """
    out = _MD_LINK.sub(r"<\2|\1>", str(text or ""))
    out = _MD_BOLD.sub(r"*\1*", out)
    out = _MD_HEADING.sub("", out)
    out = _MD_BULLET.sub(r"\1• ", out)
    out = _BLANK_LINES.sub("\n\n", out)
    return out.strip()


def plain(text: str) -> str:
    """Tek satıra indirgenmiş, imsiz metin (başlık ve bildirim metni için)."""
    stripped = _MD_LINK.sub(r"\1", str(text or ""))
    stripped = _MD_HEADING.sub("", stripped)
    stripped = stripped.replace("**", "").replace("*", "").replace("`", "")
    stripped = stripped.replace(">", " ")
    return " ".join(stripped.split())


def clip(text: str, limit: int, marker: str = "…") -> str:
    """``limit`` karakteri aşan metni KELİME sınırında keser ve işaretler.

    Kırpma her zaman görünür: cümlenin ortasında sessizce bitmez.
    """
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    room = max(0, limit - len(marker))
    cut = body[:room]
    space = cut.rfind(" ")
    if space > room * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-") + marker


def chunks(text: str, size: int = MAX_SECTION_CHARS) -> List[str]:
    """Uzun bir gövdeyi paragraf sınırlarından ``size``a sığacak parçalara böler."""
    body = str(text or "").strip()
    if not body:
        return []
    parts: List[str] = []
    current = ""
    for paragraph in body.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(paragraph) > size:
            parts.append(paragraph[:size])
            paragraph = paragraph[size:]
        current = paragraph
    if current:
        parts.append(current)
    return parts


def _content_lines(text: str) -> List[str]:
    """Madde olmaya aday satırlar, imlerinden arındırılmış.

    Maddeler DÜZ metindir: kırpılan bir satırda yarım kalan ``*`` Slack'te
    olduğu gibi görünür, o yüzden im hiç taşınmaz — vurguyu madde başlığı verir.
    """
    out: List[str] = []
    for raw in str(text or "").split("\n"):
        line = plain(raw.strip().lstrip("*+-•").strip())
        # Ayraç satırları ("— — —") ve boş satırlar madde olamaz.
        if len(line) < 12 or not any(ch.isalnum() for ch in line):
            continue
        out.append(line)
    return out


def first_sentence(text: str, limit: int = MAX_BULLET_CHARS) -> str:
    """Bir gövdenin ilk anlamlı cümlesi — madde metni olarak kullanılır."""
    for line in _content_lines(text):
        return clip(_SENTENCE_END.split(line)[0].strip() or line, limit)
    return ""


# --- blok yapıcıları --------------------------------------------------------


def header(text: str) -> Dict[str, Any]:
    """``header`` bloğu: düz metin, im yok, 150 karakter sert sınır."""
    return {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": clip(plain(text), MAX_HEADER_CHARS) or "Rapor",
            "emoji": True,
        },
    }


def section(text: str) -> Dict[str, Any]:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": _fit_section(text)},
    }


def context(text: str) -> Dict[str, Any]:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": _fit_section(text)}],
    }


def divider() -> Dict[str, Any]:
    return {"type": "divider"}


def _fit_section(text: str) -> str:
    """Bir blok metnini Slack'in 3000 karakter sınırına sığdırır, işaretleyerek."""
    body = str(text or "")
    if len(body) <= MAX_SECTION_CHARS:
        return body
    return clip(body, MAX_SECTION_CHARS, marker=TRUNCATION_NOTE)


def fields_section(pairs: Sequence[Tuple[str, str]], title: str = "") -> Optional[Dict[str, Any]]:
    """Sayısal göstergeler için ``fields`` bloğu — Slack bunları ikişerli dizer.

    Telefonda okunan en iyi biçim bu: etiket üstte kalın, değer altında.
    """
    items = [(str(label or "").strip(), str(value or "").strip()) for label, value in pairs]
    items = [(label, value) for label, value in items if label or value]
    if not items:
        return None
    block: Dict[str, Any] = {
        "type": "section",
        "fields": [
            {
                "type": "mrkdwn",
                "text": clip(f"*{label}*\n{value or '—'}", MAX_FIELD_CHARS),
            }
            for label, value in items[:MAX_FIELDS]
        ],
    }
    if title:
        block["text"] = {"type": "mrkdwn", "text": _fit_section(title)}
    return block


def fit_blocks(
    blocks: Sequence[Dict[str, Any]],
    tail: Sequence[Dict[str, Any]] = (),
    limit: int = MAX_BLOCKS,
) -> List[Dict[str, Any]]:
    """Blok listesini ``limit``e sığdırır — ``tail`` HER ZAMAN korunur.

    ``tail`` rapora giden bağlantıdır: kırpılan mesajda kaybolması, kullanıcının
    eksik içeriğin devamına ulaşamaması demek olurdu.
    """
    keep = max(0, min(limit, 50) - len(tail))
    body = list(blocks)[:keep]
    return body + list(tail)


# --- pano bağlantısı --------------------------------------------------------


def dashboard_base_url() -> str:
    """Panonun herkese açık kök adresi, her zaman sonunda eğik çizgiyle."""
    raw = (os.getenv(DASHBOARD_BASE_URL_ENV) or "").strip() or DEFAULT_DASHBOARD_BASE_URL
    return raw if raw.endswith("/") else raw + "/"


def report_url(report: Any, base: str = "") -> str:
    """Bir danışman belgesinin panodaki derin bağlantısı."""
    route = str(getattr(report, "route", "") or "")
    return (base or dashboard_base_url()) + route


# --- raporun parçaları ------------------------------------------------------


def _meta_line(report: Any, new_findings: int = 0, now: Optional[datetime] = None) -> str:
    """Başlığın altındaki tek bağlam satırı: saat · okuma süresi · tazelik."""
    stamp = str(getattr(report, "generated_at_istanbul", "") or "").strip()
    if not stamp and now is not None:
        stamp = now.strftime("%d.%m.%Y %H:%M")
    bits = [f"🕒 {stamp}" if stamp else ""]
    minutes = int(getattr(report, "read_minutes", 0) or 0)
    if minutes:
        bits.append(f"⏱️ ~{minutes} dk okuma")
    if new_findings:
        bits.append(f"🆕 {new_findings} yeni bulgu")
    actions = list(getattr(report, "action_items", []) or [])
    if actions:
        bits.append(f"✅ {len(actions)} aksiyon")
    return " · ".join(bit for bit in bits if bit)


def _metric_pairs(report: Any) -> List[Tuple[str, str]]:
    """``key_metrics`` -> ``fields`` çiftleri, eğilim okuyla."""
    arrow = {"up": " ↑", "down": " ↓", "flat": " →"}
    pairs: List[Tuple[str, str]] = []
    for metric in list(getattr(report, "key_metrics", []) or []):
        label = plain(getattr(metric, "label", "") or "")
        value = plain(getattr(metric, "value", "") or "")
        unit = plain(getattr(metric, "unit", "") or "")
        if unit:
            value = f"{value} {unit}".strip()
        value += arrow.get(str(getattr(metric, "trend", "") or ""), "")
        if label or value:
            pairs.append((label, value))
    return pairs


def sentences(text: str, limit: int = MAX_BULLET_CHARS) -> List[str]:
    """Bir gövdenin cümleleri, madde olabilecek kadar anlamlı olanlar."""
    out: List[str] = []
    for line in _content_lines(text):
        for piece in _SENTENCE_END.split(line):
            piece = piece.strip()
            if len(piece) >= 12:
                out.append(clip(piece, limit))
    return out


def _bullets(report: Any, skip: str = "") -> Tuple[List[str], bool]:
    """Raporun en çok :data:`MAX_BULLETS` kısa maddesi + kırpıldı mı bilgisi.

    Önce BAŞLIKLI bölümler denenir ("başlık — ilk cümle"): raporun kendi
    iskeleti budur ve telefonda en iyi taranan biçim odur. Rapor başlıksızsa
    (hava durumu gibi kısa bölümler) gövdenin ilk cümleleri madde olur. Öne
    çıkan cümlenin kendisi hiçbir durumda tekrar edilmez.
    """
    normal = plain(skip).casefold()
    parts = list(getattr(report, "sections", []) or [])

    titled: List[str] = []
    for part in parts:
        title = plain(getattr(part, "title", "") or "")
        if not title:
            continue
        lead = first_sentence(getattr(part, "body", "") or "")
        if lead and plain(lead).casefold() == normal:
            lead = ""
        titled.append(f"*{clip(title, 80)}* — {lead}" if lead else f"*{clip(title, 120)}*")
    if titled:
        return titled[:MAX_BULLETS], len(titled) > MAX_BULLETS

    body = "\n".join(str(getattr(part, "body", "") or "") for part in parts)
    flowing = [
        line
        for line in sentences(body or str(getattr(report, "markdown", "") or ""))
        if plain(line).casefold() != normal
    ]
    return flowing[:MAX_BULLETS], len(flowing) > MAX_BULLETS


def _bullet_block(bullets: Sequence[str], more: bool) -> Optional[Dict[str, Any]]:
    if not bullets:
        return None
    lines = [f"•  {clip(b, MAX_BULLET_CHARS + 100)}" for b in bullets]
    text = "*Öne çıkanlar*\n" + "\n".join(lines)
    if more:
        text += f"\n{TRUNCATION_NOTE}"
    return section(text)


def _action_block(report: Any) -> Optional[Dict[str, Any]]:
    actions = list(getattr(report, "action_items", []) or [])
    if not actions:
        return None
    lines = []
    for index, item in enumerate(actions[:MAX_ACTIONS], start=1):
        text = plain(getattr(item, "text", "") or "")
        deadline = plain(getattr(item, "deadline", "") or "")
        line = f"{index}.  {clip(text, MAX_BULLET_CHARS)}"
        if deadline:
            line += f" _({deadline})_"
        lines.append(line)
    if len(actions) > MAX_ACTIONS:
        lines.append(f"{TRUNCATION_NOTE}")
    return section("*✅ Bugünün aksiyonları*\n" + "\n".join(lines))


def _source_block(report: Any) -> Optional[Dict[str, Any]]:
    sources = list(getattr(report, "sources", []) or [])
    links = []
    for source in sources[:MAX_SOURCES]:
        url = str(getattr(source, "url", "") or "").strip()
        title = plain(getattr(source, "title", "") or "") or url
        if url:
            links.append(f"<{url}|{clip(title, 60)}>")
    if not links:
        return None
    tail = f" · +{len(sources) - len(links)} kaynak" if len(sources) > len(links) else ""
    return context("🔗 " + " · ".join(links) + tail)


def _footer(url: str, base: str) -> List[Dict[str, Any]]:
    """Mesajın sonu: tam rapora ve panoya bağlantı.

    :func:`fit_blocks` bunu ``tail`` olarak taşır, yani mesaj ne kadar kırpılırsa
    kırpılsın bu iki bağlantı her zaman kalır — kırpılan içeriğin devamına
    ulaşmanın tek yolu bu.
    """
    parts = [
        f"📄 *<{url}|Tam raporu aç>*" if url else "",
        f"<{base}|📊 Pano>" if base else "",
    ]
    line = " · ".join(p for p in parts if p)
    return [divider(), section(line)] if line else [divider()]


# --- kamuya açık yapıcılar --------------------------------------------------


def report_blocks(
    report: Any,
    base_url: str = "",
    new_findings: int = 0,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Yayımlanmış bir raporun kendi kanalına giden Block Kit gövdesi."""
    base = base_url or dashboard_base_url()
    url = report_url(report, base)
    emoji = str(getattr(report, "emoji", "") or "🧩")
    name = str(getattr(report, "name", "") or "Rapor")
    # Plain, not mrkdwn: the lead is wrapped in *bold* below and a nested (or
    # half-clipped) ``*`` would leak into the rendered message as a literal.
    headline = plain(getattr(report, "headline", "") or "")
    excerpt = plain(getattr(report, "excerpt", "") or "")

    blocks: List[Dict[str, Any]] = [header(f"{emoji} {name}")]

    meta = _meta_line(report, new_findings=new_findings, now=now)
    if meta:
        blocks.append(context(meta))

    lead = headline or excerpt
    blocks.append(
        section(f">*{clip(lead, MAX_LEAD_CHARS)}*" if lead else "_(özet çıkarılamadı)_")
    )

    metrics = fields_section(_metric_pairs(report))
    if metrics is not None:
        blocks.append(metrics)

    bullets, more = _bullets(report, skip=lead)
    bullet_block = _bullet_block(bullets, more)
    if bullet_block is not None:
        blocks.append(divider())
        blocks.append(bullet_block)
    elif excerpt and excerpt != headline:
        blocks.append(section(clip(excerpt, MAX_BULLET_CHARS + 200)))

    action_block = _action_block(report)
    if action_block is not None:
        blocks.append(action_block)

    source_block = _source_block(report)
    if source_block is not None:
        blocks.append(source_block)

    # Rapor gövdesinin tamamı hiçbir zaman Slack'e gitmez; bağlantı bu yüzden
    # zorunlu ve altbilgi her koşulda korunur.
    return fit_blocks(blocks, tail=_footer(url, base))


def build_report_message(
    report: Any,
    base_url: str = "",
    new_findings: int = 0,
    now: Optional[datetime] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """``(bildirim metni, bloklar)`` — Slack blocks ile birlikte metin İSTER."""
    blocks = report_blocks(report, base_url=base_url, new_findings=new_findings, now=now)
    emoji = str(getattr(report, "emoji", "") or "🧩")
    name = plain(getattr(report, "name", "") or "Rapor")
    headline = plain(getattr(report, "headline", "") or "")
    text = f"{emoji} {name}" + (f" — {headline}" if headline else "")
    return clip(text, MAX_FALLBACK_CHARS), blocks


def briefing_blocks(
    title: str,
    briefing: Any,
    emoji: str = "🧩",
    max_body_blocks: int = 3,
) -> List[Dict[str, Any]]:
    """Özel (panoya yazılmayan) bir bölümün kendi kanalına giden gövdesi.

    Bunun panoda bir belgesi YOKTUR, dolayısıyla bağlanacak bir yer de yoktur:
    gövde burada tam hâliyle taşınır, yalnızca Slack'in blok sınırı kadar.
    """
    body = to_mrkdwn(str(getattr(briefing, "text", "") or "").strip())
    blocks: List[Dict[str, Any]] = [
        header(f"{emoji} {title}"),
        context("🔒 Kişisel veri — panoya yazılmaz, yalnızca bu kanalda."),
        divider(),
    ]
    parts = chunks(body) or ["_(bu çalıştırmada içerik üretilmedi)_"]
    for part in parts[:max_body_blocks]:
        blocks.append(section(part))
    if len(parts) > max_body_blocks:
        blocks.append(
            context("… bölümün kalanı Slack uzunluk sınırı nedeniyle kısaltıldı.")
        )
    return fit_blocks(blocks)


def build_briefing_message(
    title: str,
    briefing: Any,
    emoji: str = "🧩",
    max_body_blocks: int = 3,
) -> Tuple[str, List[Dict[str, Any]]]:
    """``(bildirim metni, bloklar)`` — özel bölüm için."""
    blocks = briefing_blocks(title, briefing, emoji=emoji, max_body_blocks=max_body_blocks)
    return clip(f"{emoji} {plain(title)}", MAX_FALLBACK_CHARS), blocks
