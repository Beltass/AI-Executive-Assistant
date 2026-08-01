"""Teknik Gözetim (7/24 SRE) — nöbetçinin günlük brifingteki yüzü.

:mod:`ai_assistant.watchdog` zaten var ve kendi başına çalışıyor: koşunun
bıraktığı artefaktları (``status.json``, ``metrics.json``, rapor arşivi, durum
dosyası) okur, on teknik kontrol çalıştırır ve ``frontend/health.json``a bir
hüküm yazar. Ama o hükmü yalnızca PANO ve — durum değiştiğinde — ayrı bir Slack
uyarısı görüyordu; günlük brifingi okuyan kişi sistemin kendi sağlığını hiç
görmüyordu. Bu danışman o boşluğu kapatır.

İNCE SARMALAYICI
----------------
Burada tek bir kontrol yeniden yazılmaz. Modül nöbetçinin kendi
:func:`~ai_assistant.watchdog.run_checks` çağrısını yapar ve çıkan bulguları
brifing metnine çevirir. Dosya YAZMAZ ve Slack uyarısı GÖNDERMEZ — onlar
``python -m ai_assistant.watchdog`` komutunun işidir; brifing yolunun yan
etkisi olmaması, aynı hükmün iki kez duyurulmasını da engeller.

LLM ÇAĞIRMAZ: girdisi dosyalardır, çıktısı deterministiktir. Bu yüzden toplu
çağrıya (``advisors._batch``) katılmaz ve ücretsiz kotadan hiçbir şey yemez.

WORK_ANALYST'TAN FARKI
----------------------
``work_analyst`` BU koşuya bakar: hangi danışman çalıştı, hangisi hata verdi,
başarı oranı ne. ``sre_watchdog``ın öznesi MAKİNEDİR ve ufku koşulardan
uzundur: cron hâlâ tetikleniyor mu, kota tükendi mi, brifing Slack'e ulaştı
mı, beslemeler ayakta mı, durum dosyası geri commit edildi mi. Biri koşunun
içine, öteki koşuların arasına bakar.

Sıralama: en sonda kayıtlıdır — Operasyon Direktörü'nden de sonra. Direktör
karar listesini yazarken sistemin iç ayrıntılarını bilerek dışarıda bırakır
(bkz. ``operations_director.SYSTEM_HEALTH_KEYS``), bu yüzden bu bölüm koşuyu
kapatan teknik kapanış notudur.

TEMİZ DEVREDİLME: hiç artefakt yoksa ``skipped`` + Türkçe açıklama; kontroller
patlarsa nöbetçi zaten her kontrolü tek tek koruma altına alır. Bu bölüm
brifingi asla düşürmez.

GİZLİLİK: dosya yolları, ölçüm sayıları ve hata nedenleri gibi SİSTEM iç
bilgisi taşır, bu yüzden ``private = True`` — panoya yazılmaz, yalnızca
Slack'te durur.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence, Tuple

from . import Advisor, Briefing
from .. import watchdog

logger = logging.getLogger(__name__)

#: Brifinge yazılacak en fazla bulgu. Nöbetçi on kontrol çalıştırır; hepsini
#: tek tek listelemek bölümü rapordan çok günlüğe çevirir, kalanı panoda durur.
MAX_FINDINGS = 5

#: Okunacak artefakt yokken verilen Türkçe açıklama.
NO_ARTEFACT_HELP = (
    "izlenecek çalıştırma artefaktı yok: ne durum dosyası (status.json) ne de "
    "ölçüm geçmişi (metrics.json) okunabildi. Bu dosyaları ilk tam brifing "
    "yazar; bir sonraki koşuda bu bölüm dolar."
)

#: Artefakt var ama hiçbir kontrol sonuç üretemediğinde.
NO_CHECK_HELP = (
    "teknik kontrollerin hiçbiri sonuç üretemedi; bu koşuda raporlanacak bir "
    "sistem bulgusu yok."
)

CLOSING_NOTE = (
    "🔒 Not: Bu bölüm SİSTEMİN kendi teknik sağlığını izler — çalıştırma "
    "tazeliği, model kotası, Slack teslimi, besleme erişimi ve durum kaydı. "
    "Bu koşudaki danışman performansı İş Analisti bölümündedir. Sistemin iç "
    "ayrıntılarını taşıdığı için panoya yazılmaz."
)


def load_artefacts() -> Tuple[Dict[str, Any], List[dict]]:
    """Nöbetçinin okuduğu artefaktlar: durum dosyası ve ölçüm geçmişi.

    Nöbetçinin komut satırıyla AYNI kaynakları okur; okunamayan bir dosya
    hüküm değil, boş girdidir.
    """
    try:
        status, runs = watchdog._load_inputs()
    except Exception as exc:  # pragma: no cover - savunma amaçlı
        logger.warning("nöbetçi artefaktları okunamadı: %s", exc)
        return {}, []
    return dict(status or {}), list(runs or [])


def format_briefing(checks: Sequence[watchdog.Check]) -> str:
    """Bulguları brifing metnine çevirir: hüküm, bulgular, kontrol özeti."""
    severity = watchdog.overall_severity(checks)
    icon = watchdog.SEVERITY_ICON.get(severity, "")
    label = watchdog.SEVERITY_LABEL.get(severity, severity)

    lines = [
        f"**Öne çıkan:** {icon} Sistem durumu: {label} — "
        f"{watchdog.headline(checks)}",
        "",
    ]

    problems = [c.to_dict() for c in checks if c.severity != watchdog.SEVERITY_OK]
    if problems:
        lines.append("**🚨 Bulgular ve ne yapılacağı:**")
        for check in problems[:MAX_FINDINGS]:
            lines.append(
                f"- {watchdog.SEVERITY_ICON.get(check['severity'], '')} "
                f"**{check['name']}** — {check['detail']}"
            )
            if check["remedy"]:
                lines.append(f"  🔧 {check['remedy']}")
        if len(problems) > MAX_FINDINGS:
            lines.append(
                f"- … ve {len(problems) - MAX_FINDINGS} bulgu daha — "
                "ayrıntılar panoda."
            )
    else:
        lines.append(
            "Tüm teknik kontroller temiz; sistem tarafında bugün yapılacak bir "
            "şey yok."
        )
    lines.append("")

    lines.append(
        "**📊 Kontrol özeti:** "
        f"{sum(1 for c in checks if c.severity == watchdog.SEVERITY_OK)} temiz · "
        f"{sum(1 for c in checks if c.severity == watchdog.SEVERITY_WARN)} uyarı · "
        f"{sum(1 for c in checks if c.severity == watchdog.SEVERITY_CRITICAL)} "
        f"kritik (toplam {len(checks)} kontrol)."
    )
    lines.append("")
    lines.append(CLOSING_NOTE)
    return "\n".join(lines)


class SreWatchdogAdvisor(Advisor):
    """7/24 teknik nöbetçinin bulgularını günlük brifinge taşır."""

    key = "sre_watchdog"
    title = "Teknik Gözetim (7/24 SRE)"
    #: Sistemin iç durumunu raporlar; pano herkese açıktır.
    private = True
    incremental_source = False

    def _generate(self) -> Briefing:
        status, runs = load_artefacts()
        if not status and not runs:
            return self.skipped(NO_ARTEFACT_HELP)

        checks = watchdog.run_checks(status=status, runs=runs)
        if not checks:
            return self.skipped(NO_CHECK_HELP)
        return self.ok(format_briefing(checks))


__all__ = [
    "CLOSING_NOTE",
    "MAX_FINDINGS",
    "NO_ARTEFACT_HELP",
    "NO_CHECK_HELP",
    "SreWatchdogAdvisor",
    "format_briefing",
    "load_artefacts",
]
