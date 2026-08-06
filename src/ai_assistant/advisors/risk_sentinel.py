"""Risk Nöbetçisi — TREND hâlinde kötüleşen sinyaller ve eşik aşımları.

Kadroda iki komşu var ve bu bölüm ikisinin de yaptığını yapmaz:

* ``sre_watchdog`` ANLIK teknik kontrol yapar: "şu an çalıştırma taze mi, kota
  doldu mu, Slack teslim etti mi". Cevabı bugünün fotoğrafıdır.
* ``operations_director`` BUGÜNÜN kararlarını çıkarır: "bugün ne yapılmalı".

Bu bölüm ise ZAMANA bakar. Tek bir koşuya değil, kayıtlı koşuların DİZİSİNE:
bir sayı üç koşudur sessizce mi kötüleşiyor, bir oran eşiği aştı mı? Bugün
"kırmızı" olmayan ama gidişatı kırmızıya bakan şeyleri, henüz ucuzken söyler.
Tek bir kötü koşu haberdir; üst üste kötüleşen üç koşu TRENDDİR — ayırt eden
şey budur.

NE YAPAR
--------
1. :func:`ai_assistant.metrics.load_history` ile kayıtlı koşu geçmişini okur
   (yeni bir istemci ya da yeni bir dosya YOKTUR — nöbetçinin okuduğu aynı
   ``metrics.json``).
2. Geçmişi ikiye böler (önceki pencere / son pencere) ve izlenen her seri için
   iki pencerenin ortalamasını karşılaştırır. Kötüye gidiş
   :data:`WORSENING_RATIO` eşiğini aşarsa bir SİNYAL üretir.
3. Mutlak eşikleri kontrol eder: başarısız danışman sayısı ve —
   yapılandırıldıysa — koşu başına token tavanı.
4. Sinyalleri ve HAM sayıları modele verir; model yalnızca bu sayıları yorumlar.

TETİKLEYİCİ: ``data_triggered``. Manifestteki ``data_owner`` alanı
``run_history``; geçmiş değişmediyse (yeni koşu kaydı yok) istem de değişmez,
:meth:`~ai_assistant.operations_manager.OperationsManager._data_gate` bölümü
atlar ve model hiç çağrılmaz.

TEMİZ DEVREDİLME: geçmiş yoksa, karşılaştırma için yeterli koşu yoksa
(:data:`MIN_RUNS`), kötüleşen bir sinyal yoksa ya da model anahtarı yoksa
Türkçe bir açıklamayla ``skipped`` döner. Model anahtarı yokken ASLA uydurma
bir risk analizi üretmez.

GİZLİLİK: sistemin iç ölçümlerini taşır, pano herkese açıktır — ``private``.

Configuration (via environment):
    RISK_SENTINEL_WINDOW        Karşılaştırılan pencere büyüklüğü (varsayılan
                                :data:`DEFAULT_WINDOW` koşu, her pencere için).
    RISK_SENTINEL_TOKEN_LIMIT   Koşu başına token tavanı; 0/tanımsız = kapalı.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import Advisor, BatchSection, Briefing
from ..integrations import llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

WINDOW_ENV = "RISK_SENTINEL_WINDOW"
TOKEN_LIMIT_ENV = "RISK_SENTINEL_TOKEN_LIMIT"

#: Her pencerede kaç koşu ortalanır. Üç, tek bir kötü günün trend gibi
#: görünmesini engelleyecek kadar geniş; haftalar sürmeyecek kadar dar.
DEFAULT_WINDOW = 3

#: Karşılaştırma yapılabilmesi için gereken en az koşu sayısı — iki pencere.
MIN_RUNS = 2 * DEFAULT_WINDOW

#: Bir seri "kötüleşiyor" sayılmadan önce gereken göreli bozulma (%25).
#: Daha düşük bir eşik, gürültüyü uyarıya çevirirdi.
WORSENING_RATIO = 0.25

#: Modele taşınacak en fazla sinyal. Sıralama zaten en kötüden başlar.
MAX_SIGNALS = 6

SKIP_NO_HISTORY = (
    "koşu geçmişi yok: metrics.json henüz yazılmamış. Risk nöbetçisi tek bir "
    "koşudan trend çıkaramaz; ilk koşular biriktikçe bu bölüm dolar."
)

SKIP_TOO_SHORT = (
    "trend için yeterli koşu yok: karşılaştırma en az {needed} kayıtlı koşu "
    "ister, geçmişte {have} var. Bölüm sessiz kalıyor — az veriden çıkarılan "
    "bir 'trend' uydurmadan başka bir şey olmaz."
)

SKIP_NO_SIGNAL = (
    "erken uyarı sinyali yok: izlenen serilerin hiçbiri son {window} koşuda "
    "anlamlı biçimde kötüleşmedi ve tanımlı bir eşik aşılmadı. Söylenecek bir "
    "şey olmadığı için model çağrılmadı."
)

SKIP_NO_LLM = "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"

SYSTEM_PROMPT = (
    "Sen bir üst düzey yöneticinin risk nöbetçisisin. Türkçe yazıyorsun. "
    "İşin DAR ve nettir: sana verilen ZAMAN SERİSİ ölçümlerinde kötüye gidişi "
    "okumak ve daha ucuzken müdahale ettirmek.\n\n"
    "KAPSAMIN NE DEĞİL: 'şu an sistem ayakta mı' kontrolü başka bir "
    "danışmanın işi; 'bugün hangi kararı vereyim' listesi de öyle. Sen "
    "bugünün fotoğrafını değil, ÜÇ KOŞUDUR SÜREN yönü anlatırsın. Bir madde "
    "yazarken sor: bunu tek bir koşuya bakarak da söyleyebilir miydim? Cevap "
    "evetse o madde senin değil.\n\n"
    "SESİN: sakin, abartısız, sayıya bağlı. Alarm dili kullanma; 'felaket' "
    "değil 'şu hızla şu tarihte şu eşiğe çarpar' de.\n\n"
    "MUTLAK KURAL — UYDURMA YOK: yalnızca sana verilen serileri ve sayıları "
    "kullan. Verilmemiş bir metrik, bir kullanıcı, bir olay ya da bir kök "
    "neden ICAT ETME. Kök neden bilinmiyorsa 'olası nedenler' diye AYRIK "
    "olarak yaz ve hangisinin doğru olduğunu nasıl anlayacağını söyle. "
    "Geleceğe dair her sayı bir TAHMİNDİR; öyle işaretle."
)

CAVEAT = (
    "📌 Risk notu: Buradaki sinyaller yalnızca kayıtlı koşu ölçümlerinden "
    "çıkarılmış EĞİLİMLERDİR; bir kök neden teşhisi değildir.\n"
    "📉 Kısa pencerelerde ölçüm gürültüsü trend gibi görünebilir; müdahale "
    "etmeden önce bir sonraki koşuyu da bekleyin.\n"
    "🔒 Not: Bu bölüm sistemin iç ölçümlerini taşıdığı için panoya yazılmaz."
)


def _int_setting(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Series:
    """İzlenen tek bir ölçüm serisi.

    ``higher_is_worse`` serinin YÖNÜNÜ taşır: başarısız danışman sayısı
    büyüdükçe kötüleşir, başarılı danışman sayısı küçüldükçe. Yönü veride
    değil burada tutmak, "kötüleşme" tanımının tek bir yerde kalmasını sağlar.
    """

    field: str
    label: str
    unit: str = ""
    higher_is_worse: bool = True


#: İzlenen seriler. Hepsi koşu kaydında ZATEN var; bu bölüm yeni bir ölçüm
#: toplamaz, var olanı zaman içinde okur.
SERIES: Tuple[Series, ...] = (
    Series("advisors_failed", "Başarısız danışman sayısı", "danışman"),
    Series("advisors_ok", "Başarılı danışman sayısı", "danışman", False),
    Series("total_tokens", "Koşu başına token", "token"),
    Series("duration_seconds", "Koşu süresi", "sn"),
    Series("retries", "Model yeniden deneme sayısı", "deneme"),
)


@dataclass
class Signal:
    """Kötüye giden tek bir seri, ya da aşılmış tek bir eşik."""

    label: str
    older: float
    recent: float
    unit: str = ""
    #: Göreli bozulma (0.4 = %40 kötüleşme). Eşik aşımlarında 0 olabilir.
    drift: float = 0.0
    #: Mutlak eşik aşıldıysa açıklaması, yoksa boş dize.
    breach: str = ""

    @property
    def weight(self) -> float:
        """Sıralama ağırlığı: eşik aşımı her zaman trendin önüne geçer."""
        return self.drift + (10.0 if self.breach else 0.0)

    def describe(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        line = (
            f"- {self.label}: önceki pencere ortalaması "
            f"{_pretty(self.older)}{unit} → son pencere ortalaması "
            f"{_pretty(self.recent)}{unit}"
        )
        if self.drift:
            line += f" (%{round(self.drift * 100)} kötüleşme)"
        if self.breach:
            line += f" — EŞİK AŞIMI: {self.breach}"
        return line


def _pretty(value: float) -> str:
    """Tam sayıyı tam sayı, kesirliyi tek ondalıkla yazar."""
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def windows(runs: Sequence[dict], window: int) -> Tuple[List[dict], List[dict]]:
    """Geçmişi (önceki pencere, son pencere) olarak ikiye böler.

    Kayıtlar eskiden yeniye sıralıdır; son ``window`` koşu "şimdi", ondan
    önceki ``window`` koşu "önce" sayılır. Aradaki daha eski koşular
    karşılaştırmaya girmez: sorulan soru "geçen yıla göre" değil, "son
    birkaç koşudur ne oluyor".
    """
    recent = list(runs[-window:])
    older = list(runs[-2 * window : -window])
    return older, recent


def token_limit() -> int:
    """Koşu başına token tavanı; tanımsız/0 ise eşik kontrolü kapalıdır."""
    return _int_setting(TOKEN_LIMIT_ENV, 0)


def detect(runs: Sequence[dict], window: int) -> List[Signal]:
    """Kötüleşen serileri ve eşik aşımlarını bulur, en ağırdan sıralar."""
    older, recent = windows(runs, window)
    if not older or not recent:
        return []

    limit = token_limit()
    found: List[Signal] = []
    for series in SERIES:
        before = mean([_num(run.get(series.field)) for run in older])
        after = mean([_num(run.get(series.field)) for run in recent])

        # Bozulma her zaman "kötü yöne doğru ne kadar" olarak ölçülür, böylece
        # yönü ters olan seriler (başarılı sayısı) aynı eşikle karşılaştırılır.
        delta = (after - before) if series.higher_is_worse else (before - after)
        base = max(abs(before), 1.0)
        drift = delta / base

        breach = ""
        if series.field == "advisors_failed" and after >= 1:
            breach = (
                f"son {len(recent)} koşuda ortalama {_pretty(after)} danışman "
                "başarısız oluyor; hedef 0."
            )
        elif series.field == "total_tokens" and limit and after > limit:
            breach = (
                f"koşu başına token ortalaması {_pretty(after)}, tanımlı tavan "
                f"{limit}."
            )

        if drift < WORSENING_RATIO and not breach:
            continue
        found.append(
            Signal(
                label=series.label,
                older=before,
                recent=after,
                unit=series.unit,
                drift=max(drift, 0.0),
                breach=breach,
            )
        )

    found.sort(key=lambda signal: signal.weight, reverse=True)
    return found[:MAX_SIGNALS]


class RiskSentinelAdvisor(Advisor):
    """Koşu geçmişinde kötüye giden eğilimleri ve eşik aşımlarını raporlar."""

    key = "risk_sentinel"
    title = "Risk Nöbetçisi (Erken Uyarı · Eşik Aşımı)"
    #: Sistemin iç ölçümlerini taşır; pano herkese açıktır.
    private = True
    #: Yeni koşu kaydı = yeni sinyal olabilir.
    incremental_source = True

    def __init__(self) -> None:
        self._signals: List[Signal] = []
        self._runs: List[dict] = []
        self._skip_reason = ""
        self._gathered = False

    # -- the run ---------------------------------------------------------
    def _generate(self) -> Briefing:
        self._gather()
        if self._skip_reason:
            return self.skipped(self._skip_reason)

        if not llm.is_configured():
            # Sinyaller gerçek ama yorumu model yazar. Model yoksa yorumu
            # uydurmak yerine bölüm sessiz kalır.
            return self.skipped(SKIP_NO_LLM)

        try:
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
        return len(self._signals)

    # -- gathering -------------------------------------------------------
    def _gather(self) -> None:
        """Koşu geçmişini bir kez okur; sinyalleri ya da atlama nedenini tutar."""
        if self._gathered:
            return
        self._gathered = True

        window = _int_setting(WINDOW_ENV, DEFAULT_WINDOW)
        needed = max(2 * window, MIN_RUNS)
        try:
            runs = self._history()
        except Exception as exc:  # pragma: no cover - savunma amaçlı
            logger.warning("koşu geçmişi okunamadı: %s", exc)
            self._skip_reason = f"koşu geçmişi okunamadı: {exc}"
            return

        if not runs:
            self._skip_reason = SKIP_NO_HISTORY
            return
        if len(runs) < needed:
            self._skip_reason = SKIP_TOO_SHORT.format(needed=needed, have=len(runs))
            return

        self._runs = list(runs)
        self._signals = detect(runs, window)
        if not self._signals:
            self._skip_reason = SKIP_NO_SIGNAL.format(window=window)

    def _history(self) -> List[dict]:
        """Kayıtlı koşular (tembel içe aktarma: metrik katmanını erken çekme)."""
        from ..metrics import load_history

        return list(load_history() or [])

    # -- the prompt ------------------------------------------------------
    def _facts(self) -> str:
        window = _int_setting(WINDOW_ENV, DEFAULT_WINDOW)
        lines = [
            f"Kayıtlı koşu sayısı: {len(self._runs)}",
            f"Karşılaştırılan pencere: son {window} koşu ile ondan önceki "
            f"{window} koşu",
            "",
            "KÖTÜLEŞEN SERİLER (yalnızca bunları yorumla):",
        ]
        lines.extend(signal.describe() for signal in self._signals)
        limit = token_limit()
        if limit:
            lines.append(f"\nTanımlı token tavanı: koşu başına {limit}.")
        else:
            lines.append(
                "\nKoşu başına token tavanı TANIMLI DEĞİL; token için 'tavanı "
                "aştı' deme, yalnızca eğilimi anlat."
            )
        return "\n".join(lines)

    def _user_prompt(self) -> str:
        return (
            "Aşağıdaki ölçümler kayıtlı koşu geçmişinden çıkarıldı ve KÖTÜYE "
            "gidiyor. Bunları bir erken uyarı notuna çevir. Blokları bu "
            "sırayla ver:\n\n"
            "*🚨 Ne kötüleşiyor*: her sinyal için tek cümle — hangi seri, ne "
            "kadar, hangi yönde. Sayıları AYNEN kullan.\n\n"
            "*⏳ Bu hızla ne olur*: mevcut eğim sürerse ne zaman hangi eşiğe "
            "çarpılır? Bir tahmin ver ve 'tahmin' olduğunu açıkça yaz; "
            "hesabını tek satırda göster.\n\n"
            "*🔍 Olası nedenler*: her sinyal için en fazla 2 ayrık hipotez ve "
            "her birini DOĞRULAYACAK tek bir kontrol. Hangi hipotezin doğru "
            "olduğunu bilmiyorsan bilmediğini söyle.\n\n"
            "*🧯 Şimdi yapılırsa ucuz olan*: en fazla 3 önleyici adım, en "
            "yüksek etkiden başlayarak; her adımın maliyeti ve beklenen "
            "etkisi tek cümleyle.\n\n"
            "*📏 Neyi izlemeli*: bir sonraki koşuda hangi sayı hangi yöne "
            "giderse 'düzeldi' diyebiliriz? Tek bir ölçüt yaz.\n\n"
            "Anlık sistem sağlığı kontrolü ve günün karar listesi YAZMA — "
            "onlar başka danışmanların bölümünde.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nÖLÇÜMLER (yalnızca aşağıdakini kullan; eksik olanı "
            "uydurma):\n\n"
            + self._facts()
        )


__all__ = [
    "CAVEAT",
    "DEFAULT_WINDOW",
    "MAX_SIGNALS",
    "MIN_RUNS",
    "RiskSentinelAdvisor",
    "SERIES",
    "SKIP_NO_HISTORY",
    "SKIP_NO_LLM",
    "SKIP_NO_SIGNAL",
    "SKIP_TOO_SHORT",
    "SYSTEM_PROMPT",
    "Series",
    "Signal",
    "TOKEN_LIMIT_ENV",
    "WINDOW_ENV",
    "WORSENING_RATIO",
    "detect",
    "mean",
    "token_limit",
    "windows",
]
