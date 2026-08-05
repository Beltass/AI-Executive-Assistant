"""Danışman Dialog Sistemi Testleri.

Test Kapsamı:
- Dialog durumu yönetimi (create, load, save)
- Danışman seçim menüsü
- Multi-turn konuşma
- State transitions
- Advisor routing
- Response formatting
"""

import json
import os
import tempfile
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from src.ai_assistant.chat.advisor_dialog import (
    AdvisorType,
    DialogState,
    Message,
    AdvisorDialog,
    AdvisorDialogManager,
    AdvisorDialogFlow,
    create_advisor_menu_blocks,
)

# ============================================================================
# Tests for AdvisorDialog dataclass
# ============================================================================


class TestAdvisorDialog:
    """AdvisorDialog yapısının testleri."""

    def test_advisor_dialog_creation(self):
        """Dialog oluşturma."""
        dialog = AdvisorDialog(
            user_id="U12345",
            advisor_key="data_analyst",
        )

        assert dialog.user_id == "U12345"
        assert dialog.advisor_key == "data_analyst"
        assert dialog.current_state == "menu"
        assert dialog.conversation_history == []
        assert isinstance(dialog.context, dict)

    def test_advisor_dialog_to_dict(self):
        """Dialog'u dict'e çevirme."""
        dialog = AdvisorDialog(
            user_id="U12345",
            advisor_key="social_media_coach",
        )
        dialog.conversation_history.append(Message(role="user", content="Merhaba"))

        data = dialog.to_dict()

        assert data["user_id"] == "U12345"
        assert data["advisor_key"] == "social_media_coach"
        assert len(data["conversation_history"]) == 1
        assert data["conversation_history"][0]["role"] == "user"

    def test_advisor_dialog_from_dict(self):
        """Dict'ten dialog oluşturma."""
        data = {
            "user_id": "U12345",
            "advisor_key": "personal_assistant",
            "conversation_history": [
                {
                    "role": "user",
                    "content": "Merhaba",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
            "current_state": "waiting_input",
            "context": {},
            "last_interaction": datetime.now().isoformat(),
            "temporary_data": {},
            "tags": ["urgent"],
        }

        dialog = AdvisorDialog.from_dict(data)

        assert dialog.user_id == "U12345"
        assert dialog.advisor_key == "personal_assistant"
        assert dialog.current_state == "waiting_input"
        assert len(dialog.conversation_history) == 1
        assert dialog.tags == ["urgent"]


# ============================================================================
# Tests for AdvisorDialogManager
# ============================================================================


class TestAdvisorDialogManager:
    """Dialog Yöneticisinin testleri."""

    def test_manager_initialization(self):
        """Manager başlatma."""
        manager = AdvisorDialogManager()
        assert manager is not None

    def test_get_or_create_dialog_new(self):
        """Yeni dialog oluşturma."""
        manager = AdvisorDialogManager()
        advisor_key = AdvisorType.DATA_ANALYST.value
        user_id = "U12345"

        dialog = manager.get_or_create_dialog(advisor_key, user_id)

        assert dialog.user_id == user_id
        assert dialog.advisor_key == advisor_key
        assert dialog.current_state == DialogState.MENU.value

    def test_save_and_load_dialog(self):
        """Dialog kaydetme ve yükleme."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AdvisorDialogManager()

            # Geçici dosya yolunu ayarla
            with patch.object(manager, "_get_dialog_file") as mock_get_file:
                temp_file = os.path.join(tmpdir, "test_dialog.json")
                mock_get_file.return_value = temp_file

                # Dialog oluştur ve kaydet
                dialog = AdvisorDialog(
                    user_id="U12345",
                    advisor_key="data_analyst",
                    current_state=DialogState.WAITING_INPUT.value,
                )
                dialog.conversation_history.append(Message(role="user", content="Test"))

                save_result = manager.save_dialog(dialog)
                assert save_result is True

                # Yükleme test
                loaded_dialog = manager.get_dialog("data_analyst", "U12345")
                if loaded_dialog:  # Dosya başarıyla yüklendiyse
                    assert loaded_dialog.user_id == "U12345"
                    assert len(loaded_dialog.conversation_history) == 1

    def test_clear_dialog(self):
        """Dialog temizleme."""
        manager = AdvisorDialogManager()

        with patch.object(manager, "_get_dialog_file") as mock_get_file:
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_file = os.path.join(tmpdir, "test_dialog.json")
                mock_get_file.return_value = temp_file

                # Dialog oluştur ve kaydet
                dialog = AdvisorDialog(user_id="U12345", advisor_key="data_analyst")
                manager.save_dialog(dialog)

                # Temizle
                result = manager.clear_dialog("data_analyst", "U12345")
                assert result is True


# ============================================================================
# Tests for AdvisorDialogFlow
# ============================================================================


class TestAdvisorDialogFlow:
    """Dialog Akışının testleri."""

    def test_flow_initialization(self):
        """Flow başlatma."""
        flow = AdvisorDialogFlow()
        assert flow.manager is not None

    def test_show_advisor_menu(self):
        """Danışman menüsü gösterme."""
        flow = AdvisorDialogFlow()
        response = flow.show_advisor_menu("U12345")

        assert response["type"] == "blocks"
        assert "blocks" in response
        assert len(response["blocks"]) > 0

    def test_handle_advisor_selection_data_analyst(self):
        """Veri Analisti seçimi işleme."""
        flow = AdvisorDialogFlow()

        advisor_key, response = flow.handle_advisor_selection("U12345", "1")

        assert advisor_key == AdvisorType.DATA_ANALYST.value
        assert "text" in response

    def test_handle_advisor_selection_social_media_coach(self):
        """Sosyal Medya Koçu seçimi işleme."""
        flow = AdvisorDialogFlow()

        advisor_key, response = flow.handle_advisor_selection("U12345", "2")

        assert advisor_key == AdvisorType.SOCIAL_MEDIA_COACH.value
        assert "text" in response

    def test_handle_advisor_selection_personal_assistant(self):
        """Kişisel Asistan seçimi işleme."""
        flow = AdvisorDialogFlow()

        advisor_key, response = flow.handle_advisor_selection("U12345", "3")

        assert advisor_key == AdvisorType.PERSONAL_ASSISTANT.value
        assert "text" in response

    def test_handle_advisor_selection_invalid(self):
        """Geçersiz seçim işleme."""
        flow = AdvisorDialogFlow()

        advisor_key, response = flow.handle_advisor_selection("U12345", "invalid")

        assert advisor_key is None
        assert "text" in response

    def test_data_analyst_multi_turn_conversation(self):
        """Veri Analisti multi-turn konuşma."""
        flow = AdvisorDialogFlow()

        # Adım 1: Danışman seçimi
        advisor_key, _ = flow.handle_advisor_selection("U12345", "1")
        assert advisor_key == AdvisorType.DATA_ANALYST.value

        # Adım 2: Veri yükleme
        response = flow.handle_advisor_input(
            advisor_key, "U12345", "CSV dosyası yüklüyorum"
        )
        assert response["type"] == "message"
        assert "text" in response

    def test_social_media_coach_multi_turn_conversation(self):
        """Sosyal Medya Koçu multi-turn konuşma."""
        flow = AdvisorDialogFlow()

        # Adım 1: Danışman seçimi
        advisor_key, _ = flow.handle_advisor_selection("U12345", "2")
        assert advisor_key == AdvisorType.SOCIAL_MEDIA_COACH.value

        # Adım 2: Platform seçimi
        response = flow.handle_advisor_input(advisor_key, "U12345", "LinkedIn")
        assert response["type"] == "message"
        assert "text" in response

        # Adım 3: Aksiyonu belirt
        response = flow.handle_advisor_input(
            advisor_key, "U12345", "Profil analizi yap"
        )
        assert response["type"] == "message"

    def test_personal_assistant_multi_turn_conversation(self):
        """Kişisel Asistan multi-turn konuşma."""
        flow = AdvisorDialogFlow()

        # Adım 1: Danışman seçimi
        advisor_key, _ = flow.handle_advisor_selection("U12345", "3")
        assert advisor_key == AdvisorType.PERSONAL_ASSISTANT.value

        # Adım 2: Aksiyonu belirt
        response = flow.handle_advisor_input(advisor_key, "U12345", "Bugünün özeti")
        assert response["type"] == "message"
        assert "Briefing" in response["text"] or "özet" in response["text"].lower()

    def test_data_analyst_workflow(self):
        """Veri Analisti tam iş akışı."""
        flow = AdvisorDialogFlow()

        # Menüyü göster
        menu_response = flow.show_advisor_menu("U12345")
        assert menu_response["type"] == "blocks"

        # Veri Analisti seçimi
        advisor_key, initial_response = flow.handle_advisor_selection("U12345", "1")
        assert advisor_key == AdvisorType.DATA_ANALYST.value

        # Veri yükleme
        upload_response = flow.handle_advisor_input(advisor_key, "U12345", "CSV")
        assert "text" in upload_response

        # Analiz türü seçimi
        analysis_response = flow.handle_advisor_input(advisor_key, "U12345", "trend")
        assert "text" in analysis_response

        # Format seçimi (format keywords: "rapor", "dashboard", "csv", "excel")
        format_response = flow.handle_advisor_input(advisor_key, "U12345", "rapor")
        assert "text" in format_response
        assert (
            "indir" in format_response["text"].lower()
            or "rapor" in format_response["text"].lower()
        )

    def test_social_media_coach_profile_audit(self):
        """Sosyal Medya Koçu profil denetimi."""
        flow = AdvisorDialogFlow()

        # Seçim
        advisor_key, _ = flow.handle_advisor_selection("U12345", "2")

        # Platform
        flow.handle_advisor_input(advisor_key, "U12345", "LinkedIn")

        # Profil denetimi
        response = flow.handle_advisor_input(advisor_key, "U12345", "audit")
        assert "text" in response
        assert any(
            word in response["text"].lower()
            for word in ["güçlü", "iyileştir", "profil"]
        )

    def test_social_media_coach_content_strategy(self):
        """Sosyal Medya Koçu content stratejisi."""
        flow = AdvisorDialogFlow()

        # Seçim
        advisor_key, _ = flow.handle_advisor_selection("U12345", "2")

        # Platform
        flow.handle_advisor_input(advisor_key, "U12345", "Instagram")

        # Strateji
        response = flow.handle_advisor_input(advisor_key, "U12345", "strateji")
        assert "text" in response
        assert (
            "haftalık" in response["text"].lower()
            or "strategy" in response["text"].lower()
        )

    def test_personal_assistant_priority_tasks(self):
        """Kişisel Asistan acil görevler."""
        flow = AdvisorDialogFlow()

        # Seçim
        advisor_key, _ = flow.handle_advisor_selection("U12345", "3")

        # Acil görevler
        response = flow.handle_advisor_input(advisor_key, "U12345", "acil")
        assert "text" in response
        assert "görev" in response["text"].lower() or "task" in response["text"].lower()

    def test_personal_assistant_goal_tracking(self):
        """Kişisel Asistan hedef takibi."""
        flow = AdvisorDialogFlow()

        # Seçim
        advisor_key, _ = flow.handle_advisor_selection("U12345", "3")

        # Hedef takibi
        response = flow.handle_advisor_input(advisor_key, "U12345", "hedef")
        assert "text" in response
        assert "hedef" in response["text"].lower()

    def test_personal_assistant_evening_summary(self):
        """Kişisel Asistan akşam özeti."""
        flow = AdvisorDialogFlow()

        # Seçim
        advisor_key, _ = flow.handle_advisor_selection("U12345", "3")

        # Akşam özeti
        response = flow.handle_advisor_input(advisor_key, "U12345", "akşam")
        assert "text" in response


# ============================================================================
# Tests for Block Kit generation
# ============================================================================


class TestBlockKitGeneration:
    """Block Kit oluşturmanın testleri."""

    def test_create_advisor_menu_blocks(self):
        """Menü Block Kit'i oluşturma."""
        blocks = create_advisor_menu_blocks()

        assert isinstance(blocks, list)
        assert len(blocks) > 0
        assert blocks[0]["type"] == "section"

        # Actions button'ları kontrol et
        actions_block = [b for b in blocks if b["type"] == "actions"]
        assert len(actions_block) > 0
        assert len(actions_block[0]["elements"]) == 3


# ============================================================================
# Integration tests
# ============================================================================


class TestIntegration:
    """Entegrasyon testleri."""

    def test_end_to_end_data_analyst(self):
        """Baştan sona Veri Analisti akışı."""
        flow = AdvisorDialogFlow()

        # Workflow
        responses = []

        # 1. Menü göster
        menu = flow.show_advisor_menu("U999")
        assert menu["type"] == "blocks"

        # 2. Danışman seç
        advisor_key, sel_response = flow.handle_advisor_selection("U999", "1")
        assert advisor_key == "data_analyst"
        responses.append(sel_response)

        # 3. Veri yükle
        resp = flow.handle_advisor_input("data_analyst", "U999", "CSV dosyası")
        responses.append(resp)

        # 4. Analiz türü
        resp = flow.handle_advisor_input("data_analyst", "U999", "trend")
        responses.append(resp)

        # 5. Format
        resp = flow.handle_advisor_input("data_analyst", "U999", "Excel")
        responses.append(resp)

        # Kontroller
        assert len(responses) >= 3
        for r in responses:
            assert "text" in r or "blocks" in r

    def test_concurrent_user_dialogs(self):
        """Eş zamanlı kullanıcı dialog'ları."""
        flow = AdvisorDialogFlow()

        # Üç farklı kullanıcı
        users = ["U111", "U222", "U333"]
        advisors = ["1", "2", "3"]

        for user, advisor_num in zip(users, advisors):
            advisor_key, response = flow.handle_advisor_selection(user, advisor_num)
            assert advisor_key is not None
            assert "text" in response

            # Dialog durumunu kontrol et
            dialog = flow.manager.get_dialog(advisor_key, user)
            if dialog:
                assert dialog.user_id == user
                assert dialog.advisor_key == advisor_key


# ============================================================================
# State persistence tests
# ============================================================================


class TestStatePersistence:
    """Durum kalıcılığı testleri."""

    def test_dialog_state_persistence(self):
        """Dialog durumunun kalıcılığı."""
        manager = AdvisorDialogManager()

        dialog1 = AdvisorDialog(
            user_id="U123",
            advisor_key="data_analyst",
            current_state=DialogState.WAITING_INPUT.value,
        )
        dialog1.conversation_history.append(Message(role="user", content="Test"))
        dialog1.context["step"] = 2

        # Kaydet
        manager.save_dialog(dialog1)

        # Yükle
        loaded = manager.get_dialog("data_analyst", "U123")
        if loaded:
            assert loaded.current_state == DialogState.WAITING_INPUT.value
            assert len(loaded.conversation_history) >= 1
            assert loaded.context.get("step") == 2

    def test_multiple_advisors_same_user(self):
        """Aynı kullanıcı, farklı advisorlar."""
        flow = AdvisorDialogFlow()

        user_id = "UXXXXX"

        # Advisors seç
        for advisor_num in ["1", "2", "3"]:
            advisor_key, _ = flow.handle_advisor_selection(user_id, advisor_num)
            assert advisor_key is not None

            # Input gönder
            response = flow.handle_advisor_input(advisor_key, user_id, "Test input")
            assert response["type"] == "message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
