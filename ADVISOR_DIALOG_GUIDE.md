# Danışman Dialog Sistemi (Advisor Dialog System)

## Genel Bakış

Interactive Slack dialog sistemi, kullanıcıların üç ana danışmanla DM yoluyla etkileşim kurmasını sağlar:

1. **Veri Analisti** (Data Analyst) — Veri yükleme, analiz, rapor oluşturma
2. **Sosyal Medya İmaj Koçu** (Social Media Coach) — Platform seçme, profil analizi, content stratejisi
3. **Kişisel Asistan** (Personal Assistant) — Günlük planlama, görev takibi, hedefler

## Mimari

### Dosya Yapısı

```
src/ai_assistant/chat/
├── advisor_dialog.py          # Ana dialog sistemi (420+ satır)
├── direct_messaging.py        # DM yönlendirmesi (güncellenmiş)
└── [diğer modüller]

tests/
└── test_advisor_dialog.py     # 27 test (tümü geçti)

.assistant_state/
├── data_analyst_dialog.json           # Dialog durumu (otomatik)
├── social_media_coach_dialog.json     # Dialog durumu (otomatik)
└── personal_assistant_dialog.json     # Dialog durumu (otomatik)
```

### Temel Bileşenler

#### 1. AdvisorDialog (Dataclass)

Bir dialog'un tüm durumunu tutar:

```python
@dataclass
class AdvisorDialog:
    user_id: str                              # Slack user ID
    advisor_key: str                          # "data_analyst" vb.
    conversation_history: List[Message]       # Konuşma geçmişi
    current_state: str                        # "menu", "waiting_input", "processing", "ready"
    context: Dict[str, Any]                   # Önceki etkileşimler
    last_interaction: str                     # ISO timestamp
    temporary_data: Dict[str, Any]            # İşlem sırasında veri
    tags: List[str]                           # Kategorilendirme
```

#### 2. AdvisorDialogManager

Dialog durumunun diskte tutulması:

```python
manager = AdvisorDialogManager()

# Yeni dialog oluştur
dialog = manager.get_or_create_dialog("data_analyst", "U12345")

# Kaydet
manager.save_dialog(dialog)

# Yükle
dialog = manager.get_dialog("data_analyst", "U12345")

# Temizle
manager.clear_dialog("data_analyst", "U12345")
```

#### 3. AdvisorDialogFlow

Multi-turn konuşma mantığı:

```python
flow = AdvisorDialogFlow()

# Menüyü göster
menu = flow.show_advisor_menu("U12345")

# Danışman seçimi
advisor_key, response = flow.handle_advisor_selection("U12345", "1")

# Input işle
response = flow.handle_advisor_input(advisor_key, "U12345", "CSV yükle")
```

## Dialog Durumları (State Machine)

```
                    ┌──────────────┐
                    │   MENU       │
                    │ (Advisor     │
                    │  seçimi)     │
                    └──────┬───────┘
                           │ (1/2/3)
                    ┌──────▼───────┐
                    │WAITING_INPUT │
                    │ (Girdi       │
                    │  bekleniyor) │
                    └──────┬───────┘
                           │ (user input)
                    ┌──────▼───────┐
                    │PROCESSING    │
                    │ (İşlem       │
                    │  yapılıyor)  │
                    └──────┬───────┘
                           │ (done)
                    ┌──────▼───────┐
                    │READY         │
                    │ (Sonuç       │
                    │  hazır)      │
                    └──────────────┘
```

## Danışman Akışları

### 1. Veri Analisti (Data Analyst)

```
Kullanıcı: "1" (Veri Analisti seç)
Bot: "Ne analiz etmek istiyorsun?"
    → Veri yükle (CSV, JSON, Excel, paste)

Kullanıcı: "CSV dosyası yüklüyorum"
Bot: "Başarıyla CSV algılandı. Ne analiz etmek istiyorsun?"
    → Trend? Korelasyon? Özet?

Kullanıcı: "trend"
Bot: "Trend analizi yapılıyor... Hangi format?"
    → Excel? Dashboard? Rapor? CSV?

Kullanıcı: "rapor"
Bot: [Analiz raporu + İndirme linki]
```

**Özellikler:**
- Dosya türü otomatik algılama (CSV, JSON, Excel, Text)
- Analiz türleri: Trend, Korelasyon, Özet
- Çıktı formatları: Excel, Dashboard, Rapor, CSV
- Örnek rapor oluşturma

### 2. Sosyal Medya İmaj Koçu (Social Media Coach)

```
Kullanıcı: "2" (Sosyal Medya Koçu seç)
Bot: "Hangi platform? LinkedIn, Instagram, Twitter?"

Kullanıcı: "LinkedIn"
Bot: "Ne yapmak istiyorsun?"
    → Profil Analizi
    → Content Stratejisi
    → Kişisel Marka

Kullanıcı: "audit"
Bot: [Profil denetimi + Öneriler]
```

**Özellikler:**
- Platform seçimi: LinkedIn, Instagram, Twitter
- Profil denetimi: Güçlü yönler + İyileştirmeler
- Content stratejisi: Haftalık plan
- Kişisel marka: Brand assessment

### 3. Kişisel Asistan (Personal Assistant)

```
Kullanıcı: "3" (Kişisel Asistan seç)
Bot: "Ne yapmak ister?"
    1. Bugünün Özeti (Morning briefing)
    2. Acil Görevler (Priority tasks)
    3. Hedefler (Goal tracking)
    4. Fırsatlar (Opportunities)
    5. Akşam Özeti (Evening summary)

Kullanıcı: "özet"
Bot: [Günlük briefing + Takvim + Mailler + Slack]
```

**Özellikler:**
- Günlük briefing: Hava + Takvim + Mailler
- Acil görevler: Kırmızı, Orange, Sarı seviyeler
- Hedef takibi: Aylık ilerleme
- Fırsatlar: Konuşma davet, Proje fırsatları
- Akşam özeti: Başarılar + Yarın hazırlık

## Entegrasyon (Integration)

### direct_messaging.py ile

```python
# direct_messaging.py içinde

async def route_to_advisor(self, message: DirectMessage):
    """Dialog sistemi etkinse, onu kullan."""
    
    if self.dialog_enabled and self.dialog_flow:
        return await self._route_with_dialog(message)
    
    # Fallback: eski sistem
```

### Env Değişkenleri

```bash
# Dialog sistemi aktif mi? (varsayılan: true)
ADVISOR_DIALOG_ENABLED=true

# Bildirim yöntemi: push, email, sms (varsayılan: push)
SLACK_NOTIFICATION_METHOD=push

# DM timeout (saniye, varsayılan: 30)
DIRECT_MESSAGE_TIMEOUT=30
```

## API Kullanımı

### Dialog Oluşturma ve Yönetimi

```python
from src.ai_assistant.chat.advisor_dialog import (
    AdvisorDialogFlow,
    AdvisorType,
)

# Flow oluştur
flow = AdvisorDialogFlow()

# Menüyü göster
menu = flow.show_advisor_menu("U12345")
# Returns: {"type": "blocks", "blocks": [...]}

# Danışman seç
advisor_key, response = flow.handle_advisor_selection("U12345", "1")
# advisor_key: "data_analyst"
# response: {"text": "...", "action": "..."}

# Input işle
response = flow.handle_advisor_input("data_analyst", "U12345", "Veri yükle")
# response: {"type": "message", "text": "...", "action": "..."}
```

### Dialog Durumunu Yönetme

```python
from src.ai_assistant.chat.advisor_dialog import AdvisorDialogManager

manager = AdvisorDialogManager()

# Mevcut dialog'u yükle
dialog = manager.get_dialog("data_analyst", "U12345")
if dialog:
    print(f"Durum: {dialog.current_state}")
    print(f"Geçmiş: {len(dialog.conversation_history)} mesaj")

# Kalıcılık
manager.save_dialog(dialog)  # Diskte sakla
manager.clear_dialog("data_analyst", "U12345")  # Sil
```

## Veri Kalıcılığı (Persistence)

### Dosya Yapısı

`.assistant_state/data_analyst_dialog.json`:

```json
{
  "user_id": "U12345",
  "advisor_key": "data_analyst",
  "conversation_history": [
    {
      "role": "user",
      "content": "CSV yükle",
      "timestamp": "2026-08-04T12:00:00"
    },
    {
      "role": "assistant",
      "content": "Başarıyla CSV algılandı...",
      "timestamp": "2026-08-04T12:00:01"
    }
  ],
  "current_state": "waiting_input",
  "context": {
    "upload_type": "CSV",
    "analysis_type": "Trend"
  },
  "last_interaction": "2026-08-04T12:00:01",
  "temporary_data": {},
  "tags": ["urgent"]
}
```

## Testler

### Çalıştırma

```bash
# Tüm testleri çalıştır
python -m pytest tests/test_advisor_dialog.py -v

# Belirli test
python -m pytest tests/test_advisor_dialog.py::TestAdvisorDialogFlow -v

# Coverage
python -m pytest tests/test_advisor_dialog.py --cov=src/ai_assistant/chat/advisor_dialog
```

### Test Kapsamı

- **27 test** — Tümü geçiyor ✅
- Dialog oluşturma ve yönetimi
- Multi-turn konuşma
- State transitions
- Advisor routing
- Response formatting
- State persistence
- End-to-end workflows
- Concurrent user dialogs

## Örnek Kullanım Senaryoları

### Senaryo 1: Veri Analizi

```
User → Bot (DM): "Veriyi analiz etmek istiyorum"
Bot → Menu
User: "1"
Bot → "Veri Analisti seçildi. Veri yükle..."
User: "CSV dosyası"
Bot → "Başarıyla algılandı. Ne analiz?"
User: "trend"
Bot → "İşleniyor... Format?"
User: "rapor"
Bot → [Analiz raporu + İndirme linki]
```

### Senaryo 2: LinkedIn Profil Optimizasyonu

```
User → Bot (DM): "LinkedIn profilimi iyileştir"
Bot → Menu
User: "2"
Bot → "Sosyal Medya Koçu seçildi. Platform?"
User: "LinkedIn"
Bot → "Ne yapmak istiyorsun?"
User: "Profil analizi yap"
Bot → [Güçlü yönler + İyileştirme önerileri]
```

### Senaryo 3: Günlük Planlama

```
User → Bot (DM): "Bugünün planı"
Bot → Menu
User: "3"
Bot → "Kişisel Asistan seçildi. Ne istiyorsun?"
User: "Bugünün özeti"
Bot → [Morning briefing: Hava, Takvim, Mailler, Slack]
```

## Geliştirim Fırsatları

1. **LLM Entegrasyonu**
   - Claude API'sı ile advisor yanıtlarını zenginleştir
   - Bağlamı LLM'ye gönder, daha akıllı cevaplar al

2. **Real Data Integration**
   - Gerçek veri kaynakları (Google Drive, Sheets)
   - Gerçek Slack verisi (kullanıcı takvim, mailler)
   - LinkedIn API entegrasyonu

3. **Multi-language Support**
   - İngilizce, Türkçe, vb. diller

4. **Richer UI**
   - Block Kit buttons ve menus
   - Modal dialogs
   - Interactive message selections

5. **Analytics**
   - Hangi danışmanlar en çok kullanılıyor?
   - Kullanıcı engagement metrics
   - Common user flows

## Dosya Listesi

### Oluşturulan Dosyalar

- `/home/user/AI-Executive-Assistant/src/ai_assistant/chat/advisor_dialog.py` (420+ satır)
  - AdvisorDialog dataclass
  - AdvisorDialogManager (state persistence)
  - AdvisorDialogFlow (multi-turn logic)
  - 3 advisor-specific implementations

- `/home/user/AI-Executive-Assistant/src/ai_assistant/chat/direct_messaging.py` (güncellendi)
  - Dialog sistem entegrasyonu
  - _route_with_dialog() method
  - Menu selection handling

- `/home/user/AI-Executive-Assistant/tests/test_advisor_dialog.py` (27 test)
  - Dialog unit tests
  - Flow integration tests
  - State persistence tests
  - End-to-end tests
  - Concurrent user tests

### Otomatik Oluşturulan Dosyalar

- `.assistant_state/data_analyst_dialog.json`
- `.assistant_state/social_media_coach_dialog.json`
- `.assistant_state/personal_assistant_dialog.json`

## İletişim

Dialog sistemi, Slack Block Kit formatını destekler:

```python
response = {
    "type": "blocks",
    "blocks": [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "..."}
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {...}, "action_id": "..."}
            ]
        }
    ]
}
```

## Sonuç

Danışman Dialog Sistemi:
- ✅ Tam otomatik state yönetimi
- ✅ Multi-turn konuşma desteği
- ✅ 3 danışman (Veri, Sosyal Medya, Kişisel)
- ✅ 27 geçmiş test
- ✅ Türkçe interface
- ✅ Slack entegrasyonu
- ✅ Diskte kalıcılık

Ready to integrate! 🚀
