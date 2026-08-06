"""Tek bir aksiyon modeli — Action Center'ın ortak şeması.

Repoda iki ayrı ``ActionItem`` vardı: biri toplantı notlarının çıkardığı
görev (``owner``/``deadline``/``priority`` 1-5), diğeri rapor gövdesindeki
"Aksiyonlar" satırı (``text``/``deadline``/``owner``). İkisi de aynı şeyi
anlatıyordu, bu yüzden burada TEK tanım var; her iki modül de bunu içe
aktarır ve eski alan adları takma ad (alias) olarak yaşamaya devam eder.

Kanonik şema:

    id, title, priority, owner, due_date, source_advisor, evidence_links,
    impact, recommendation, approval_status, status

Eski adların karşılıkları:

    ``text`` / ``description`` -> ``title``
    ``deadline``              -> ``due_date``

``priority`` iki dilde konuşur: toplantı notlarının 1-5 tamsayısı ve
dashboard'un P0-P3 kodu. Alan neyle kurulduysa onu saklar (mevcut testler
``item.priority == 4`` diyor, bunu bozmayız); dönüşüm
:func:`priority_to_code` / :func:`priority_to_rank` ve
``priority_code`` / ``priority_rank`` özellikleriyle yapılır.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "ActionItem",
    "PRIORITY_CODES",
    "priority_to_code",
    "priority_to_rank",
    "normalize_priority",
    "APPROVAL_STATUSES",
]

#: Dashboard'un konuştuğu öncelik kodları, en acilden en sakine.
PRIORITY_CODES = ("P0", "P1", "P2", "P3")

#: Onay akışının durakları. ``not_required`` varsayılan: bir aksiyon aksi
#: söylenmedikçe kimsenin onayını beklemez.
APPROVAL_STATUSES = ("not_required", "pending", "approved", "rejected")

#: 1-5 tamsayısı -> P kodu. 1 en acil; 4 ve 5 aynı kovaya (P3) düşer çünkü
#: dashboard'da "yapılacak ama beklesin" için tek bir rafımız var.
_RANK_TO_CODE = {1: "P0", 2: "P1", 3: "P2", 4: "P3", 5: "P3"}

#: P kodu -> 1-5. ``P3`` geri dönerken 4 olur; 5'e yuvarlamak, kullanıcının
#: hiç yazmadığı bir "en düşük öncelik" iddiası olurdu.
_CODE_TO_RANK = {"P0": 1, "P1": 2, "P2": 3, "P3": 4}


def priority_to_code(value: Any, default: str = "P2") -> str:
    """1-5 tamsayısını (veya zaten P kodu olan değeri) ``P0``-``P3`` yap."""
    if isinstance(value, str):
        code = value.strip().upper()
        if code in _CODE_TO_RANK:
            return code
        try:
            value = int(code)
        except (TypeError, ValueError):
            return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        rank = int(value)
        if rank < 1:
            rank = 1
        elif rank > 5:
            rank = 5
        return _RANK_TO_CODE[rank]
    return default


def priority_to_rank(value: Any, default: int = 3) -> int:
    """``P0``-``P3`` kodunu (veya zaten tamsayı olan değeri) 1-5 yap."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        rank = int(value)
        return min(5, max(1, rank))
    if isinstance(value, str):
        code = value.strip().upper()
        if code in _CODE_TO_RANK:
            return _CODE_TO_RANK[code]
        try:
            return min(5, max(1, int(code)))
        except (TypeError, ValueError):
            return default
    return default


def normalize_priority(value: Any) -> str:
    """Dışarıdan gelen her şeyi tek bir P koduna indirger."""
    return priority_to_code(value)


_UNSET = object()


@dataclass(init=False)
class ActionItem:
    """Bir yapılacak iş: kim, ne zaman, ne kadar acil, hangi ajandan.

    Kurucusu hem yeni hem eski isimleri kabul eder::

        ActionItem(text="Raporu gönder", deadline="bu hafta")      # reports
        ActionItem(description="Raporu gönder", priority=4)        # meeting
        ActionItem(title="Raporu gönder", priority="P1")           # yeni
    """

    id: str = ""
    title: str = ""
    priority: Any = 3
    owner: str = ""
    due_date: Any = None
    source_advisor: str = ""
    evidence_links: List[str] = field(default_factory=list)
    impact: str = ""
    recommendation: str = ""
    approval_status: str = "not_required"
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __init__(
        self,
        title: str = "",
        *,
        id: Optional[str] = None,
        text: Optional[str] = None,
        description: Optional[str] = None,
        priority: Any = 3,
        owner: str = "",
        due_date: Any = _UNSET,
        deadline: Any = _UNSET,
        source_advisor: str = "",
        evidence_links: Optional[List[str]] = None,
        impact: str = "",
        recommendation: str = "",
        approval_status: str = "not_required",
        status: str = "pending",
        created_at: Optional[datetime] = None,
    ) -> None:
        self.id = id if id else str(uuid.uuid4())[:8]
        self.title = title or text or description or ""
        self.priority = priority
        self.owner = owner
        if due_date is not _UNSET:
            self.due_date = due_date
        elif deadline is not _UNSET:
            self.due_date = deadline
        else:
            self.due_date = None
        self.source_advisor = source_advisor
        self.evidence_links = list(evidence_links or [])
        self.impact = impact
        self.recommendation = recommendation
        self.approval_status = approval_status
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc)

    # --- eski isimler, aynı veri ------------------------------------------

    @property
    def text(self) -> str:
        """``reports`` tarafının adı: aksiyon satırının metni."""
        return self.title

    @text.setter
    def text(self, value: str) -> None:
        self.title = value

    @property
    def description(self) -> str:
        """``meeting_notes`` tarafının adı: yapılacak işin tarifi."""
        return self.title

    @description.setter
    def description(self, value: str) -> None:
        self.title = value

    @property
    def deadline(self) -> Any:
        """``due_date``ın eski adı; tipini olduğu gibi korur."""
        return self.due_date

    @deadline.setter
    def deadline(self, value: Any) -> None:
        self.due_date = value

    # --- öncelik iki yönlü -------------------------------------------------

    @property
    def priority_code(self) -> str:
        """Önceliğin ``P0``-``P3`` hâli."""
        return priority_to_code(self.priority)

    @property
    def priority_rank(self) -> int:
        """Önceliğin 1-5 hâli."""
        return priority_to_rank(self.priority)

    # --- serileştirme ------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        """Rapor gövdesinin beklediği dar payload — DEĞİŞMEDİ.

        Boş alanlar hiç yazılmaz; frontend'in checklist'i sadece yazılanı
        gösterir.
        """
        payload: Dict[str, Any] = {"text": self.title}
        if self.due_date:
            payload["deadline"] = self.due_date
        if self.owner:
            payload["owner"] = self.owner
        return payload

    def to_dict(self) -> Dict[str, Any]:
        """Action Center'ın tam şeması (dashboard ve JSON kalıcılığı için)."""
        due = self.due_date
        if isinstance(due, datetime):
            due = due.isoformat()
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority_code,
            "priority_rank": self.priority_rank,
            "owner": self.owner,
            "due_date": due,
            "source_advisor": self.source_advisor,
            "evidence_links": list(self.evidence_links),
            "impact": self.impact,
            "recommendation": self.recommendation,
            "approval_status": self.approval_status,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionItem":
        """:meth:`to_dict` çıktısını (ve eski adlı payload'ları) geri okur."""
        data = dict(data or {})
        return cls(
            title=str(
                data.get("title") or data.get("text") or data.get("description") or ""
            ),
            id=data.get("id") or None,
            priority=data.get("priority", 3),
            owner=str(data.get("owner") or ""),
            due_date=data.get("due_date", data.get("deadline")),
            source_advisor=str(data.get("source_advisor") or ""),
            evidence_links=list(data.get("evidence_links") or []),
            impact=str(data.get("impact") or ""),
            recommendation=str(data.get("recommendation") or ""),
            approval_status=str(data.get("approval_status") or "not_required"),
            status=str(data.get("status") or "pending"),
        )
