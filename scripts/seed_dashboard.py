"""Seed the dashboard with a realistic sample run — OFFLINE, no API keys.

The dashboard is a static site: with no data files next to it, a visitor gets
"henüz veri yok" and cannot tell a working deploy from a broken one. This script
writes ONE representative run — per-advisor report documents plus a status file
— so the reading view, the archive and the monitor all have something true to
render the moment the site is published.

It calls no network and no model. The section bodies below are written by hand
as EXAMPLES of the shape the advisors produce (they open with the
``**Öne çıkan:**`` line the Slack index extracts), and they are marked as such
on the page so nobody mistakes them for a real briefing.

Run with::

    python scripts/seed_dashboard.py            # only the report documents
    python scripts/seed_dashboard.py --status   # ALSO overwrite status.json

``status.json`` is left alone by default on purpose: it already carries the real
last run and its history, and replacing that with a sample would make the
monitor LESS true, which is the opposite of the point.

The next real briefing overwrites everything it touches.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_assistant import reports  # noqa: E402
from ai_assistant.advisors import Briefing  # noqa: E402
from ai_assistant.integrations import CheckResult, STATUS_OK, STATUS_SKIPPED  # noqa: E402
from ai_assistant.operations_manager import Supervision  # noqa: E402
from ai_assistant.status_report import ISTANBUL, write_status_report  # noqa: E402

NOTE = (
    "\n\n---\n\n_Bu, panonun ilk yayınında görünsün diye hazırlanmış **örnek** "
    "bir bölümdür. İlk gerçek brifing çalıştığında yerini alır._"
)


def _section(headline: str, body: str) -> str:
    return f"**Öne çıkan:** {headline}\n\n{body.strip()}{NOTE}"


SAMPLES = [
    (
        "leadership_coach",
        "Liderlik Koçu",
        "Ekibinin haftalık ritmini 20 dakikalık tek bir kontrol toplantısıyla sabitle.",
        """
## Merak uyandıran giriş

Bir ekipte "acil" kelimesi haftada kaç kez geçiyorsa, takvimde o kadar boşluk
vardır. Sabit ritmi olmayan ekipler, planlamadıkları her şeyi eskalasyon
yoluyla halleder.

## Derinlemesine

### 1. Haftalık ritim (Cadence)

Andy Grove'un *High Output Management* kitabındaki "bir yöneticinin çıktısı,
etkilediği ekiplerin çıktısıdır" ilkesi burada işler: 20 dakikalık sabit bir
kontrol toplantısı, haftanın geri kalanındaki 5-6 kesintiyi ortadan kaldırır.

- **Ne zaman:** Pazartesi 09:40, her hafta aynı saat.
- **Gündem:** 3 sabit soru — neyi bitirdik, neye takıldık, bu hafta neye
  odaklanıyoruz.
- **Süre:** 20 dakika, uzatma yok.

### 2. Yaygın hata

Toplantıyı "durum raporu" hâline getirmek. Rapor yazıyla verilir; toplantı
yalnızca *takılan* konular içindir.

## Neden işe yarar

Öngörülebilirlik, bilişsel yükü azaltır: ekip bir sonraki karar noktasının ne
zaman olduğunu bildiğinde araya girme ihtiyacı düşer.

## 📚 Kaynaklar

- [Coursera](https://www.coursera.org) — "Leading People and Teams" programı;
  ritim ve geri bildirim modülleri için.
- Kitap: *High Output Management* — Andrew S. Grove.

🔎 Bağlantıları açılışta doğrulayın.

## ✅ Bugünün görevi

Takvime önümüzdeki 4 hafta için tekrarlayan 20 dakikalık kontrol toplantısı koy
ve davete yukarıdaki 3 soruyu gündem olarak yaz. Başarı ölçütü: dördü de
takvimde ve gündem alanı dolu.
""",
    ),
    (
        "ai_mastery",
        "Yapay Zeka Ustalığı Koçu",
        "Bugün 25 dakikada tek bir beceri: bir isteme (prompt) rol, bağlam ve çıktı biçimi eklemek.",
        """
## Bugünün becerisi: üç parçalı isteme

Çoğu zayıf yanıtın sebebi model değil, istemedeki eksik bağlamdır. Bir istemeyi
üç parçaya böl:

1. **Rol** — "Bir banka çağrı merkezi operasyon müdürü gibi düşün."
2. **Bağlam** — elindeki gerçek veriyi ve kısıtı yaz.
3. **Çıktı biçimi** — "5 maddelik liste, her madde en fazla 2 cümle."

### Karşılaştırma

- Zayıf: "Çağrı merkezi verimliliği hakkında yaz."
- Güçlü: "Rol: 200 kişilik bir banka çağrı merkezinin operasyon müdürüsün.
  Bağlam: ortalama görüşme süresi 4 dk 20 sn, terk oranı %9. Görev: terk oranını
  2 puan düşürmek için 5 somut aksiyon öner; her aksiyonun ölçüsünü de yaz."

## Neden işe yarar

Model, belirsizliği kendi varsayımlarıyla doldurur. Üç parça, o boşluğu
kapatarak varsayım sayısını azaltır.

## 📚 Kaynaklar

- [Google AI](https://ai.google.dev) — resmi isteme rehberi.
- [edX](https://www.edx.org) — ücretsiz yapay zeka temelleri dersleri.

🔎 Bağlantıları açılışta doğrulayın.

## ✅ Bugünün görevi

Dün sorduğun bir soruyu al ve üç parçalı biçimde yeniden yaz; iki yanıtı yan
yana koy. Başarı ölçütü: yeni yanıtta senin eklemen gereken bilgi sayısı azaldı.
""",
    ),
    (
        "cx_research",
        "Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı",
        "İlk temasta çözüm (FCR) ölçülürken 'çözüldü' tanımını müşteriye sormayan her ölçüm yanıltıcıdır.",
        """
## Bulgu

FCR (First Contact Resolution) çoğu operasyonda temsilcinin kapanış kodundan
üretilir. Aynı müşteri 48 saat içinde tekrar aradığında bu ilk kayıt "çözüldü"
olarak kalır, dolayısıyla ölçüm gerçeğin üzerinde çıkar.

### Daha sağlam ölçüm

- **Tekrar arama penceresi:** ilk temastan sonraki 7 gün içindeki aynı konulu
  temasları say.
- **Müşteri onayı:** kapanışta tek soruluk anket — "sorununuz bu görüşmede
  çözüldü mü?"
- **İki ölçümün farkı:** aradaki açık, kapanış kodlarının ne kadar iyimser
  olduğunu gösterir.

## Ne yapmalı

Önce ölçümü düzelt, sonra hedef koy. Yanlış ölçülen bir FCR hedefi, temsilciyi
konuyu kapatmaya değil, kapanış kodunu "çözüldü" seçmeye teşvik eder.

## 📚 Kaynaklar

- [Nielsen Norman Group](https://www.nngroup.com) — müşteri deneyimi ölçümü.

🔎 Bağlantıları açılışta doğrulayın.

## ✅ Bugünün görevi

Son 7 günün tekrar arama oranını çıkar ve kapanış kodundan hesaplanan FCR ile
karşılaştır. Başarı ölçütü: iki sayı da tek bir slaytta yan yana.
""",
    ),
]


def main() -> int:
    now = datetime.now(ISTANBUL)
    briefings = [
        Briefing(key=key, title=title, status=STATUS_OK, text=_section(headline, body))
        for key, title, headline, body in SAMPLES
    ]
    # The private advisor is present in the run and absent from the files — the
    # seeded data demonstrates the privacy rule instead of just describing it.
    briefings.append(
        Briefing(
            key="daily_ops_briefing",
            title="Gün Başı Operasyon Brifingi",
            status=STATUS_SKIPPED,
            text="no Google credentials/token configured",
            private=True,
        )
    )
    supervision = Supervision(briefings=briefings, mode="full")

    publication = reports.publish(
        supervision, root=str(ROOT / "frontend" / "reports"), now=now
    )
    print(f"{len(publication.reports)} örnek rapor yazıldı → {publication.directory}")

    if "--status" in sys.argv[1:]:
        path = write_status_report(
            supervision,
            slack_result=CheckResult(
                name="Slack Notifier", status=STATUS_SKIPPED, detail="örnek veri"
            ),
            duration_seconds=41.2,
            path=str(ROOT / "frontend" / "status.json"),
            now=now,
        )
        print(f"Durum dosyası: {path}")
    else:
        print("status.json korundu (üzerine yazmak için: --status)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
