"""Menü soyutlaması — numaralı metin BUGÜN, Block Kit düğmesi YARIN.

Durum makinesi hiçbir zaman metin üretmez; bir :class:`Prompt` üretir: başlık,
seçenekler, çoklu seçim mi, serbest metin kabul ediyor mu. Bunu kanala ne
göndereceğine bir :class:`Renderer` karar verir:

* :class:`TextRenderer` — numaralı liste ("1, 2, 3 — numarayı yazın"). Bu proje
  GitHub Actions cron üzerinde çalıştığı ve düğme yükünü alacak bir HTTPS ucu
  OLMADIĞI için varsayılan budur.
* :class:`BlockRenderer` — aynı ``Prompt``ı Slack düğmelerine çevirir. Bugün
  kullanılmıyor; bir gün bir sunucu geldiğinde akışın geri kalanına
  dokunulmadan devreye alınabilsin diye burada duruyor ve testleri var.

Girdi çözümü de aynı yerden geçer: :func:`resolve` yazılan numarayı, seçenek
etiketini ya da (ileride) düğmenin ``action_id``sini AYNI seçenek değerine
çevirir. Böylece durum makinesi "kullanıcı ne tıkladı/yazdı" ayrımını hiç görmez.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

#: Her adımda geçerli olan genel komutlar.
COMMAND_BACK = "geri"
COMMAND_CANCEL = "iptal"
COMMAND_RESTART = "bastan"
COMMAND_HELP = "yardim"

_COMMAND_WORDS: Dict[str, str] = {
    "geri": COMMAND_BACK,
    "geri dön": COMMAND_BACK,
    "geri don": COMMAND_BACK,
    "önceki": COMMAND_BACK,
    "onceki": COMMAND_BACK,
    "b": COMMAND_BACK,
    "iptal": COMMAND_CANCEL,
    "vazgeç": COMMAND_CANCEL,
    "vazgec": COMMAND_CANCEL,
    "dur": COMMAND_CANCEL,
    "baştan": COMMAND_RESTART,
    "bastan": COMMAND_RESTART,
    "baştan başla": COMMAND_RESTART,
    "bastan basla": COMMAND_RESTART,
    "sıfırla": COMMAND_RESTART,
    "sifirla": COMMAND_RESTART,
    "yardım": COMMAND_HELP,
    "yardim": COMMAND_HELP,
    "?": COMMAND_HELP,
}

#: Menünün altına düşülen kısa hatırlatma.
FOOTER = "_Her adımda: `geri` · `baştan` · `iptal`_"

_SPLIT = re.compile(r"[,\s;+]+")


def normalize(text: str) -> str:
    """Karşılaştırma için sadeleştirilmiş metin: küçük harf, tek boşluk."""
    folded = str(text or "").strip().casefold()
    # Türkçe "İ" casefold'da "i̇" (i + birleşen nokta) üretir; tek "i" yapılır.
    folded = folded.replace("i̇", "i")
    return re.sub(r"\s+", " ", folded)


def command_of(text: str) -> str:
    """Genel komutu tanır: ``geri`` / ``iptal`` / ``bastan`` / ``yardim`` / ``""``."""
    return _COMMAND_WORDS.get(normalize(text), "")


@dataclass(frozen=True)
class Option:
    """Bir menü seçeneği. ``value`` durum makinesinin gördüğü tek şeydir."""

    value: str
    label: str
    hint: str = ""

    def action_id(self, step: str) -> str:
        """Düğmeye geçildiğinde kullanılacak kimlik."""
        return f"{step}:{self.value}"


@dataclass
class Prompt:
    """Bir adımın kullanıcıya sorduğu şey — biçimden bağımsız."""

    step: str
    title: str
    options: List[Option] = field(default_factory=list)
    #: Birden çok seçenek işaretlenebilir mi ("1,3,5")?
    multi: bool = False
    #: Numara yerine serbest metin de kabul edilir mi (yapıştırma, tarih)?
    free_text: bool = False
    #: Başlığın altına yazılan açıklama.
    note: str = ""
    #: Girdi tanınmadığında başa eklenen düzeltme cümlesi.
    clarification: str = ""
    #: Menüsüz, yalnızca bilgi veren adımlar için.
    footer: bool = True

    def option(self, value: str) -> Optional[Option]:
        return next((o for o in self.options if o.value == value), None)


@dataclass
class Selection:
    """Kullanıcı girdisinin çözümü."""

    ok: bool = False
    values: List[str] = field(default_factory=list)
    text: str = ""
    error: str = ""

    @property
    def value(self) -> str:
        return self.values[0] if self.values else ""


class Renderer:
    """Bir ``Prompt``ı Slack'e gidecek yüke çeviren arayüz."""

    def render(self, prompt: Prompt) -> Dict[str, Any]:  # pragma: no cover - arayüz
        raise NotImplementedError


class TextRenderer(Renderer):
    """Numaralı metin menüsü — düğme gerektirmeyen, cron'la çalışan biçim."""

    def render(self, prompt: Prompt) -> Dict[str, Any]:
        return {"text": self.text(prompt)}

    def text(self, prompt: Prompt) -> str:
        lines: List[str] = []
        if prompt.clarification:
            lines.append(prompt.clarification)
        lines.append(f"*{prompt.title}*")
        if prompt.note:
            lines.append(prompt.note)
        if prompt.options:
            lines.append("")
            for index, option in enumerate(prompt.options, start=1):
                suffix = f" — _{option.hint}_" if option.hint else ""
                lines.append(f"`{index}` {option.label}{suffix}")
            lines.append("")
            lines.append(
                "Birden fazla seçebilirsiniz: `1,3,5`"
                if prompt.multi
                else "Numarayı yazın."
            )
        if prompt.footer:
            lines.append(FOOTER)
        return "\n".join(lines).strip()


class BlockRenderer(Renderer):
    """Aynı ``Prompt``ın Block Kit düğmeli karşılığı.

    BUGÜN KULLANILMIYOR: düğme tıklaması Slack'ten bir HTTPS ucuna ``POST``
    edilir ve bu proje cron üzerinde, açık uç olmadan çalışır. Akışın biçimden
    bağımsız olduğunun kanıtı ve o uç bir gün geldiğinde tek satırlık geçiş
    noktası olarak burada duruyor.
    """

    #: Slack bir ``actions`` bloğuna en çok bu kadar öğe alır.
    MAX_ELEMENTS = 5

    def render(self, prompt: Prompt) -> Dict[str, Any]:
        text = f"*{prompt.title}*"
        blocks: List[Dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}}
        ]
        if prompt.note:
            blocks.append(
                {"type": "context", "elements": [{"type": "mrkdwn", "text": prompt.note}]}
            )
        buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": option.label[:75], "emoji": True},
                "value": option.value,
                "action_id": option.action_id(prompt.step),
            }
            for option in prompt.options
        ]
        for start in range(0, len(buttons), self.MAX_ELEMENTS):
            blocks.append(
                {"type": "actions", "elements": buttons[start : start + self.MAX_ELEMENTS]}
            )
        return {"text": prompt.title, "blocks": blocks}


def resolve(prompt: Prompt, raw: str) -> Selection:
    """Yazılanı seçenek değerlerine çevirir.

    Sırasıyla denenir: ``action_id`` (düğme yolu), numara(lar), seçenek etiketi,
    seçenek değeri. Hiçbiri tutmazsa ve adım serbest metin kabul ediyorsa metnin
    kendisi döner; etmiyorsa Türkçe bir hata döner — TAHMİN YOK.
    """
    text = str(raw or "").strip()
    if not text:
        return Selection(error="Boş mesaj geldi.")

    # Düğme yolu: "adim:deger" biçimindeki action_id doğrudan çözülür.
    if ":" in text and not prompt.multi:
        step, _, value = text.partition(":")
        if step == prompt.step and prompt.option(value) is not None:
            return Selection(ok=True, values=[value], text=text)

    tokens = [t for t in _SPLIT.split(text) if t]
    numeric = [t for t in tokens if t.isdigit()]

    # Tümü numara mı? (Çoklu seçimde "1,3,5", tekli seçimde "2".)
    if numeric and len(numeric) == len(tokens):
        if not prompt.multi and len(numeric) > 1:
            return Selection(
                error="Bu adımda tek seçim yapılır; yalnızca bir numara yazın."
            )
        values: List[str] = []
        for token in numeric:
            index = int(token)
            if index < 1 or index > len(prompt.options):
                return Selection(
                    error=f"`{index}` listede yok; 1–{len(prompt.options)} arası bir numara yazın."
                )
            value = prompt.options[index - 1].value
            if value not in values:
                values.append(value)
        return Selection(ok=True, values=values, text=text)

    # Etiket ya da değer yazılmış olabilir ("excel", "trend çizgisi").
    needle = normalize(text)
    for option in prompt.options:
        if needle in (normalize(option.label), normalize(option.value)):
            return Selection(ok=True, values=[option.value], text=text)

    if prompt.free_text:
        return Selection(ok=True, values=[], text=text)

    if not prompt.options:
        return Selection(error="Bu adımda beklenen bir girdi yok.")

    return Selection(
        error=(
            "Bunu anlayamadım. Listedeki numarayı yazın"
            + (" (birden fazlaysa `1,3,5` gibi)." if prompt.multi else ".")
        )
    )


def numbered(options: Sequence[Option]) -> List[str]:
    """Seçenekleri "1) etiket" satırlarına çevirir (log ve test kolaylığı)."""
    return [f"{index}) {option.label}" for index, option in enumerate(options, start=1)]


__all__ = [
    "BlockRenderer",
    "COMMAND_BACK",
    "COMMAND_CANCEL",
    "COMMAND_HELP",
    "COMMAND_RESTART",
    "FOOTER",
    "Option",
    "Prompt",
    "Renderer",
    "Selection",
    "TextRenderer",
    "command_of",
    "normalize",
    "numbered",
    "resolve",
]
