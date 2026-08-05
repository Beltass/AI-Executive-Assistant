"""``frontend/advisors.json`` — panoya giden ajan listesi, manifestten türetilir.

Pano (``frontend/app.js``) uzun süre 16 ajanı elle listeledi; dosyanın kendi
yorumu "ADVISOR_META tek kaynak" derken listenin kopyası JavaScript'te
duruyordu. Buradaki üretici o kopyayı ortadan kaldırır: roster, sıra, başlık,
emoji, kategori, tetikleyici ve token tavanı
:data:`ai_assistant.status_report.ADVISOR_META` içinden okunur ve statik bir
JSON dosyasına yazılır. Pano bu dosyayı ``fetch`` ile alır; dosya yoksa
gömülü yedeğine düşer (defensive).

``topic`` ve ``color`` panonun kendi gruplandırması içindir; manifest bunları
tutmaz, bu yüzden eşleme burada — TEK yerde — yaşar.

Kullanım::

    python -m ai_assistant.frontend_manifest          # frontend/advisors.json
    python -m ai_assistant.frontend_manifest --check  # bayat mı, söyler
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from .status_report import ADVISOR_META, live_advisor_keys

__all__ = [
    "SCHEMA_VERSION",
    "TOPIC_COLORS",
    "build_manifest",
    "manifest_path",
    "write_manifest",
    "is_stale",
]

#: Panonun okuduğu şemanın sürümü. Alan eklemek sürümü değiştirmez; alan
#: silmek/anlamını değiştirmek değiştirir.
SCHEMA_VERSION = 1

#: Panonun konu (topic) kutuları ve renkleri — ``frontend/app.js``'teki
#: ``TOPICS`` ile aynı anahtarlar.
TOPIC_COLORS = {
    "business-analytics": "#4A90E2",
    "human-resources": "#7ED321",
    "marketing-sales": "#F5A623",
    "innovation-tech": "#9B59B6",
    "communications": "#E74C3C",
    "learning-development": "#1ABC9C",
    "personal-family": "#34495E",
}

#: Kategori kaba: 16 ajanın yarısı ``operasyon``. Varsayılan eşleme bu.
_CATEGORY_TOPIC = {
    "operasyon": "business-analytics",
    "sektör": "marketing-sales",
    "kariyer": "learning-development",
    "kişisel gelişim": "human-resources",
    "aile": "personal-family",
}

#: Kategorinin söyleyemediği yerler: takvim asistanı ile operasyon direktörü
#: aynı kategoride ama panoda aynı kutuda durmamalı.
_TOPIC_OVERRIDES = {
    "communications_calendar": "communications",
    "meeting_prep": "communications",
    "personal_assistant": "personal-family",
    "ai_innovation": "innovation-tech",
    "sre_watchdog": "innovation-tech",
}


def _topic(key: str, category: str) -> str:
    return _TOPIC_OVERRIDES.get(key) or _CATEGORY_TOPIC.get(
        category, "business-analytics"
    )


def build_manifest() -> Dict[str, Any]:
    """Canlı roster'ı panonun beklediği şekle çevirir (deterministik).

    Zaman damgası YOK: dosya üretildiği an değil, manifest değiştiği zaman
    değişsin ki "bayat mı" sorusu diff ile cevaplanabilsin.
    """
    advisors: List[Dict[str, Any]] = []
    for key in live_advisor_keys():
        meta = ADVISOR_META[key]
        topic = _topic(key, str(meta.get("category") or ""))
        advisors.append(
            {
                "id": key.replace("_", "-"),
                "advisor_id": key,
                "name_tr": meta.get("title", ""),
                "emoji": meta.get("emoji", ""),
                "category": meta.get("category", ""),
                "topic": topic,
                "color": TOPIC_COLORS.get(topic, "#4A90E2"),
                "dashboard_order": int(meta.get("dashboard_order") or 0),
                "trigger": meta.get("trigger", ""),
                "token_ceiling": int(meta.get("token_ceiling") or 0),
                "data_owner": meta.get("data_owner", ""),
                "slack_target": meta.get("slack_target", ""),
            }
        )
    advisors.sort(key=lambda row: (row["dashboard_order"], row["advisor_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "count": len(advisors),
        "advisors": advisors,
    }


def manifest_path(root: str = "") -> str:
    """``frontend/advisors.json``ın yolu."""
    base = root or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(base, "frontend", "advisors.json")


def write_manifest(path: str = "") -> str:
    """Dosyayı yazar, yazdığı yolu döndürür."""
    target = path or manifest_path()
    payload = json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(payload)
    return target


def is_stale(path: str = "") -> bool:
    """Diskteki dosya manifestle aynı mı? Farklıysa ``True``."""
    target = path or manifest_path()
    try:
        with open(target, "r", encoding="utf-8") as fh:
            on_disk = json.load(fh)
    except (OSError, ValueError):
        return True
    return on_disk != build_manifest()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="sadece kontrol et")
    parser.add_argument("--path", default="", help="hedef dosya")
    args = parser.parse_args(argv)

    target = args.path or manifest_path()
    if args.check:
        if is_stale(target):
            print(f"BAYAT: {target} manifestle uyuşmuyor", file=sys.stderr)
            return 1
        print(f"güncel: {target}")
        return 0
    print(write_manifest(target))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
