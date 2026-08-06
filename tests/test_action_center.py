"""Tek ActionItem modeli: tekillik, takma adlar, öncelik dönüşümü."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_assistant import reports
from ai_assistant.action_center import (
    ActionItem,
    priority_to_code,
    priority_to_rank,
)
from ai_assistant.advisors import meeting_notes

SRC = Path(__file__).resolve().parents[1] / "src"
_CLASS_RE = re.compile(r"^class\s+ActionItem\b", re.MULTILINE)


class TestSingleDefinition:
    """Kaynak ağacında ActionItem'ın tek bir tanımı olmalı."""

    def test_only_one_class_actionitem_in_src(self):
        hits = [
            path
            for path in SRC.rglob("*.py")
            if _CLASS_RE.search(path.read_text(encoding="utf-8"))
        ]
        assert [p.name for p in hits] == ["action_center.py"], (
            "ActionItem birden fazla yerde tanımlı: "
            f"{[str(p.relative_to(SRC)) for p in hits]}"
        )

    def test_both_modules_share_the_same_class(self):
        assert reports.ActionItem is ActionItem
        assert meeting_notes.ActionItem is ActionItem


class TestPriorityRoundTrip:
    """1-5 tamsayısı ile P0-P3 kodu iki yönlü konuşur."""

    @pytest.mark.parametrize(
        "rank,code",
        [(1, "P0"), (2, "P1"), (3, "P2"), (4, "P3"), (5, "P3")],
    )
    def test_rank_to_code(self, rank, code):
        assert priority_to_code(rank) == code
        assert ActionItem(title="x", priority=rank).priority_code == code

    @pytest.mark.parametrize("code,rank", [("P0", 1), ("P1", 2), ("P2", 3), ("P3", 4)])
    def test_code_to_rank(self, code, rank):
        assert priority_to_rank(code) == rank
        assert ActionItem(title="x", priority=code).priority_rank == rank

    def test_round_trip_is_stable_for_one_to_four(self):
        for rank in (1, 2, 3, 4):
            assert priority_to_rank(priority_to_code(rank)) == rank

    def test_out_of_range_and_garbage_are_clamped(self):
        assert priority_to_code(0) == "P0"
        assert priority_to_code(99) == "P3"
        assert priority_to_code("hiç") == "P2"
        assert priority_to_rank(None) == 3
        assert priority_to_rank(True) == 3

    def test_stored_value_is_not_rewritten(self):
        """Mevcut kod ``item.priority == 4`` diyor; alan olduğu gibi kalır."""
        assert ActionItem(description="x", priority=4).priority == 4
        assert ActionItem(title="x", priority="P1").priority == "P1"


class TestLegacyAliases:
    """Eski alan adları yeni şemaya bağlanır, kırılmaz."""

    def test_text_description_title_are_one_field(self):
        item = ActionItem(text="Raporu gönder")
        assert item.title == "Raporu gönder"
        assert item.description == "Raporu gönder"
        item.text = "Yeni metin"
        assert item.title == "Yeni metin"
        item.description = "Üçüncü"
        assert item.text == "Üçüncü"

    def test_deadline_maps_to_due_date_both_ways(self):
        when = datetime.now(timezone.utc) + timedelta(days=3)
        item = ActionItem(description="İncele", deadline=when)
        assert item.due_date == when
        assert item.deadline == when

        other = ActionItem(title="İncele", due_date="bu hafta")
        assert other.deadline == "bu hafta"

    def test_defaults_match_the_old_dataclasses(self):
        item = ActionItem()
        assert item.status == "pending"
        assert item.priority == 3
        assert item.deadline is None
        assert item.approval_status == "not_required"
        assert item.evidence_links == []
        assert len(item.id) == 8

    def test_reports_payload_shape_unchanged(self):
        item = ActionItem(text="Sun", deadline="bugün", owner="Burak")
        assert item.as_dict() == {
            "text": "Sun",
            "deadline": "bugün",
            "owner": "Burak",
        }
        assert ActionItem(text="Sun").as_dict() == {"text": "Sun"}


class TestActionCenterSchema:
    """Dashboard'un okuduğu tam şema."""

    def test_to_dict_has_every_action_center_field(self):
        item = ActionItem(
            title="KPI sapmasını incele",
            priority=1,
            owner="Burak",
            due_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
            source_advisor="data_analyst",
            evidence_links=["https://example.com/kpi"],
            impact="Gelir riski",
            recommendation="Kampanyayı durdur",
            approval_status="pending",
        )
        payload = item.to_dict()
        assert payload["priority"] == "P0"
        assert payload["priority_rank"] == 1
        assert payload["due_date"] == "2026-08-05T00:00:00+00:00"
        assert payload["source_advisor"] == "data_analyst"
        assert set(payload) == {
            "id",
            "title",
            "priority",
            "owner",
            "due_date",
            "source_advisor",
            "evidence_links",
            "impact",
            "recommendation",
            "approval_status",
            "status",
            "priority_rank",
        }

    def test_from_dict_round_trip(self):
        item = ActionItem(title="Onay al", priority="P1", approval_status="pending")
        again = ActionItem.from_dict(item.to_dict())
        assert again.title == "Onay al"
        assert again.priority_code == "P1"
        assert again.approval_status == "pending"

    def test_from_dict_reads_legacy_payloads(self):
        again = ActionItem.from_dict(
            {"text": "Eski kayıt", "deadline": "bu hafta", "owner": "Ayşe"}
        )
        assert again.title == "Eski kayıt"
        assert again.due_date == "bu hafta"
        assert again.owner == "Ayşe"


class TestMeetingNotesSerialisation:
    """Toplantı notlarının JSON'u aynı anahtarlarla çıkmaya devam eder."""

    def test_meeting_notes_to_dict_action_item_keys(self):
        when = datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc)
        notes = meeting_notes.MeetingNotes(title="Sprint")
        notes.action_items = [
            ActionItem(
                description="Doküman yaz", owner="Burak", deadline=when, priority=2
            )
        ]
        payload = notes.to_dict()["action_items"][0]
        assert set(payload) == {
            "id",
            "description",
            "owner",
            "deadline",
            "priority",
            "status",
            "created_at",
        }
        assert payload["description"] == "Doküman yaz"
        assert payload["deadline"] == when.isoformat()
        assert payload["priority"] == 2
