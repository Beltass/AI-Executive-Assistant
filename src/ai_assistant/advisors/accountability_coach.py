"""Accountability coach — Hesap Sorucu Koç.

The one advisor that looks at the OTHER advisors instead of the outside world.
Every persona ends its briefing with a ``✅ Bugünün görevi`` line; this coach
collects them from the CURRENT run, restates them as one checkable list, and —
using the little state it can keep — asks yesterday's uncomfortable question:
*yaptın mı?*

Behaviour science, not nagging: it uses implementation intentions ("saat X'te,
Y yerinde, Z'yi yapacağım"), tiny habits (shrink the task until it is
impossible to skip) and a visible streak, because a streak you can see is the
cheapest commitment device there is. When a day slips it is firm and insistent —
Duolingo-style — but never cruel: the ask is always "restart today", never
"you failed".

Ordering: it MUST run after the others so their tasks exist. The Operations
Manager feeds each advisor the briefings produced so far via
:meth:`~ai_assistant.advisors.Advisor.observe`, and this advisor is registered
LAST in :func:`~ai_assistant.advisors.all_advisors`. If the other sections
failed or were skipped, it degrades to a generic restart nudge.

No LLM: the section is assembled deterministically from the other advisors'
output, so it costs nothing against the free-tier Gemini quota and cannot
hallucinate a task you were never given.

Configuration (via environment):
    ACCOUNTABILITY_STATE_FILE  Where the small JSON state lives. Defaults to
                               ``.assistant_state/accountability.json``.

⚠️ PERSISTENCE LIMITATION: on GitHub Actions the runner filesystem is
EPHEMERAL — every scheduled run starts from a clean checkout, so the state file
written yesterday is gone today. The advisor therefore treats "no prior state"
as a legitimate fresh start (never an error): you still get today's consolidated
task list and a day-1 streak. Durable cross-day tracking would require committing
the state file back to the repo or moving it to an external store (Gist, Notion,
a KV service); that is deliberately NOT done here.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

from . import Advisor, Briefing
from ..config import setting
from ..integrations import STATUS_OK

DEFAULT_STATE_FILE = ".assistant_state/accountability.json"

# The marker every persona ends its briefing with.
TASK_MARKER = "Bugünün görevi"

# Where a captured task stops: the next heading/divider after the marker.
_STOP_LINE = re.compile(r"^\s*(#{1,6}\s|[-*_]{3,}\s*$|\d+\)\s|📚|🔎|⚠️\s*Uyum)")

# Leading list/heading decoration to strip off a captured task line.
_LEAD = re.compile(r"^[\s#>*_`\-–—•]*(?:\d+[.)]\s*)?[\s*_`]*")

MAX_TASK_CHARS = 320


@dataclass
class AccountabilityState:
    """The tiny bit of memory this coach keeps between runs."""

    streak: int = 0
    last_date: str = ""
    last_tasks: List[str] = field(default_factory=list)
    history: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AccountabilityState":
        return cls(
            streak=int(data.get("streak") or 0),
            last_date=str(data.get("last_date") or ""),
            last_tasks=[str(t) for t in (data.get("last_tasks") or [])],
            history={
                str(k): [str(t) for t in (v or [])]
                for k, v in (data.get("history") or {}).items()
            },
        )

    def to_dict(self) -> dict:
        return {
            "streak": self.streak,
            "last_date": self.last_date,
            "last_tasks": self.last_tasks,
            "history": self.history,
        }


class AccountabilityCoachAdvisor(Advisor):
    key = "accountability_coach"
    title = "Hesap Sorucu Koç"

    def __init__(self) -> None:
        self._observed: List[Briefing] = []

    # -- ordering hook ---------------------------------------------------
    def observe(self, briefings: Sequence[Briefing]) -> None:
        """Receive the briefings produced BEFORE this advisor in the run."""
        self._observed = [b for b in briefings if b.key != self.key]

    # -- main path -------------------------------------------------------
    def _generate(self) -> Briefing:
        today = date.today()
        tasks = self._collect_tasks()
        state = self._load_state()

        if not tasks and not state.last_tasks:
            # Nothing was assigned today and nothing is remembered from before:
            # there is genuinely nothing to hold anyone accountable for.
            return self.skipped(
                "takip edilecek görev yok (diğer danışmanlar bugün görev "
                "üretmedi ve önceki çalıştırmadan kayıt bulunamadı)"
            )

        yesterday_tasks, yesterday_label = self._previous(state, today)
        streak = self._next_streak(state, today)
        text = self._render(today, tasks, yesterday_tasks, yesterday_label, streak, state)

        if tasks:
            self._save_state(state, today, tasks, streak)
        return self.ok(text)

    # -- task extraction -------------------------------------------------
    def _collect_tasks(self) -> List[str]:
        """Pull every ``✅ Bugünün görevi`` out of this run's other briefings."""
        tasks: List[str] = []
        for briefing in self._observed:
            if briefing.status != STATUS_OK or not briefing.text:
                continue
            task = extract_task(briefing.text)
            if task:
                tasks.append(f"*{briefing.title}* — {task}")
        return tasks

    # -- state -----------------------------------------------------------
    @staticmethod
    def _state_path() -> str:
        return setting("ACCOUNTABILITY_STATE_FILE")

    def _load_state(self) -> AccountabilityState:
        """Read the state file. A missing/broken file is a FRESH START."""
        path = self._state_path()
        if not path or not os.path.exists(path):
            return AccountabilityState()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return AccountabilityState.from_dict(json.load(fh))
        except Exception:
            # Corrupt or unreadable state must never break the briefing.
            return AccountabilityState()

    def _save_state(
        self,
        state: AccountabilityState,
        today: date,
        tasks: List[str],
        streak: int,
    ) -> None:
        """Persist today's tasks + streak. Any I/O error is swallowed."""
        path = self._state_path()
        if not path:
            return
        iso = today.isoformat()
        state.streak = streak
        state.last_date = iso
        state.last_tasks = tasks
        state.history[iso] = tasks
        # Keep the file small: the last two weeks are plenty for a nudge.
        for key in sorted(state.history)[:-14]:
            state.history.pop(key, None)
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state.to_dict(), fh, ensure_ascii=False, indent=2)
        except Exception:
            # Ephemeral/read-only filesystems are expected (GitHub Actions).
            return

    @staticmethod
    def _previous(state: AccountabilityState, today: date) -> tuple:
        """Return (tasks, human label) for the most recent recorded day."""
        if not state.last_date or not state.last_tasks:
            return [], ""
        if state.last_date == today.isoformat():
            # Same-day re-run: the "previous" day is the one before that.
            previous_days = [d for d in sorted(state.history) if d < state.last_date]
            if not previous_days:
                return [], ""
            day = previous_days[-1]
            return state.history.get(day, []), _label(day, today)
        return state.last_tasks, _label(state.last_date, today)

    @staticmethod
    def _next_streak(state: AccountabilityState, today: date) -> int:
        """Streak = consecutive days with an assigned task list."""
        if not state.last_date:
            return 1
        if state.last_date == today.isoformat():
            return max(state.streak, 1)  # idempotent re-run on the same day
        if state.last_date == (today - timedelta(days=1)).isoformat():
            return state.streak + 1
        return 1  # a gap resets the chain — today is day 1 again

    # -- rendering -------------------------------------------------------
    def _render(
        self,
        today: date,
        tasks: List[str],
        yesterday_tasks: List[str],
        yesterday_label: str,
        streak: int,
        state: AccountabilityState,
    ) -> str:
        lines: List[str] = []

        # 1. The uncomfortable question.
        lines.append("*🔁 Dün ne demiştik?*")
        if yesterday_tasks:
            lines.append(
                f"{yesterday_label} sana şu görev(ler) verilmişti — "
                "tek tek cevapla: *yaptın mı?*"
            )
            lines.extend(f"- [ ] {task}" for task in yesterday_tasks)
            lines.append(
                "Yaptıysan bir saniye durup kendine hakkını ver. Yapmadıysan "
                "bahane arama; bugünkü versiyonunu 10 dakikaya indirip ilk işin "
                "olarak yap. Yarım yapılmış iş, hiç yapılmamış işten iyidir."
            )
        else:
            lines.append(
                "Önceki güne ait kayıt bulamadım (bu koşturma taze bir başlangıç "
                "sayılır). O yüzden bugün tek bir şey soracağım: bu listeden en az "
                "birini bitirmeden günü kapatma."
            )

        # 2. The streak — the cheapest commitment device there is.
        lines.append("")
        lines.append("*🔥 Seri (streak)*")
        if streak <= 1:
            lines.append(
                "Bugün *1. gün*. Seri buradan başlıyor; yarın bu sayının 2 "
                "olmasını istiyorum."
            )
        else:
            lines.append(
                f"*{streak} gün* üst üste görev listesi aldın. Bu seriyi bugün "
                "kırma — zincirin en kıymetli olduğu an, kırılmaya en yakın olduğu andır."
            )
        if not state.last_date:
            lines.append(
                "_Not: kalıcı depolama olmadığından seri her temiz çalıştırmada "
                "yeniden başlayabilir; asıl ölçüt senin işaretlediğin kutular._"
            )

        # 3. Today's consolidated list.
        lines.append("")
        lines.append("*✅ Bugünün toplu görev listesi*")
        if tasks:
            lines.extend(f"- [ ] {task}" for task in tasks)
            lines.append("")
            lines.append(
                "*Uygulama niyeti (implementation intention):* her görev için "
                "şu cümleyi zihninde tamamla — _\"Saat __:__ olduğunda, "
                "____ yerinde, ____ yapacağım.\"_ Niyeti zamana ve mekâna "
                "bağlamak, yapma olasılığını ciddi biçimde artırır."
            )
            lines.append(
                "*Küçült:* listeyi bugün bitiremeyeceğini düşünüyorsan her "
                "görevin 2 dakikalık halini yap (tek paragraf, tek arama, tek "
                "mesaj). Amaç mükemmel gün değil, kırılmayan zincir."
            )
        else:
            lines.append(
                "Bugün diğer danışmanlardan görev gelmedi (bölümler atlandı ya "
                "da hazırlanamadı). Boş geçme: dün yarım kalan işi bitir ya da "
                "kendine 20 dakikalık tek bir gelişim bloğu koy ve şimdi takvime yaz."
            )

        lines.append("")
        lines.append(
            "_Yarın ilk sorum yine aynı olacak: yaptın mı? Cevabı bugünden hazırla._"
        )
        return "\n".join(lines)


# --- module-level helpers (also handy in tests) -----------------------------


def _label(iso_day: str, today: date) -> str:
    """Human Turkish label for a recorded day ('Dün' / the date)."""
    try:
        day = date.fromisoformat(iso_day)
    except ValueError:
        return iso_day
    delta = (today - day).days
    if delta == 1:
        return "Dün"
    if delta == 0:
        return "Bugün daha önce"
    return f"{day.strftime('%d.%m.%Y')} tarihinde"


def extract_task(text: str) -> Optional[str]:
    """Return the ``✅ Bugünün görevi`` content of a briefing, or ``None``.

    Tolerant of the shapes personas actually produce: ``### ✅ Bugünün görevi``,
    ``5. *✅ Bugünün görevi*:`` or a bold line followed by the task on the next
    line.
    """
    if not text or TASK_MARKER.lower() not in text.lower():
        return None

    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if TASK_MARKER.lower() in line.lower():
            start = index
            break
    if start == -1:
        return None

    collected: List[str] = []

    # Anything after the marker on the SAME line is already part of the task.
    head = lines[start]
    position = head.lower().find(TASK_MARKER.lower()) + len(TASK_MARKER)
    remainder = head[position:].lstrip(" *_`:—-–)")
    if remainder.strip():
        collected.append(remainder.strip())

    for line in lines[start + 1 :]:
        if not line.strip():
            if collected:
                break
            continue
        if _STOP_LINE.match(line):
            break
        collected.append(_LEAD.sub("", line).strip())
        if sum(len(part) for part in collected) > MAX_TASK_CHARS:
            break

    task = " ".join(part for part in collected if part).strip(" *_`")
    if not task:
        return None
    if len(task) > MAX_TASK_CHARS:
        task = task[:MAX_TASK_CHARS].rstrip() + "…"
    return task
