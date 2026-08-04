"""Danışman Diyalog Sistemi — Kullanıcı ile etkileşimli konuşma.

Bu modül, kullanıcının DM yoluyla üç ana danışmanla etkileşim kurmasını sağlar:

1. **Veri Analisti** — CSV/JSON veri yükleme, analiz, rapor oluşturma
2. **Sosyal Medya İmaj Koçu** — Platform seçme, profil analizi, content stratejisi
3. **Kişisel Asistan** — Günlük planlama, görev takibi, hedefler, fırsatlar

Durum Makinesi:
    - menu: Danışman seçimi
    - waiting_input: Kullanıcı girdisi bekleniyor
    - processing: Advisor işlem yapıyor
    - ready: Sonuç hazır

Veri Saklama:
    .assistant_state/data_analyst_dialog.json
    .assistant_state/social_media_coach_dialog.json
    .assistant_state/personal_assistant_dialog.json

API Entegrasyonu:
    - direct_messaging.py ile entegre
    - Slack Block Kit formatı ile yanıt
    - Multi-turn konuşma desteği
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_DIR = ".assistant_state"
ADVISOR_STATE_FILE_TEMPLATE = ".assistant_state/{advisor_key}_dialog.json"


class AdvisorType(Enum):
    """Danışman türleri."""
    DATA_ANALYST = "data_analyst"
    SOCIAL_MEDIA_COACH = "social_media_coach"
    PERSONAL_ASSISTANT = "personal_assistant"


class DialogState(Enum):
    """Dialog durum makinesi."""
    MENU = "menu"  # Danışman seçimi
    WAITING_INPUT = "waiting_input"  # Kullanıcı girdisi bekleniyor
    PROCESSING = "processing"  # İşlem yapılıyor
    READY = "ready"  # Sonuç hazır


@dataclass
class Message:
    """Dialog mesajı."""
    role: str  # "user" veya "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AdvisorDialog:
    """Danışman dialog durumu."""
    user_id: str
    advisor_key: str  # "data_analyst", "social_media_coach", "personal_assistant"
    conversation_history: List[Message] = field(default_factory=list)
    current_state: str = "menu"  # DialogState
    context: Dict[str, Any] = field(default_factory=dict)  # Önceki etkileşimler
    last_interaction: str = field(default_factory=lambda: datetime.now().isoformat())
    temporary_data: Dict[str, Any] = field(default_factory=dict)  # İşlem sırasında veri
    tags: List[str] = field(default_factory=list)  # Kategorilendirme

    def to_dict(self) -> Dict[str, Any]:
        """Dict'e dönüştür (JSON serialize için)."""
        return {
            "user_id": self.user_id,
            "advisor_key": self.advisor_key,
            "conversation_history": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in self.conversation_history
            ],
            "current_state": self.current_state,
            "context": self.context,
            "last_interaction": self.last_interaction,
            "temporary_data": self.temporary_data,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AdvisorDialog:
        """Dict'ten oluştur."""
        messages = [
            Message(
                role=m["role"],
                content=m["content"],
                timestamp=m.get("timestamp", datetime.now().isoformat())
            )
            for m in data.get("conversation_history", [])
        ]
        return cls(
            user_id=data["user_id"],
            advisor_key=data["advisor_key"],
            conversation_history=messages,
            current_state=data.get("current_state", "menu"),
            context=data.get("context", {}),
            last_interaction=data.get("last_interaction", datetime.now().isoformat()),
            temporary_data=data.get("temporary_data", {}),
            tags=data.get("tags", []),
        )


class AdvisorDialogManager:
    """Dialog yönetimi — durum, geçişler, kalıcılık."""

    def __init__(self):
        """Manager'ı başlat."""
        self._ensure_state_dir()

    @staticmethod
    def _ensure_state_dir() -> None:
        """State dizinini oluştur."""
        os.makedirs(STATE_DIR, exist_ok=True)

    @staticmethod
    def _get_dialog_file(advisor_key: str, user_id: str) -> str:
        """Dialog dosyası yolunu al."""
        # Her advisor için bir dosya tutabiliriz ya da kullanıcı başına
        # Şimdilik advisor başına yapıyoruz
        return os.path.join(STATE_DIR, f"{advisor_key}_dialog.json")

    def get_dialog(self, advisor_key: str, user_id: str) -> Optional[AdvisorDialog]:
        """Dialog durumunu yükle."""
        file_path = self._get_dialog_file(advisor_key, user_id)
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Eğer dict ise, AdvisorDialog'a dönüştür
                    if isinstance(data, dict) and "user_id" in data:
                        dialog = AdvisorDialog.from_dict(data)
                        if dialog.user_id == user_id:
                            return dialog
        except Exception as exc:
            logger.warning(f"Dialog yükleme başarısız ({advisor_key}, {user_id}): {exc}")
        return None

    def save_dialog(self, dialog: AdvisorDialog) -> bool:
        """Dialog durumunu kaydet."""
        file_path = self._get_dialog_file(dialog.advisor_key, dialog.user_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(dialog.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            logger.warning(f"Dialog kaydetme başarısız: {exc}")
            return False

    def get_or_create_dialog(
        self,
        advisor_key: str,
        user_id: str
    ) -> AdvisorDialog:
        """Dialog al veya yeni oluştur."""
        dialog = self.get_dialog(advisor_key, user_id)
        if not dialog:
            dialog = AdvisorDialog(
                user_id=user_id,
                advisor_key=advisor_key,
                current_state=DialogState.MENU.value
            )
        return dialog

    def clear_dialog(self, advisor_key: str, user_id: str) -> bool:
        """Dialog durumunu temizle."""
        file_path = self._get_dialog_file(advisor_key, user_id)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception as exc:
            logger.warning(f"Dialog temizleme başarısız: {exc}")
            return False


class AdvisorDialogFlow:
    """Dialog akışı — menü, giriş, işlem, sonuç."""

    def __init__(self):
        """Flow manager'ı başlat."""
        self.manager = AdvisorDialogManager()

    def show_advisor_menu(self, user_id: str) -> Dict[str, Any]:
        """Danışman seçim menüsü göster."""
        return {
            "type": "blocks",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Hangi danışmanla çalışmak istiyorsun?*\n\nSana yardımcı olmak için burada üç uzman bekliyorum."
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*1️⃣ Veri Analisti*\n_Veriyi analiz et, rapor oluştur_\n\nCSV, JSON veya açıklama yüklü; trends, correlations ya da summary isteyebilirsin."
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*2️⃣ Sosyal Medya İmaj Koçu*\n_Profil iyileştir, strateji yap_\n\nLinkedIn, Instagram vb. platform; profil audit, content stratejisi, kişisel marka."
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*3️⃣ Kişisel Asistan*\n_Günü planla, hedefleri takip et_\n\nBugünün özeti, acil görevler, hedefler, fırsatlar, akşam özeti."
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_Seçmek için: `1`, `2` veya `3` yazabilirsin._"
                    }
                }
            ]
        }

    def handle_advisor_selection(self, user_id: str, selection: str) -> tuple[Optional[str], Dict[str, Any]]:
        """Danışman seçimini işle."""
        selection = selection.strip().lower()

        advisor_map = {
            "1": AdvisorType.DATA_ANALYST.value,
            "veri": AdvisorType.DATA_ANALYST.value,
            "analiz": AdvisorType.DATA_ANALYST.value,
            "2": AdvisorType.SOCIAL_MEDIA_COACH.value,
            "sosyal": AdvisorType.SOCIAL_MEDIA_COACH.value,
            "instagram": AdvisorType.SOCIAL_MEDIA_COACH.value,
            "linkedin": AdvisorType.SOCIAL_MEDIA_COACH.value,
            "3": AdvisorType.PERSONAL_ASSISTANT.value,
            "asistan": AdvisorType.PERSONAL_ASSISTANT.value,
            "gün": AdvisorType.PERSONAL_ASSISTANT.value,
        }

        advisor_key = advisor_map.get(selection)
        if not advisor_key:
            return None, self._invalid_selection_message()

        # Dialog oluştur veya yükle
        dialog = self.manager.get_or_create_dialog(advisor_key, user_id)
        dialog.current_state = DialogState.WAITING_INPUT.value
        dialog.conversation_history.append(Message(role="user", content=selection))

        self.manager.save_dialog(dialog)

        # İlk prompt'u göster
        if advisor_key == AdvisorType.DATA_ANALYST.value:
            return advisor_key, self._data_analyst_initial_menu()
        elif advisor_key == AdvisorType.SOCIAL_MEDIA_COACH.value:
            return advisor_key, self._social_media_coach_initial_menu()
        elif advisor_key == AdvisorType.PERSONAL_ASSISTANT.value:
            return advisor_key, self._personal_assistant_initial_menu()
        else:
            return advisor_key, {"text": "Advisor başlat başarısız"}

    def handle_advisor_input(
        self,
        advisor_key: str,
        user_id: str,
        user_input: str
    ) -> Dict[str, Any]:
        """Danışman girdisini işle."""
        dialog = self.manager.get_or_create_dialog(advisor_key, user_id)

        # Kullanıcı mesajını history'ye ekle
        dialog.conversation_history.append(Message(role="user", content=user_input))
        dialog.current_state = DialogState.PROCESSING.value

        # Advisor'a yönlendir
        if advisor_key == AdvisorType.DATA_ANALYST.value:
            response = self._handle_data_analyst_input(dialog, user_input)
        elif advisor_key == AdvisorType.SOCIAL_MEDIA_COACH.value:
            response = self._handle_social_media_coach_input(dialog, user_input)
        elif advisor_key == AdvisorType.PERSONAL_ASSISTANT.value:
            response = self._handle_personal_assistant_input(dialog, user_input)
        else:
            response = {"text": "Danışman tanınamadı.", "action": None}

        # Assistant yanıtını history'ye ekle
        dialog.conversation_history.append(Message(role="assistant", content=response["text"]))
        dialog.current_state = DialogState.READY.value
        dialog.last_interaction = datetime.now().isoformat()

        self.manager.save_dialog(dialog)

        return self._format_response(response)

    # --- Veri Analisti Dialog -----------------------------------------------

    def _handle_data_analyst_input(self, dialog: AdvisorDialog, user_input: str) -> Dict[str, Any]:
        """Veri Analisti için input işle."""
        user_input_lower = user_input.lower()

        # Eğer ilk mesajsa — veri yükleme aşaması
        if len(dialog.conversation_history) <= 1:
            return self._data_analyst_initial_menu()

        # Veri yüklüyse
        if any(keyword in user_input_lower for keyword in ["csv", "json", "excel", "yükle", "paste", "yapıştır"]):
            dialog.temporary_data["upload_type"] = self._detect_file_type(user_input)
            return {
                "text": f"📊 Başarıyla {dialog.temporary_data['upload_type']} formatı algılandı.\n\n"
                       f"Ne analiz etmek istiyorsun?\n"
                       f"• *Trend* — zaman içindeki değişimler\n"
                       f"• *Korelasyon* — ilişkiler\n"
                       f"• *Özet* — genel istatistikler",
                "action": "waiting_analysis_type"
            }

        # Analiz türü seçiliyse
        if any(keyword in user_input_lower for keyword in ["trend", "korelasyon", "özet", "summary"]):
            return self._data_analyst_process_analysis(dialog, user_input)

        # Format seçiliyse
        if any(keyword in user_input_lower for keyword in ["excel", "dashboard", "rapor", "csv", "json"]):
            return self._data_analyst_format_output(dialog, user_input)

        return self._data_analyst_ask_clarification()

    def _data_analyst_initial_menu(self) -> Dict[str, Any]:
        """Veri Analisti başlangıç menüsü."""
        return {
            "text": "📊 *Veri Analisti* burada!\n\n"
                   "Ne yapmak ister?\n\n"
                   "1️⃣ Veri yükle (CSV, JSON, Excel, ya da yapıştır)\n"
                   "2️⃣ Önceki analizimi tekrar göster\n\n"
                   "_Başlamak için `1` yazabilirsin veya direkt veri yapıştırabilirsin._",
            "action": "waiting_data_upload"
        }

    def _detect_file_type(self, content: str) -> str:
        """Dosya türünü algıla."""
        content_lower = content.lower()
        if ".csv" in content_lower or "csv" in content_lower:
            return "CSV"
        elif ".json" in content_lower or "json" in content_lower:
            return "JSON"
        elif ".xlsx" in content_lower or "excel" in content_lower:
            return "Excel"
        return "Text"

    def _data_analyst_process_analysis(self, dialog: AdvisorDialog, user_input: str) -> Dict[str, Any]:
        """Veri analizi işle."""
        analysis_type = "Trend" if "trend" in user_input.lower() else "Korelasyon" if "korelasyon" in user_input.lower() else "Özet"
        dialog.temporary_data["analysis_type"] = analysis_type

        return {
            "text": f"🔍 *{analysis_type} Analizi* yapılıyor...\n\n"
                   f"Verilerinizi inceliyorum. Sonuç şu formatta istiyorsun?\n\n"
                   f"• *Excel* — detaylı tablo\n"
                   f"• *Dashboard* — grafikler\n"
                   f"• *Rapor* — yazılı bulguların\n"
                   f"• *CSV* — ham veri",
            "action": "waiting_format_choice"
        }

    def _data_analyst_format_output(self, dialog: AdvisorDialog, user_input: str) -> Dict[str, Any]:
        """Çıktı formatını belirle ve rapor oluştur."""
        output_format = "Excel" if "excel" in user_input.lower() else "Dashboard" if "dashboard" in user_input.lower() else "Rapor" if "rapor" in user_input.lower() else "CSV"

        # Simülasyon: rapor oluştur
        report_text = self._generate_sample_analysis_report(dialog, output_format)

        return {
            "text": report_text,
            "action": "analysis_complete",
            "download_link": f"/reports/analysis_{dialog.user_id}_{int(datetime.now().timestamp())}.xlsx"
        }

    def _data_analyst_ask_clarification(self) -> Dict[str, Any]:
        """Açıklama iste."""
        return {
            "text": "🤔 Anlamadığım bir şey var. Lütfen şunlardan birini dene:\n\n"
                   "• Veri yükle (CSV/JSON/Excel)\n"
                   "• `trend` / `korelasyon` / `özet` analizi iste\n"
                   "• `excel` / `rapor` / `dashboard` format iste",
            "action": "waiting_clarification"
        }

    def _generate_sample_analysis_report(self, dialog: AdvisorDialog, format_type: str) -> str:
        """Örnek analiz raporu oluştur."""
        analysis_type = dialog.temporary_data.get("analysis_type", "Özet")
        return (f"📊 *{analysis_type} Analizi Raporu*\n\n"
                f"Format: *{format_type}*\n\n"
                f"✅ Verileriniz başarıyla analiz edildi.\n\n"
                f"**Temel Bulgular:**\n"
                f"• Veri seti: {dialog.temporary_data.get('upload_type', 'Unknown')} formatı\n"
                f"• Dönem: Son 90 gün\n"
                f"• Kayıt sayısı: 2,847\n\n"
                f"**İstatistikler:**\n"
                f"• Ortalama: 45.23\n"
                f"• Standart sapma: 12.1\n"
                f"• Min-Max: 5.2 - 89.7\n\n"
                f"📥 Rapor indirmek için yukarıdaki linke tıkla.")

    # --- Sosyal Medya İmaj Koçu Dialog -------------------------------------

    def _handle_social_media_coach_input(self, dialog: AdvisorDialog, user_input: str) -> Dict[str, Any]:
        """Sosyal Medya Koçu için input işle."""
        user_input_lower = user_input.lower()

        if len(dialog.conversation_history) <= 1:
            return self._social_media_coach_initial_menu()

        if any(keyword in user_input_lower for keyword in ["linkedin", "instagram", "twitter", "platform"]):
            dialog.temporary_data["platform"] = self._detect_platform(user_input)
            return self._social_media_coach_ask_action(dialog)

        if any(keyword in user_input_lower for keyword in ["audit", "analiz", "profil"]):
            return self._social_media_coach_profile_audit(dialog)

        if any(keyword in user_input_lower for keyword in ["strateji", "content", "içerik", "weekly"]):
            return self._social_media_coach_content_strategy(dialog)

        if any(keyword in user_input_lower for keyword in ["marka", "brand", "kişisel"]):
            return self._social_media_coach_brand_assessment(dialog)

        return self._social_media_coach_ask_clarification()

    def _social_media_coach_initial_menu(self) -> Dict[str, Any]:
        """Sosyal Medya Koçu başlangıç menüsü."""
        return {
            "text": "💼 *Sosyal Medya İmaj Koçu* burada!\n\n"
                   "Hangi platform üzerinde çalışmak istiyorsun?\n\n"
                   "1️⃣ *LinkedIn* — profesyonel ağ\n"
                   "2️⃣ *Instagram* — görsel içerik\n"
                   "3️⃣ *Twitter/X* — kısa haberler\n\n"
                   "_Seç: `1`, `2` veya `3`_",
            "action": "waiting_platform_selection"
        }

    def _detect_platform(self, content: str) -> str:
        """Platform algıla."""
        content_lower = content.lower()
        if "linkedin" in content_lower or "1" in content_lower:
            return "LinkedIn"
        elif "instagram" in content_lower or "2" in content_lower:
            return "Instagram"
        elif "twitter" in content_lower or "x" in content_lower or "3" in content_lower:
            return "Twitter"
        return "LinkedIn"

    def _social_media_coach_ask_action(self, dialog: AdvisorDialog) -> Dict[str, Any]:
        """Sosyal medya aksiyonunu sor."""
        platform = dialog.temporary_data.get("platform", "LinkedIn")
        return {
            "text": f"✨ {platform} seçildi. Ne yapmak istiyorsun?\n\n"
                   f"1️⃣ *Profil Analizi* — Mevcut durumu değerlendir\n"
                   f"2️⃣ *Content Stratejisi* — Haftalık plan\n"
                   f"3️⃣ *Kişisel Marka* — Brand assessment\n\n"
                   f"_Seç: `1`, `2` veya `3`_",
            "action": "waiting_action_selection"
        }

    def _social_media_coach_profile_audit(self, dialog: AdvisorDialog) -> Dict[str, Any]:
        """Profil denetimi yap."""
        platform = dialog.temporary_data.get("platform", "LinkedIn")
        return {
            "text": f"🔍 *{platform} Profil Denetimi*\n\n"
                   f"✅ Güçlü Yönler:\n"
                   f"• Profesyonel fotoğraf — iyi seçilmiş\n"
                   f"• Açık özet — anlaşılır ve çekici\n\n"
                   f"⚠️ İyileştirme Önerileri:\n"
                   f"• Başlık kısa — 120 karakter ekle\n"
                   f"• Özet yazısında keywordler artır\n"
                   f"• Bağlantıları zenginleştir (link ekleme)\n"
                   f"• Tavsiye sayını artır\n\n"
                   f"📊 Tavsiye: Haftada 3 içerik yayınla.",
            "action": "audit_complete"
        }

    def _social_media_coach_content_strategy(self, dialog: AdvisorDialog) -> Dict[str, Any]:
        """Content stratejisi oluştur."""
        platform = dialog.temporary_data.get("platform", "LinkedIn")
        return {
            "text": f"📅 *{platform} — Haftalık Content Stratejisi*\n\n"
                   f"**Pazartesi:** Endüstri İçgörüsü\n"
                   f"_'3 trend 2024'te dikkat çekiyor'_\n\n"
                   f"**Çarşamba:** Kişisel Deneyim\n"
                   f"_'Dün bu hatayı yaptığımda öğrendiğim ders'_\n\n"
                   f"**Cuma:** Eğitim/İpucu\n"
                   f"_'5 adımda Excel mastery'_\n\n"
                   f"✍️ En iyi sonuçlar: 8-10 sabah, 18-19 akşam yayını.",
            "action": "strategy_complete"
        }

    def _social_media_coach_brand_assessment(self, dialog: AdvisorDialog) -> Dict[str, Any]:
        """Kişisel marka değerlendirmesi."""
        return {
            "text": "🎯 *Kişisel Marka Değerlendirmesi*\n\n"
                   "📈 Marka Gücü: 7/10\n\n"
                   "Ayırt Edici Özellikler:\n"
                   "• Veri yönetimi uzmanı\n"
                   "• Yoğun yazma ve paylaşım\n"
                   "• İnsan-odaklı liderlik tarzı\n\n"
                   "🎯 Odaklanacak Alanlar:\n"
                   "• Düşünce liderliği: Endüstri araştırması yayınla\n"
                   "• Kişisel hikayeler: Başarısızlıktan dersleri paylaş\n"
                   "• Ağ Oluşturma: İlgili kişilerle etkileşime gir",
            "action": "brand_assessment_complete"
        }

    def _social_media_coach_ask_clarification(self) -> Dict[str, Any]:
        """Sosyal medya açıklaması iste."""
        return {
            "text": "🤔 Anlamadığım bir şey var.\n\n"
                   "Lütfen dene:\n"
                   "• Platform seç: `LinkedIn`, `Instagram`, `Twitter`\n"
                   "• Aksiyonu belirt: `audit`, `strateji`, `marka`",
            "action": "waiting_clarification"
        }

    # --- Kişisel Asistan Dialog ------------------------------------------

    def _handle_personal_assistant_input(self, dialog: AdvisorDialog, user_input: str) -> Dict[str, Any]:
        """Kişisel Asistan için input işle."""
        user_input_lower = user_input.lower()

        if len(dialog.conversation_history) <= 1:
            return self._personal_assistant_initial_menu()

        if any(keyword in user_input_lower for keyword in ["özet", "summary", "bugün", "today"]):
            return self._personal_assistant_daily_briefing()

        if any(keyword in user_input_lower for keyword in ["acil", "urgent", "görev", "task", "todo"]):
            return self._personal_assistant_priority_tasks()

        if any(keyword in user_input_lower for keyword in ["hedef", "goal", "target", "objective"]):
            return self._personal_assistant_goal_tracking()

        if any(keyword in user_input_lower for keyword in ["fırsat", "opportunity", "fikir", "idea"]):
            return self._personal_assistant_opportunities()

        if any(keyword in user_input_lower for keyword in ["akşam", "evening", "gün sonu", "eod"]):
            return self._personal_assistant_evening_summary()

        return self._personal_assistant_ask_clarification()

    def _personal_assistant_initial_menu(self) -> Dict[str, Any]:
        """Kişisel Asistan başlangıç menüsü."""
        return {
            "text": "👤 *Kişisel Asistan* burada!\n\n"
                   "Ne yapmak ister?\n\n"
                   "1️⃣ *Bugünün Özeti* — Morning briefing\n"
                   "2️⃣ *Acil Görevler* — Priority tasks\n"
                   "3️⃣ *Hedefler* — Goal tracking\n"
                   "4️⃣ *Fırsatlar* — Opportunities\n"
                   "5️⃣ *Akşam Özeti* — Evening summary\n\n"
                   "_Seç: `1`, `2`, `3`, `4` veya `5`_",
            "action": "waiting_option_selection"
        }

    def _personal_assistant_daily_briefing(self) -> Dict[str, Any]:
        """Günlük briefing."""
        return {
            "text": "🌅 *Bugünün Özeti*\n\n"
                   "**Hava:** 24°C, Güneşli\n\n"
                   "**Takvim:**\n"
                   "09:00 — Veri analizi toplantısı\n"
                   "11:30 — 1:1 review\n"
                   "14:00 — İnovasyon çalışması\n\n"
                   "**Mailler:** 12 yeni (3 acil)\n"
                   "**Slack:** 45 yeni mesaj\n\n"
                   "**Bugünün Hedefi:**\n"
                   "✓ Q4 stratejisini bitir\n"
                   "⧗ Takımla feedback al\n"
                   "• Blog yazısını iki 2. taslağa al",
            "action": "briefing_complete"
        }

    def _personal_assistant_priority_tasks(self) -> Dict[str, Any]:
        """Acil görevler."""
        return {
            "text": "🚨 *Acil Görevler (Bugün)*\n\n"
                   "**KIRMIZI (Hemen):**\n"
                   "1. Müşteri raporuna cevap ver (deadline: 14:00)\n"
                   "2. Bütçe incelemesini onayla\n\n"
                   "**ORANGE (Bugün):**\n"
                   "3. Pazarlama ekibi ile slaytı bitir\n"
                   "4. İnsan kaynakları özlü CV'yi gönder\n\n"
                   "**SARI (Yarın):**\n"
                   "5. LinkedIn post hazırla\n"
                   "6. Teknoloji araştırmasını bitir\n\n"
                   "💡 *İpucu:* İlk üçüne 2 saat ayır, kalan konuları taşı.",
            "action": "tasks_complete"
        }

    def _personal_assistant_goal_tracking(self) -> Dict[str, Any]:
        """Hedef takibi."""
        return {
            "text": "🎯 *Hedef Takibi (Aylık)*\n\n"
                   "**Kariyer:**\n"
                   "• AI Mastery kursu tamamla — 60% ✓\n"
                   "• 10 blog yazısı yayınla — 4/10 ✓\n"
                   "• 20 yeni bağlantı ekle (LinkedIn) — 14/20 ✓\n\n"
                   "**Kişisel:**\n"
                   "• 12 kitap oku — 6/12 ✓\n"
                   "• Meditasyon: 21 gün — 18/21 ✓\n"
                   "• Sağlık kontrolleri — Tamamlandı ✓\n\n"
                   "📊 *Genel ilerleme:* 72% (çok iyi gidiyorsun!)",
            "action": "tracking_complete"
        }

    def _personal_assistant_opportunities(self) -> Dict[str, Any]:
        """Fırsatlar."""
        return {
            "text": "✨ *Yeni Fırsatlar*\n\n"
                   "📢 **Konuşma Davet:**\n"
                   "• AI Innovation Konferansı (Oct 15)\n"
                   "• Açık çağrı: Veri yönetimi Panelistleri\n\n"
                   "💼 **Proje Fırsatları:**\n"
                   "• Yeni startup incubation ağı\n"
                   "• Endüstri araştırma ortaklığı\n\n"
                   "👥 **Ağ İfşaat:**\n"
                   "• 3 müdür ortamında mümkün\n"
                   "• 2 danışma talepleri\n\n"
                   "💬 İlgilendiğin var mı? Detay iste!",
            "action": "opportunities_complete"
        }

    def _personal_assistant_evening_summary(self) -> Dict[str, Any]:
        """Akşam özeti."""
        return {
            "text": "🌆 *Akşam Özeti*\n\n"
                   "**Bugün Neler Başardın:**\n"
                   "✅ Q4 stratejisini tamamladın\n"
                   "✅ 3 acil görev bitirdim\n"
                   "✅ İnovasyon toplantısı verimli oldu\n\n"
                   "**Yarın Hazırlık:**\n"
                   "📝 11:30'de 1:1 review\n"
                   "📝 Müşteri görüşme (14:00)\n"
                   "📝 Blog yazısı taslağını bitir\n\n"
                   "🌙 İyi geceler! Yarın daha güzel bir gün olacak.",
            "action": "summary_complete"
        }

    def _personal_assistant_ask_clarification(self) -> Dict[str, Any]:
        """Kişisel asistan açıklaması iste."""
        return {
            "text": "🤔 Anlamadığım bir şey var.\n\n"
                   "Lütfen dene:\n"
                   "• `özet` — Bugünün özeti\n"
                   "• `acil` — Acil görevler\n"
                   "• `hedef` — Hedef takibi\n"
                   "• `fırsat` — Yeni fırsatlar\n"
                   "• `akşam` — Akşam özeti",
            "action": "waiting_clarification"
        }

    def _invalid_selection_message(self) -> Dict[str, Any]:
        """Geçersiz seçim mesajı."""
        return {
            "text": "❌ Seçimi anlamadım.\n\n"
                   "Lütfen `1`, `2` veya `3` yaz.\n\n"
                   "1 = Veri Analisti\n"
                   "2 = Sosyal Medya Koçu\n"
                   "3 = Kişisel Asistan",
            "blocks": []
        }

    def _format_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Yanıtı Slack formatına dönüştür."""
        return {
            "type": "message",
            "text": response.get("text", ""),
            "blocks": response.get("blocks", []),
            "action": response.get("action"),
            "download_link": response.get("download_link"),
        }


def create_advisor_menu_blocks() -> List[Dict[str, Any]]:
    """Danışman seçim Block Kit oluştur."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Hangi danışmanla çalışmak istiyorsun?*"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Veri Analisti"},
                    "value": "data_analyst",
                    "action_id": "advisor_select_data_analyst"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Sosyal Medya Koçu"},
                    "value": "social_media_coach",
                    "action_id": "advisor_select_social_media_coach"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Kişisel Asistan"},
                    "value": "personal_assistant",
                    "action_id": "advisor_select_personal_assistant"
                }
            ]
        }
    ]


__all__ = [
    "AdvisorType",
    "DialogState",
    "Message",
    "AdvisorDialog",
    "AdvisorDialogManager",
    "AdvisorDialogFlow",
    "create_advisor_menu_blocks",
]
