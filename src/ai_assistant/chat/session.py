"""Kullanıcı başına sohbet durum makinesi — yedi adımda bir rapor siparişi.

    1  Veri kaynağı    → Drive'daki e-tablolar, veri yapıştırma, son kaynak
    2  Dönem           → bugün / bu hafta / bu ay / son 3 ay / özel aralık
    3  Kırılım         → çoklu seçim, GERÇEK sütunlardan
    4  Metrikler       → çoklu seçim, GERÇEK sayısal sütunlardan
    5  Görselleştirme  → trend / çubuk / halka / yoğunluk / sadece tablo
    6  Format          → tarayıcı raporu / Excel / ikisi
    7  Özet ve onay    → seçimler tekrarlanır, "onay" beklenir

DURUM DİSKTE DURUR. Her cron yoklaması yeni bir süreçtir; kullanıcıya menüyü
gösteren süreç, cevabı okuyan süreç DEĞİLDİR. Bu yüzden konuşma her mesajdan
sonra :class:`ai_assistant.chat.store.ChatStore` ile yazılır ve her mesaptan
önce oradan okunur.

ÜÇ KOMUT HER ADIMDA GEÇERLİ: ``geri`` (bir adım geri, yığın üzerinden),
``baştan`` (siparişi sıfırla), ``iptal`` (siparişi kapat).

TAHMİN YOK: tanınmayan girdi menüyü kısa bir Türkçe düzeltmeyle yeniden gösterir.
Motor asla "herhalde şunu demek istedi" diye ilerlemez.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..analysis.dataset import Dataset, DatasetError, load_any, load_text
from . import intent as intent_mod
from . import sources as sources_mod
from . import templates as templates_mod
from .columns import (
    dimension_options,
    metric_options,
    options_as_dicts,
    options_from_dicts,
)
from .menu import (
    COMMAND_BACK,
    COMMAND_CANCEL,
    COMMAND_HELP,
    COMMAND_RESTART,
    Option,
    Prompt,
    Renderer,
    Selection,
    TextRenderer,
    command_of,
    normalize,
    resolve,
)
from .spec import (
    CHART_BAR,
    CHART_DONUT,
    CHART_HEATMAP,
    CHART_LINE,
    CHART_TABLE,
    FORMAT_WEB,
    FORMAT_XLSX,
    PERIOD_CUSTOM,
    PERIOD_MONTH,
    PERIOD_QUARTER,
    PERIOD_TODAY,
    PERIOD_WEEK,
    ReportSpec,
    SOURCE_DRIVE,
    SOURCE_PASTE,
    SOURCE_PATH,
)
from .store import ChatStore

logger = logging.getLogger(__name__)

STEP_SOURCE = "kaynak"
STEP_PASTE = "yapistir"
STEP_PERIOD = "donem"
STEP_RANGE = "aralik"
STEP_DIMENSIONS = "kirilim"
STEP_METRICS = "metrik"
STEP_CHART = "gorsel"
STEP_FORMAT = "format"
STEP_CONFIRM = "onay"

#: Numaralandırılan ana akış. Ara adımlar (yapıştırma, özel aralık) bu sırada
#: yer almaz; bir ana adımın içinden açılır ve ona geri döner.
MAIN_STEPS = (
    STEP_SOURCE,
    STEP_PERIOD,
    STEP_DIMENSIONS,
    STEP_METRICS,
    STEP_CHART,
    STEP_FORMAT,
    STEP_CONFIRM,
)

STEP_HEADINGS = {
    STEP_SOURCE: "Veri kaynağı",
    STEP_PERIOD: "Dönem",
    STEP_DIMENSIONS: "Kırılım",
    STEP_METRICS: "Metrikler",
    STEP_CHART: "Görselleştirme",
    STEP_FORMAT: "Format",
    STEP_CONFIRM: "Özet ve onay",
}

#: "Motor seçsin" — kırılım/metrik adımlarında geçerli bir cevaptır.
AUTO = "__auto__"

#: Kaynak adımının özel seçenekleri.
SOURCE_PASTE_VALUE = "__paste__"
SOURCE_LAST_VALUE = "__last__"

#: Onay adımında "evet" demenin kabul edilen biçimleri.
_CONFIRM_WORDS = {"onay", "onayla", "evet", "tamam", "olur", "hadi", "gönder", "gonder"}

#: Sohbeti başlatan kelimeler.
_START_WORDS = {
    "rapor",
    "yeni rapor",
    "rapor al",
    "rapor istiyorum",
    "başla",
    "basla",
    "merhaba",
    "selam",
    "menü",
    "menu",
}

_DATE_RE = re.compile(
    r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})|(\d{4})-(\d{1,2})-(\d{1,2})"
)


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


@dataclass
class Conversation:
    """Tek kullanıcının yarım kalmış siparişi — diske yazılan hâliyle."""

    channel: str = ""
    user: str = ""
    step: str = STEP_SOURCE
    #: ``geri`` için adım yığını (ara adımlar dahil).
    stack: List[str] = field(default_factory=list)
    spec: ReportSpec = field(default_factory=ReportSpec)
    #: Kullanıcının AÇIKÇA cevapladığı adımlar ("otomatik" de bir cevaptır).
    decided: List[str] = field(default_factory=list)
    source_options: List[Dict[str, str]] = field(default_factory=list)
    dimension_options: List[Dict[str, str]] = field(default_factory=list)
    metric_options: List[Dict[str, str]] = field(default_factory=list)
    #: Veri BİR KEZ okundu ve seçenekler türetildi mi? Boş seçenek listesi de
    #: geçerli bir sonuçtur (kırılıma uygun sütunu olmayan veri), o yüzden
    #: "okundu mu" sorusunun ayrı bir cevabı olmak zorunda.
    data_ready: bool = False
    #: Hızlı yolu doğuran cümle — kaynak seçilince veriye bağlanır.
    intent_text: str = ""
    intent_grounded: bool = False
    updated_at: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "user": self.user,
            "step": self.step,
            "stack": list(self.stack),
            "spec": self.spec.as_dict(),
            "decided": list(self.decided),
            "source_options": list(self.source_options),
            "dimension_options": list(self.dimension_options),
            "metric_options": list(self.metric_options),
            "data_ready": self.data_ready,
            "intent_text": self.intent_text,
            "intent_grounded": self.intent_grounded,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Conversation":
        payload = data if isinstance(data, dict) else {}
        conv = cls(
            channel=str(payload.get("channel") or ""),
            user=str(payload.get("user") or ""),
            step=str(payload.get("step") or STEP_SOURCE),
            spec=ReportSpec.from_dict(payload.get("spec")),
            data_ready=bool(payload.get("data_ready")),
            intent_text=str(payload.get("intent_text") or ""),
            intent_grounded=bool(payload.get("intent_grounded")),
            updated_at=str(payload.get("updated_at") or ""),
        )
        for name in ("stack", "decided"):
            value = payload.get(name)
            if isinstance(value, list):
                setattr(conv, name, [str(item) for item in value])
        for name in ("source_options", "dimension_options", "metric_options"):
            value = payload.get(name)
            if isinstance(value, list):
                setattr(
                    conv, name, [item for item in value if isinstance(item, dict)]
                )
        return conv

    # --- adım durumu --------------------------------------------------------

    def answered(self, step: str) -> bool:
        """Bu adım cevaplanmış mı? (Hızlı yol da adım cevaplar.)"""
        if step in self.decided:
            return True
        if step == STEP_SOURCE:
            return self.spec.has_source()
        if step == STEP_PERIOD:
            return self.spec.has_period()
        if step == STEP_DIMENSIONS:
            return bool(self.spec.dimensions)
        if step == STEP_METRICS:
            return bool(self.spec.metrics)
        if step == STEP_CHART:
            return bool(self.spec.chart)
        if step == STEP_FORMAT:
            return bool(self.spec.formats)
        return False

    def mark(self, step: str) -> None:
        if step not in self.decided:
            self.decided.append(step)

    def unmark(self, step: str) -> None:
        if step in self.decided:
            self.decided.remove(step)


@dataclass
class Turn:
    """Bir mesaja verilen cevap."""

    messages: List[str] = field(default_factory=list)
    #: Doluysa rapor ÜRETİLECEK (yoklayıcı çalıştırır).
    spec: Optional[ReportSpec] = None
    #: Konuşma kapandı mı?
    ended: bool = False
    #: Hiçbir şey yapılmadı (mesaj bu katmanı ilgilendirmiyor).
    ignored: bool = False


def default_loader(spec: ReportSpec) -> Dataset:
    """Tarifin işaret ettiği veriyi okur. Ağ/dosya hataları ``DatasetError``."""
    if spec.source_kind == SOURCE_PASTE:
        return load_text(spec.pasted, name=spec.source_label or "Yapıştırılan veri")
    return load_any(spec.source, sheet=spec.sheet, name=spec.source_label)


class SessionEngine:
    """Menü akışını yürüten durum makinesi. AĞA ÇIKMAZ.

    Slack'e tek bir satır bile yazmaz: mesajları :class:`Turn` içinde döner ve
    onları kanala koymak yoklayıcının işidir. Bu ayrım testleri tamamen ağsız
    yapar ve düğmeli bir arayüz geldiğinde akışın değişmemesini sağlar.
    """

    def __init__(
        self,
        store: Optional[ChatStore] = None,
        loader: Optional[Callable[[ReportSpec], Dataset]] = None,
        source_lister: Optional[Callable[[], List[Any]]] = None,
        renderer: Optional[Renderer] = None,
        now: Optional[datetime] = None,
    ):
        self.store = store or ChatStore()
        self.loader = loader or default_loader
        self.source_lister = source_lister or sources_mod.list_recent_sources
        self.renderer = renderer or TextRenderer()
        self._now = now

    # --- genel giriş --------------------------------------------------------

    def handle(self, channel: str, user: str, text: str) -> Turn:
        """Bir kullanıcı mesajını işler ve verilecek cevabı döner."""
        body = str(text or "").strip()
        if not body:
            return Turn(ignored=True)

        payload = self.store.get_session(channel, user)
        conv = Conversation.from_dict(payload) if payload else None

        try:
            turn = (
                self._continue(conv, body)
                if conv is not None
                else self._start(channel, user, body)
            )
        except Exception as exc:  # pragma: no cover - son savunma hattı
            logger.exception("sohbet adımı çöktü: %s", exc)
            self.store.drop_session(channel, user)
            self.store.save()
            return Turn(
                messages=[
                    "Beklenmedik bir hata oldu ve siparişi kapatmak zorunda kaldım "
                    f"(`{type(exc).__name__}`). `rapor` yazarak yeniden başlayabilirsiniz."
                ],
                ended=True,
            )
        return turn

    # --- başlangıç ----------------------------------------------------------

    def _start(self, channel: str, user: str, body: str) -> Turn:
        """Açık bir sipariş yokken gelen mesaj."""
        command = command_of(body)
        if command == COMMAND_CANCEL:
            return Turn(messages=["Devam eden bir sipariş yok."], ended=True)

        # Şablon komutları sohbet açmadan çalışır.
        result = templates_mod.handle(body, self.store, user, now=self._now)
        if result.handled:
            if result.spec is not None:
                return Turn(messages=result.messages, spec=result.spec)
            return Turn(messages=result.messages)

        conv = Conversation(channel=channel, user=user, step=STEP_SOURCE)
        messages: List[str] = []

        if command == COMMAND_HELP:
            messages.append(self._help_text())
        elif normalize(body) in _START_WORDS:
            messages.append(
                "Rapor siparişini alıyorum — yedi adım, her adımda numarayı yazın."
            )
        elif intent_mod.looks_like_request(body):
            return self._start_fast(conv, body)
        else:
            messages.append(
                "Bu mesajı bir rapor isteği olarak çözemedim, menüden ilerleyelim. "
                "İsterseniz tek cümleyle de yazabilirsiniz: "
                "_“son 3 ay vardiya bazında SLA, haftalık trend, Excel”_."
            )

        messages.append(self._render(self._prompt(conv)))
        self._persist(conv)
        return Turn(messages=messages)

    def _start_fast(self, conv: Conversation, body: str) -> Turn:
        """Tek cümlelik istek: anlaşılanı söyle, eksiği sor."""
        parsed = intent_mod.parse(body)
        conv.spec = parsed.spec
        conv.intent_text = body
        for step, filled in (
            (STEP_PERIOD, conv.spec.has_period()),
            (STEP_CHART, bool(conv.spec.chart)),
            (STEP_FORMAT, bool(conv.spec.formats)),
        ):
            if filled:
                conv.mark(step)

        messages: List[str] = []
        echo = parsed.understood_text()
        if echo:
            messages.append(echo)
        messages.extend(self._advance(conv))
        self._persist(conv)
        return Turn(messages=messages)

    # --- devam --------------------------------------------------------------

    def _continue(self, conv: Conversation, body: str) -> Turn:
        command = command_of(body)

        if command == COMMAND_CANCEL:
            self.store.drop_session(conv.channel, conv.user)
            self.store.save()
            return Turn(
                messages=["Sipariş iptal edildi. `rapor` yazarak yeniden başlayabilirsiniz."],
                ended=True,
            )

        if command == COMMAND_RESTART:
            fresh = Conversation(channel=conv.channel, user=conv.user, step=STEP_SOURCE)
            self._persist(fresh)
            return Turn(
                messages=["Baştan başlıyoruz.", self._render(self._prompt(fresh))]
            )

        if command == COMMAND_BACK:
            return self._go_back(conv)

        if command == COMMAND_HELP:
            return Turn(messages=[self._help_text(), self._render(self._prompt(conv))])

        return self._apply(conv, body)

    def _go_back(self, conv: Conversation) -> Turn:
        """Bir önceki adıma döner ve O ADIMIN cevabını temizler.

        Cevabı temizlemek şart: aksi hâlde "geri" dedikten sonra aynı adım
        cevaplanmış sayılır ve akış kullanıcıyı hemen ileri fırlatır.
        """
        if not conv.stack:
            return Turn(
                messages=[
                    "Zaten ilk adımdayız.",
                    self._render(self._prompt(conv)),
                ]
            )
        previous = conv.stack.pop()
        self._clear(conv, previous)
        conv.step = previous
        self._persist(conv)
        return Turn(messages=[self._render(self._prompt(conv))])

    def _clear(self, conv: Conversation, step: str) -> None:
        """Bir adımın cevabını siler."""
        conv.unmark(step)
        spec = conv.spec
        if step == STEP_SOURCE:
            spec.source_kind = spec.source = spec.source_label = spec.pasted = ""
            conv.dimension_options = []
            conv.metric_options = []
            conv.data_ready = False
            conv.intent_grounded = False
        elif step == STEP_PASTE:
            spec.pasted = ""
            conv.unmark(STEP_SOURCE)
        elif step in (STEP_PERIOD, STEP_RANGE):
            spec.period = spec.date_from = spec.date_to = ""
            spec.last_days = 0
            conv.unmark(STEP_PERIOD)
        elif step == STEP_DIMENSIONS:
            spec.dimensions = []
        elif step == STEP_METRICS:
            spec.metrics = []
        elif step == STEP_CHART:
            spec.chart = ""
        elif step == STEP_FORMAT:
            spec.formats = []

    # --- adım uygulama ------------------------------------------------------

    def _apply(self, conv: Conversation, body: str) -> Turn:
        prompt = self._prompt(conv)
        selection = resolve(prompt, body)

        if not selection.ok:
            prompt.clarification = selection.error
            return Turn(messages=[self._render(prompt)])

        handler = {
            STEP_SOURCE: self._apply_source,
            STEP_PASTE: self._apply_paste,
            STEP_PERIOD: self._apply_period,
            STEP_RANGE: self._apply_range,
            STEP_DIMENSIONS: self._apply_dimensions,
            STEP_METRICS: self._apply_metrics,
            STEP_CHART: self._apply_chart,
            STEP_FORMAT: self._apply_format,
            STEP_CONFIRM: self._apply_confirm,
        }.get(conv.step)
        if handler is None:  # pragma: no cover - savunma
            conv.step = STEP_SOURCE
            self._persist(conv)
            return Turn(messages=[self._render(self._prompt(conv))])
        return handler(conv, selection, body)

    # 1 — kaynak
    def _apply_source(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        value = selection.value
        messages: List[str] = []

        if value == SOURCE_PASTE_VALUE:
            return self._enter(conv, STEP_PASTE, from_step=STEP_SOURCE)

        if value == SOURCE_LAST_VALUE:
            remembered = self.store.last_source(conv.user)
            if not remembered:
                prompt = self._prompt(conv)
                prompt.clarification = "Kayıtlı bir önceki kaynak yok."
                return Turn(messages=[self._render(prompt)])
            conv.spec.source_kind = str(remembered.get("kind") or SOURCE_DRIVE)
            conv.spec.source = str(remembered.get("id") or "")
            conv.spec.source_label = str(remembered.get("label") or "")
        elif value.startswith("drive:"):
            option = next(
                (o for o in conv.source_options if o.get("value") == value), {}
            )
            conv.spec.source_kind = SOURCE_DRIVE
            conv.spec.source = value.split(":", 1)[1]
            conv.spec.source_label = str(option.get("label") or "")
            if str(option.get("mime") or "") != sources_mod.MIME_GOOGLE_SHEET:
                messages.append(
                    "Not: bu dosya bir Google E-Tablo değil. Okunamazsa Drive'da "
                    "*Dosya → Google E-Tablolar olarak kaydet* deyip tekrar deneyin."
                )
        else:
            # Serbest metin: bağlantı, dosya yolu ya da doğrudan yapıştırılan tablo.
            raw = body.strip()
            if "\n" in raw or "\t" in raw:
                conv.spec.source_kind = SOURCE_PASTE
                conv.spec.pasted = raw
            else:
                conv.spec.source_kind = SOURCE_PATH
                conv.spec.source = raw
                conv.spec.source_label = raw.rsplit("/", 1)[-1][:60]

        conv.mark(STEP_SOURCE)
        messages.extend(self._after_source(conv))
        self._persist(conv)
        return Turn(messages=messages)

    # 1b — yapıştırma
    def _apply_paste(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        raw = body.strip()
        if len(raw.splitlines()) < 2:
            prompt = self._prompt(conv)
            prompt.clarification = (
                "Yapıştırılan metinde başlık satırının altında veri yok; "
                "en az iki satır gerekiyor."
            )
            return Turn(messages=[self._render(prompt)])
        conv.spec.source_kind = SOURCE_PASTE
        conv.spec.pasted = raw
        conv.spec.source_label = "Yapıştırılan veri"
        conv.mark(STEP_SOURCE)
        conv.mark(STEP_PASTE)
        messages = self._after_source(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 2 — dönem
    def _apply_period(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        if selection.value == PERIOD_CUSTOM:
            conv.spec.period = PERIOD_CUSTOM
            return self._enter(conv, STEP_RANGE, from_step=STEP_PERIOD)
        conv.spec.period = selection.value
        conv.spec.last_days = 0
        conv.spec.date_from = conv.spec.date_to = ""
        conv.mark(STEP_PERIOD)
        messages = self._advance(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 2b — özel aralık
    def _apply_range(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        start, end = parse_date_range(body)
        if start is None or end is None:
            prompt = self._prompt(conv)
            prompt.clarification = (
                "Tarih aralığını çözemedim. İki tarihi şu biçimde yazın: "
                "`01.07.2026 - 31.07.2026`."
            )
            return Turn(messages=[self._render(prompt)])
        if end < start:
            start, end = end, start
        conv.spec.date_from = start.isoformat()
        conv.spec.date_to = end.isoformat()
        conv.mark(STEP_PERIOD)
        conv.mark(STEP_RANGE)
        messages = self._advance(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 3 — kırılım
    def _apply_dimensions(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        values = [v for v in selection.values if v != AUTO]
        conv.spec.dimensions = values
        conv.mark(STEP_DIMENSIONS)
        messages = self._advance(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 4 — metrikler
    def _apply_metrics(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        values = [v for v in selection.values if v != AUTO]
        conv.spec.metrics = values
        conv.mark(STEP_METRICS)
        messages = self._advance(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 5 — görselleştirme
    def _apply_chart(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        conv.spec.chart = selection.value
        conv.mark(STEP_CHART)
        messages = self._advance(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 6 — format
    def _apply_format(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        value = selection.value
        conv.spec.formats = (
            [FORMAT_XLSX, FORMAT_WEB] if value == "both" else [value]
        )
        conv.mark(STEP_FORMAT)
        messages = self._advance(conv)
        self._persist(conv)
        return Turn(messages=messages)

    # 7 — onay
    def _apply_confirm(self, conv: Conversation, selection: Selection, body: str) -> Turn:
        word = normalize(body)

        # "… olarak kaydet" onay ekranında da çalışır.
        saved = templates_mod.handle(
            body, self.store, conv.user, current=conv.spec, now=self._now
        )
        if saved.handled and saved.spec is None:
            return Turn(messages=[*saved.messages, self._render(self._prompt(conv))])

        if selection.value == "restart" or word in ("değiştir", "degistir"):
            fresh = Conversation(channel=conv.channel, user=conv.user, step=STEP_SOURCE)
            self._persist(fresh)
            return Turn(messages=["Baştan başlıyoruz.", self._render(self._prompt(fresh))])

        if selection.value != "onay" and word not in _CONFIRM_WORDS:
            prompt = self._prompt(conv)
            prompt.clarification = "Onaylamak için `onay` yazın."
            return Turn(messages=[self._render(prompt)])

        spec = conv.spec.copy()
        self.store.drop_session(conv.channel, conv.user)
        self.store.remember_spec(conv.user, spec.as_dict())
        if spec.source_kind != SOURCE_PASTE and spec.source:
            self.store.remember_source(
                conv.user,
                {"kind": spec.source_kind, "id": spec.source, "label": spec.source_label},
            )
        self.store.save()
        return Turn(
            messages=["Onaylandı. Raporu hazırlıyorum, birkaç dakika sürebilir."],
            spec=spec,
            ended=True,
        )

    # --- akış ---------------------------------------------------------------

    def _enter(self, conv: Conversation, step: str, from_step: str) -> Turn:
        """Bir ara adıma girer ve dönüş yolunu yığına koyar."""
        conv.stack.append(from_step)
        conv.step = step
        self._persist(conv)
        return Turn(messages=[self._render(self._prompt(conv))])

    def _next_step(self, conv: Conversation) -> str:
        """Cevaplanmamış ilk ana adım; hepsi cevaplandıysa onay."""
        for step in MAIN_STEPS:
            if step == STEP_CONFIRM:
                break
            if not conv.answered(step):
                return step
        return STEP_CONFIRM

    def _advance(self, conv: Conversation) -> List[str]:
        """Cevaplanmamış İLK adıma geçer ve o adımın menüsünü döner.

        "Sadece gerçekten eksik olanı sor" kuralı burada uygulanır: hızlı yoldan
        gelen bir cümle üç adımı doldurduysa akış o üçünü atlar.
        """
        origin = conv.step
        messages: List[str] = []
        # Döngü, veri okuma adımın cevabını değiştirebildiği için var: veriye
        # bağlanan bir cümle kırılımı da metriği de doldurabilir ve akış o
        # zaman iki adım birden atlar. Tur sayısı sınırlı, sonsuz döngü yok.
        for _ in range(len(MAIN_STEPS) + 1):
            target = self._next_step(conv)
            if target in (STEP_DIMENSIONS, STEP_METRICS) and not conv.data_ready:
                messages.extend(self._after_source(conv, advance=False))
                if conv.step == STEP_SOURCE:
                    # Veri okunamadı; akış kaynak adımına geri düştü.
                    return [*messages, self._render(self._prompt(conv))]
                continue
            if origin != target:
                conv.stack.append(origin)
            conv.step = target
            messages.append(self._render(self._prompt(conv)))
            return messages
        conv.step = STEP_CONFIRM  # pragma: no cover - ulaşılmaması gereken hâl
        messages.append(self._render(self._prompt(conv)))
        return messages

    def _after_source(self, conv: Conversation, advance: bool = True) -> List[str]:
        """Kaynak seçildi: veriyi oku, seçenekleri türet, cümleyi veriye bağla."""
        messages: List[str] = []
        try:
            dataset = self.loader(conv.spec)
        except DatasetError as exc:
            conv.step = STEP_SOURCE
            self._clear(conv, STEP_SOURCE)
            self._persist(conv)
            return [
                f"Veri okunamadı: {exc}",
                "Başka bir kaynak seçelim.",
            ]
        except Exception as exc:
            logger.warning("veri okunamadı: %s", exc)
            conv.step = STEP_SOURCE
            self._clear(conv, STEP_SOURCE)
            self._persist(conv)
            return [
                f"Veri okunamadı ({type(exc).__name__}): {exc}",
                "Başka bir kaynak seçelim.",
            ]

        conv.dimension_options = options_as_dicts(dimension_options(dataset))
        conv.metric_options = options_as_dicts(metric_options(dataset))
        conv.data_ready = True
        if not conv.spec.source_label:
            conv.spec.source_label = dataset.name
        messages.append(
            f"*{dataset.name}* okundu: {dataset.row_count} satır, "
            f"{dataset.column_count} sütun."
        )

        if conv.intent_text and not conv.intent_grounded:
            parsed = intent_mod.ground(intent_mod.parse(conv.intent_text), dataset)
            if parsed.spec.dimensions:
                conv.spec.dimensions = parsed.spec.dimensions
                conv.mark(STEP_DIMENSIONS)
            if parsed.spec.metrics:
                conv.spec.metrics = parsed.spec.metrics
                conv.mark(STEP_METRICS)
            conv.intent_grounded = True
            note = intent_mod.unknown_note(parsed, dataset)
            if note:
                messages.append(note)
            if parsed.spec.dimensions or parsed.spec.metrics:
                messages.append(parsed.understood_text())

        if advance:
            messages.extend(self._advance(conv))
        return [m for m in messages if m]

    # --- menüler ------------------------------------------------------------

    def _prompt(self, conv: Conversation) -> Prompt:
        builder = {
            STEP_SOURCE: self._prompt_source,
            STEP_PASTE: self._prompt_paste,
            STEP_PERIOD: self._prompt_period,
            STEP_RANGE: self._prompt_range,
            STEP_DIMENSIONS: self._prompt_dimensions,
            STEP_METRICS: self._prompt_metrics,
            STEP_CHART: self._prompt_chart,
            STEP_FORMAT: self._prompt_format,
            STEP_CONFIRM: self._prompt_confirm,
        }.get(conv.step, self._prompt_source)
        return builder(conv)

    def _heading(self, step: str) -> str:
        try:
            index = MAIN_STEPS.index(step) + 1
        except ValueError:
            return STEP_HEADINGS.get(step, step)
        return f"{index}/{len(MAIN_STEPS)} · {STEP_HEADINGS[step]}"

    def _prompt_source(self, conv: Conversation) -> Prompt:
        options: List[Option] = []
        if not conv.source_options:
            conv.source_options = self._drive_options(conv)
        for item in conv.source_options:
            options.append(
                Option(
                    value=str(item.get("value") or ""),
                    label=str(item.get("label") or ""),
                    hint=str(item.get("hint") or ""),
                )
            )
        options.append(
            Option(SOURCE_PASTE_VALUE, "Veriyi buraya yapıştıracağım", "tablo metni")
        )
        remembered = self.store.last_source(conv.user)
        if remembered.get("id"):
            options.append(
                Option(
                    SOURCE_LAST_VALUE,
                    f"Son kullandığım kaynak — {remembered.get('label') or remembered['id']}",
                )
            )
        note = (
            "Drive'daki tablolar listelenemedi; veriyi yapıştırabilir ya da "
            "e-tablo bağlantısını gönderebilirsiniz."
            if not conv.source_options
            else "Google E-Tablo bağlantısını doğrudan da yapıştırabilirsiniz."
        )
        return Prompt(
            step=STEP_SOURCE,
            title=self._heading(STEP_SOURCE),
            options=options,
            note=note,
            free_text=True,
        )

    def _drive_options(self, conv: Conversation) -> List[Dict[str, str]]:
        try:
            found = self.source_lister()
        except Exception as exc:  # pragma: no cover - lister zaten yutuyor
            logger.warning("kaynak listesi alınamadı: %s", exc)
            return []
        return [
            {
                "value": f"drive:{item.id}",
                "label": item.name,
                "hint": item.hint(),
                "mime": item.mime_type,
            }
            for item in found or []
            if getattr(item, "id", "")
        ]

    def _prompt_paste(self, conv: Conversation) -> Prompt:
        return Prompt(
            step=STEP_PASTE,
            title="Veriyi yapıştırın",
            note=(
                "Tabloyu BAŞLIK SATIRIYLA birlikte yapıştırın. Excel'den kopyala-"
                "yapıştır çalışır; sütunlar sekme ya da virgülle ayrılabilir."
            ),
            free_text=True,
        )

    def _prompt_period(self, conv: Conversation) -> Prompt:
        return Prompt(
            step=STEP_PERIOD,
            title=self._heading(STEP_PERIOD),
            options=[
                Option(PERIOD_TODAY, "Bugün"),
                Option(PERIOD_WEEK, "Bu hafta"),
                Option(PERIOD_MONTH, "Bu ay"),
                Option(PERIOD_QUARTER, "Son 3 ay"),
                Option(PERIOD_CUSTOM, "Özel tarih aralığı"),
            ],
        )

    def _prompt_range(self, conv: Conversation) -> Prompt:
        return Prompt(
            step=STEP_RANGE,
            title="Tarih aralığı",
            note="İki tarihi yazın: `01.07.2026 - 31.07.2026`",
            free_text=True,
        )

    def _prompt_dimensions(self, conv: Conversation) -> Prompt:
        options = options_from_dicts(conv.dimension_options)
        options.append(Option(AUTO, "Kırılım olmasın / motor seçsin"))
        note = (
            "Bu veride kırılıma uygun sütun bulunamadı; motor kendi seçimini yapabilir."
            if len(options) == 1
            else "Verideki sütunlardan seçildi. Birden fazla seçebilirsiniz."
        )
        return Prompt(
            step=STEP_DIMENSIONS,
            title=self._heading(STEP_DIMENSIONS),
            options=options,
            multi=True,
            note=note,
        )

    def _prompt_metrics(self, conv: Conversation) -> Prompt:
        options = options_from_dicts(conv.metric_options)
        options.append(Option(AUTO, "Motor önemli metrikleri kendisi seçsin"))
        note = (
            "Bu veride sayısal sütun bulunamadı; yalnızca dağılım tabloları üretilebilir."
            if len(options) == 1
            else "Verideki sayısal sütunlardan seçildi. Birden fazla seçebilirsiniz."
        )
        return Prompt(
            step=STEP_METRICS,
            title=self._heading(STEP_METRICS),
            options=options,
            multi=True,
            note=note,
        )

    def _prompt_chart(self, conv: Conversation) -> Prompt:
        return Prompt(
            step=STEP_CHART,
            title=self._heading(STEP_CHART),
            options=[
                Option(CHART_LINE, "Trend çizgisi", "zaman içindeki seyir"),
                Option(CHART_BAR, "Karşılaştırma çubuğu", "kırılımlar arası fark"),
                Option(CHART_DONUT, "Dağılım halkası", "payların ağırlığı"),
                Option(CHART_HEATMAP, "Yoğunluk haritası", "iki eksende yoğunlaşma"),
                Option(CHART_TABLE, "Sadece tablo", "zaman serisi grafiği olmadan"),
            ],
        )

    def _prompt_format(self, conv: Conversation) -> Prompt:
        return Prompt(
            step=STEP_FORMAT,
            title=self._heading(STEP_FORMAT),
            options=[
                Option(FORMAT_WEB, "Tarayıcı raporu", "panoda açılan bağlantı"),
                Option(FORMAT_XLSX, "Excel (.xlsx)", "kanala dosya olarak"),
                Option("both", "İkisi birden"),
            ],
        )

    def _prompt_confirm(self, conv: Conversation) -> Prompt:
        summary = "\n".join(conv.spec.summary_lines())
        return Prompt(
            step=STEP_CONFIRM,
            title=self._heading(STEP_CONFIRM),
            note=summary + "\n\nOnaylamak için `onay` yazın.",
            options=[
                Option("onay", "Onayla ve raporu üret"),
                Option("restart", "Baştan başla"),
            ],
            # Serbest metin açık: "evet"/"tamam" da onaydır ve "<ad> olarak
            # kaydet" burada çalışır. Tanınmayan girdiyi adım kendisi reddeder.
            free_text=True,
        )

    # --- yardımcılar --------------------------------------------------------

    def _render(self, prompt: Prompt) -> str:
        payload = self.renderer.render(prompt)
        return str(payload.get("text") or "")

    def _persist(self, conv: Conversation) -> None:
        """Konuşmayı diske yazar. HER adımdan sonra, istisnasız."""
        conv.updated_at = _now_iso(self._now)
        self.store.put_session(conv.channel, conv.user, conv.as_dict())
        self.store.save()

    def _help_text(self) -> str:
        return (
            "*Rapor asistanı*\n"
            "• `rapor` — yedi adımlık siparişi başlatır.\n"
            "• Tek cümle de olur: _“son 3 ay vardiya bazında SLA, haftalık trend, Excel”_.\n"
            "• `şablonlar` — kayıtlı tarifler · `<ad> çalıştır` — birini çalıştırır.\n"
            "• Her adımda `geri`, `baştan`, `iptal`."
        )


def parse_date_range(text: str) -> "tuple[Optional[datetime], Optional[datetime]]":
    """``01.07.2026 - 31.07.2026`` ya da ``2026-07-01 2026-07-31`` çözer."""
    found: List[datetime] = []
    for match in _DATE_RE.finditer(str(text or "")):
        if match.group(1):
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if year < 100:
                year += 2000
        else:
            year, month, day = int(match.group(4)), int(match.group(5)), int(match.group(6))
        try:
            found.append(datetime(year, month, day))
        except ValueError:
            continue
    if len(found) < 2:
        return (found[0] if found else None), None
    return found[0], found[1]


__all__ = [
    "AUTO",
    "Conversation",
    "MAIN_STEPS",
    "STEP_CHART",
    "STEP_CONFIRM",
    "STEP_DIMENSIONS",
    "STEP_FORMAT",
    "STEP_METRICS",
    "STEP_PASTE",
    "STEP_PERIOD",
    "STEP_RANGE",
    "STEP_SOURCE",
    "SOURCE_LAST_VALUE",
    "SOURCE_PASTE_VALUE",
    "SessionEngine",
    "Turn",
    "default_loader",
    "parse_date_range",
]
