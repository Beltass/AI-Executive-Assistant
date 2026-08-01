"""Seed ``frontend/metrics.json`` with a representative sample history.

WHY THIS EXISTS. The performance tab charts a rolling token history. With no
file next to the dashboard a visitor sees "henüz token verisi yok" and cannot
tell a working deploy from a broken one — the same problem
``scripts/seed_dashboard.py`` solves for the report documents.

WHAT IT IS HONEST ABOUT. Every run this writes carries ``"sample": true`` and
the document carries a ``sample`` flag, which the dashboard renders as a visible
"örnek veri" note. These numbers are *shaped* like real ones (a full briefing
around 10:00 İstanbul plus three cheaper incremental top-ups, a thinking-token
share in the range gemini-2.5-flash actually produces) but they were not
measured. The recommendations are then computed from them by the very same
:func:`ai_assistant.metrics.recommendations` the real data uses, so nothing is
hand-written advice.

The seeded runs age out on their own: the recommendation window is the last 7
runs, so after two days of real briefings no sample influences the advice, and
after 60 runs none of them is on file at all.

Run with::

    python scripts/seed_metrics.py             # writes frontend/metrics.json
    python scripts/seed_metrics.py --force     # overwrite a REAL history too

Without ``--force`` an existing file that already contains non-sample runs is
left alone, so this can never destroy measured data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_assistant import metrics  # noqa: E402
from ai_assistant.config import MODE_FULL, MODE_INCREMENTAL, mode_label  # noqa: E402
from ai_assistant.status_report import ISTANBUL  # noqa: E402

TARGET = ROOT / "frontend" / "metrics.json"

MODEL = "gemini-2.5-flash"

#: The advisor team, with the prompt/output profile each one actually has:
#: ``(id, name, prompt_chars, output_chars)``. The deep-domain personas carry
#: long system prompts; the coaching ones are short. This is what makes the
#: per-agent efficiency comparison show a real spread rather than a flat bar.
TEAM = [
    ("leadership_coach", "Liderlik Koçu", 3200, 2900),
    ("kids_development", "Çocuk Gelişimi Danışmanı", 3100, 2700),
    ("career_hr", "Kariyer & İK Danışmanı", 3300, 2800),
    ("job_scout", "İş Avcısı & Başvuru Hazırlayıcı", 4100, 2600),
    ("sector_intel", "Sektör & Rakip İstihbaratı", 4400, 3100),
    ("ai_news", "Yapay Zeka Haberleri", 3900, 2500),
    ("free_certs", "Ücretsiz Sertifika & Eğitim", 3400, 2400),
    ("banking_cc_projects", "Banka & Çağrı Merkezi Proje Uzmanı", 7800, 3400),
    ("ai_mastery", "Yapay Zeka Ustalığı Koçu", 5200, 3000),
    ("cx_research", "Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı", 6100, 3200),
    ("language_coach", "İngilizce & Yönetici İletişimi Koçu", 3000, 2600),
    ("accountability_coach", "Hesap Sorucu Koç", 1800, 1500),
]

#: Which advisors have genuinely new material on a mid-day top-up run.
INCREMENTAL_TEAM = ["ai_news", "sector_intel", "cx_research"]

#: Roughly four characters per token for Turkish prose. Only used to turn the
#: character profile above into plausible token counts.
CHARS_PER_TOKEN = 4.0


def _run(moment: datetime, mode: str, fallback: bool, retries: int) -> dict:
    """Build one sample run record with the same shape the real code writes."""
    incremental = mode == MODE_INCREMENTAL
    team = [row for row in TEAM if not incremental or row[0] in INCREMENTAL_TEAM]

    produced = {row[0]: row[3] if not incremental else int(row[3] * 0.55) for row in team}
    prompt_chars = {row[0]: row[2] if not incremental else int(row[2] * 0.7) for row in team}

    # The shared writing guide is sent once for the whole batch, not once per
    # section — the saving the batching change actually banks.
    guide_chars = 2400
    guide_saved = max(0, guide_chars * (len(team) - 1) - 60 * len(team))

    prompt_tokens = int(sum(prompt_chars.values()) / CHARS_PER_TOKEN) + 700
    output_tokens = int(sum(produced.values()) / CHARS_PER_TOKEN)
    thoughts_tokens = int(output_tokens * (0.34 if not incremental else 0.41))
    total_tokens = prompt_tokens + output_tokens + thoughts_tokens

    characters = sum(produced.values())
    agents = metrics.attribute_tokens(produced, prompt_chars, prompt_tokens, output_tokens)
    names = {row[0]: row[1] for row in TEAM}
    for agent in agents:
        agent["name"] = names.get(agent["id"], agent["id"])

    latency = (58.0 if not incremental else 24.0) + (35.0 if fallback else 0.0)

    return {
        "at": moment.astimezone(ISTANBUL).isoformat(timespec="seconds"),
        "at_istanbul": moment.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M"),
        "mode": mode,
        "mode_label": mode_label(mode),
        "provider": "gemini",
        "model": "gemini-flash-latest" if fallback else MODEL,
        "llm_called": True,
        "llm_ok": True,
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "thoughts_tokens": thoughts_tokens,
        "total_tokens": total_tokens,
        "latency_seconds": round(latency, 2),
        "duration_seconds": round(latency + 12.0, 1),
        "retries": retries,
        "fallback_used": fallback,
        "models_tried": 2 if fallback else 1,
        "advisors_ok": len(team) + 1,
        "advisors_failed": 0,
        "advisors_skipped": 15 - len(team) - 1,
        "sections": len(team),
        "sections_requested": len(team),
        "characters": characters,
        "prompt_chars_total": sum(prompt_chars.values()) + guide_chars + 2600,
        "guide_saved_chars": guide_saved,
        "chars_per_1k_tokens": metrics.chars_per_1k_tokens(characters, total_tokens),
        "tokens_per_section": metrics.tokens_per_section(total_tokens, len(team)),
        "thoughts_share": round(thoughts_tokens / total_tokens * 100, 1),
        "prompt_share": round(prompt_tokens / total_tokens * 100, 1),
        "agents": agents,
        "attribution": "estimate",
        # The honesty flag: the dashboard renders this as "örnek veri".
        "sample": True,
    }


def build_history(now: datetime, days: int = 3) -> list:
    """Three days of the real schedule: one full run plus three top-ups."""
    runs = []
    start = (now - timedelta(days=days - 1)).replace(
        hour=10, minute=4, second=0, microsecond=0
    )
    schedule = [(10, MODE_FULL), (14, MODE_INCREMENTAL), (18, MODE_INCREMENTAL), (22, MODE_INCREMENTAL)]
    index = 0
    for day in range(days):
        for hour, mode in schedule:
            moment = (start + timedelta(days=day)).replace(hour=hour)
            if moment > now:
                continue
            # The free tier really does hand out a spare model now and then.
            fallback = index in (2, 6)
            runs.append(_run(moment, mode, fallback, retries=1 if fallback else 0))
            index += 1
    return runs


def has_real_runs(path: Path) -> bool:
    """True when the file already holds at least one MEASURED run."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    runs = document.get("runs") if isinstance(document, dict) else None
    if not isinstance(runs, list):
        return False
    return any(isinstance(run, dict) and not run.get("sample") for run in runs)


def main() -> int:
    force = "--force" in sys.argv
    if TARGET.exists() and has_real_runs(TARGET) and not force:
        print(f"{TARGET} zaten gerçek ölçüm içeriyor — dokunulmadı (--force ile ez).")
        return 0

    now = datetime.now(ISTANBUL)
    runs = build_history(now)
    document = metrics.build_document(runs, now=now)
    document["sample"] = True
    document["sample_note"] = (
        "Bu geçmiş, pano ilk yayınında boş görünmesin diye hazırlanmış ÖRNEK "
        "veridir; ölçülmemiştir. İlk gerçek brifing çalıştırmasından sonra "
        "gerçek ölçümler eklenir ve örnekler zamanla listeden düşer."
    )

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{TARGET} yazıldı: {len(runs)} örnek çalıştırma, "
          f"{len(document['recommendations'])} öneri üretildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
