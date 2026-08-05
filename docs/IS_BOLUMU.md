# İş Bölümü — Claude / ChatGPT

Bu depoda iki AI ajanı aynı anda ve **aynı dalda** (`claude/slack-session-91zqjj`) çalışıyor: Claude ve ChatGPT. Bu dosya bir **dosya-sahipliği sözleşmesidir**. Herhangi bir değişikliğe başlamadan önce bu dosyayı oku ve hangi alanın kime ait olduğunu doğrula.

## Sahiplik tablosu

| Alan | Sahip | Dosyalar |
| --- | --- | --- |
| Toplantı notları zinciri | Claude | `src/ai_assistant/advisors/meeting_notes.py`, `src/ai_assistant/advisors/_turkish_dates.py`, `src/ai_assistant/integrations/meeting_notes_poller.py` |
| Ortak LLM katmanı | Claude | `src/ai_assistant/integrations/llm.py` |
| Gmail entegrasyonu | Claude | `src/ai_assistant/integrations/gmail.py` |
| Toplantı notları testleri | Claude | `tests/test_meeting_notes.py` |
| Backend API | ChatGPT | `backend/` (tümü) |
| Frontend | ChatGPT | `frontend/` (tümü) |
| Deployment / infra | ChatGPT | deploy workflow'ları, container yapılandırması |
| Diğer danışmanlar | ChatGPT | `src/ai_assistant/advisors/` altındaki toplantı-notları dışındakiler (`linkedin_coach.py`, `market_intelligence.py` vb.) |

## Paylaşımlı dosyalar — dokunmadan önce haber ver

Aşağıdaki dosyalar iki tarafı da ilgilendirir. Değiştirmeden **önce** karşı tarafa haber ver:

- `pyproject.toml`
- `.github/workflows/ci.yml`
- `src/ai_assistant/integrations/slack_advisor_bridge.py`
- `src/ai_assistant/advisors/_llm_base.py`

Kurallar:

- **Tam-dosya yeniden yazımı YASAK.** Yalnızca hedefli (targeted) düzenleme yap; dosyanın tamamını baştan yazma.
- `slack_advisor_bridge.py` içindeki **public metod imzaları korunacak.** Claude bu metotları çağırıyor, değiştirmiyor; imza değişirse Claude tarafı kırılır.

## Çakışma önleme kuralları

1. Push öncesi **HER ZAMAN**: `git pull --rebase origin claude/slack-session-91zqjj`
2. **Küçük ve sık commit** — büyük toplu commit yok.
3. Commit mesajı alan öneki taşısın: `feat(meeting-notes):`, `feat(backend):`, `fix(frontend):`
4. Sahibi olmadığın bir dosyayı değiştirmen gerekiyorsa: commit mesajında gerekçeyi yaz ve mümkünse **ayrı bir commit** olarak at.
5. **Aynı fonksiyonda iki taraf birden çalışmayacak.**

## Mevcut durum (Claude tarafı)

**Tamamlanan:**

- Test altyapısı düzeltmesi
- Kaynak optimizasyonu (thinking budget, poller sıklığı, state kalıcılığı)
- Gerçek ses keşfi (audio discovery)
- Gemini ile multimodal transkripsiyon
- Türkçe tarih ayrıştırma
- Gerçek Slack deadline reminder (Block Kit)
- 64 davranış testi

**Sıradaki:**

- Temiz venv doğrulaması
- CI kırmızı-olabilirlik kanıtı (testlerin gerçekten kırılabildiğinin gösterilmesi)
- Uçtan uca gerçek koşu
- Thinking budget kalite karşılaştırması
