# Google OAuth 2.0 Setup - Gmail & Calendar Entegrasyonu

Bu rehber, AI Executive Assistant uygulamasını Google Gmail ve Calendar APIs ile entegre etmek için gerekli adımları içerir.

---

## Adım 1: Google Cloud Project Oluşturma

### 1.1 Google Cloud Console'a Erişim
1. [Google Cloud Console](https://console.cloud.google.com/) adresine gidin
2. Google hesabınızla oturum açın (veya hesap oluşturun)

### 1.2 Yeni Project Oluşturma
1. Console sayfasında, üst kısımda proje seçicisine tıklayın
2. "Yeni Proje" veya "New Project" seçeneğine tıklayın
3. Proje adı girin: `AI-Executive-Assistant`
4. (İsteğe bağlı) Kuruluşu seçin
5. "Oluştur" (Create) butonuna tıklayın
6. Proje oluşturulana kadar bekleyin (1-2 dakika)

### 1.3 Gmail API'yi Etkinleştirme
1. Sol tarafta "Arama" kutusuna `Gmail API` yazın
2. Arama sonuçlarında "Gmail API"ye tıklayın
3. "API'yi etkinleştir" (Enable API) butonuna tıklayın
4. API etkinleştirilene kadar bekleyin

### 1.4 Google Calendar API'yi Etkinleştirme
1. Sol tarafta "Arama" kutusuna `Google Calendar API` yazın
2. Arama sonuçlarında "Google Calendar API"ye tıklayın
3. "API'yi etkinleştir" (Enable API) butonuna tıklayın
4. API etkinleştirilene kadar bekleyin

### 1.5 Doğrulama Ekranını Yapılandırma
1. Sol menüden "OAuth izin ekranı" (OAuth consent screen) seçeneğine tıklayın
2. Ekran türü olarak "Dışsal" (External) seçeneğini seçin
3. "Oluştur" (Create) butonuna tıklayın
4. Formu doldurun:
   - **Uygulama adı**: AI Executive Assistant
   - **Kullanıcı destek e-postası**: Kendi e-posta adresiniz
   - **Geliştirici iletişim bilgileri**: Kendi e-posta adresiniz
5. "Kaydet ve Devam Et" (Save and Continue) butonuna tıklayın

### 1.6 Kapsamları Seçme
1. "Kapsamlar Ekle" (Add Scopes) butonuna tıklayın
2. Aşağıdaki kapsamları seçin:
   - `gmail.readonly` - Gmail mesajlarını okuma
   - `calendar.readonly` - Takvim etkinliklerini okuma
3. "Güncelle" (Update) butonuna tıklayın
4. "Kaydet ve Devam Et" (Save and Continue) butonuna tıklayın

---

## Adım 2: OAuth 2.0 Kimlik Bilgileri Oluşturma

### 2.1 OAuth Credentials Oluşturma
1. Sol menüden "Kimlik Bilgileri" (Credentials) seçeneğine tıklayın
2. "Kimlik Bilgisi Oluştur" (Create Credentials) butonuna tıklayın
3. "OAuth 2.0 İstemci Kimliği" (OAuth 2.0 Client ID) seçeneğini seçin
4. "Uygulama türü" (Application type) olarak "Masaüstü uygulaması" (Desktop application) seçin
5. İstemci adı girin: `AI Executive Assistant Desktop`
6. "Oluştur" (Create) butonuna tıklayın

### 2.2 Redirect URI Yapılandırması
1. Oluşturulan kimlik bilgileriyle karşılaşacaksınız
2. İstemci ID ve İstemci Parolasını not alın (kopyalayın)
3. Kimlik bilgisine tıklayarak düzenleyin
4. "Yetkili Yönlendirme URI'ları" (Authorized redirect URIs) bölümüne gidin
5. Aşağıdaki URI'yi ekleyin:
   ```
   http://localhost:8080/oauth/callback
   ```
6. "Kaydet" (Save) butonuna tıklayın

### 2.3 JSON Dosyasını İndirme
1. "Kimlik Bilgileri" (Credentials) sayfasında, oluşturduğunuz OAuth 2.0 istemcisine gidin
2. Sağ tarafta "İndir" (Download) ikonuna tıklayın
3. JSON dosyası bilgisayarınıza indirilecektir
4. Dosyayı güvenli bir yere kaydedin (daha sonra kullanılacak)

### 2.4 İstemci Bilgileri
İndirilen JSON dosyasından veya ekrandan aşağıdaki bilgileri not alın:
- **Client ID**: `your-client-id`
- **Client Secret**: `your-client-secret`
- **Redirect URI**: `http://localhost:8080/oauth/callback`

---

## Adım 3: AI Executive Assistant'da Kimlik Doğrulama Kurulumu

### 3.1 Ortam Değişkenlerini Yapılandırma
1. Proje kökünde `.env` dosyasını açın (veya oluşturun)
2. Aşağıdaki satırları ekleyin:
   ```env
   # Google OAuth Configuration
   GOOGLE_OAUTH_CLIENT_ID=your-client-id
   GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
   GOOGLE_OAUTH_CALLBACK_URL=http://localhost:8080/oauth/callback
   GOOGLE_OAUTH_SCOPES=gmail.readonly,calendar.readonly
   ```

3. Değerleri Google Cloud Console'dan elde ettiğiniz bilgilerle değiştirin

### 3.2 OAuth Setup CLI'yi Çalıştırma
1. Terminal/Komut İstemcisini açın
2. Proje dizinine gidin:
   ```bash
   cd /home/user/AI-Executive-Assistant
   ```

3. Setup scriptini çalıştırın:
   ```bash
   python -m src.ai_assistant.integrations.google_oauth_setup
   ```

### 3.3 Google Hesabınızla Oturum Açma
1. Setup scripti çalıştırıldığında, varsayılan tarayıcınız otomatik olarak açılacaktır
2. Google oturum açma ekranı görünecektir
3. Google hesabınızla oturum açın
4. İzin istemini onaylayın:
   - "AI Executive Assistant"ın Gmail mesajlarınıza erişmesine izin ver
   - "AI Executive Assistant"ın Takvim etkinliklerinize erişmesine izin ver
5. "İzin Ver" (Allow) butonuna tıklayın

### 3.4 Token Kaydı
1. Oturum açma başarılı olursa, **Refresh Token** otomatik olarak güvenli depolama alanına kaydedilecektir
2. Konsolda başarı mesajı göreceksiniz:
   ```
   ✓ Google OAuth setup başarılı!
   ✓ Refresh token kaydedildi
   ✓ User email: your-email@gmail.com
   ```

3. Tarayıcı sekme kapatılabilir

---

## Adım 4: Ajanları Etkinleştirme

### 4.1 Mail Analyst Ajanı
- **Amaç**: Günlük Gmail mesajlarını analiz etme
- **İşlevler**:
  - Yeni mesajları kategorize etme
  - Önemli mesajları vurgulama
  - Masaüstü özeti oluşturma
  - Spam/reklam filtreleme

- **Otomatik Etkinleştirme**: Google OAuth başarılı olduğunda
- **Çalışma Zamanı**: Her 30 dakikada bir (konfigüre edilebilir)

### 4.2 Day Planner Ajanı
- **Amaç**: Günlük Takvim analizi ve planlama önerileri
- **İşlevler**:
  - Günlük etkinlikleri ve sürüsü kontrol etme
  - Boş zaman slotlarını gösterme
  - Toplantı hazırlık önerileri
  - Gün sonu özeti

- **Otomatik Etkinleştirme**: Google OAuth başarılı olduğunda
- **Çalışma Zamanı**: Her sabah 08:00 ve saat başında (UTC)

### 4.3 Ajanları Kontrol Etme
Yapılandırma dosyasını kontrol edin: `/home/user/AI-Executive-Assistant/src/config/agents.json`

Etkinleştir/Devre Dışı Bırak:
```json
{
  "mail_analyst": {
    "enabled": true,
    "schedule": "0 */30 * * * *"  // Her 30 dakikada bir
  },
  "day_planner": {
    "enabled": true,
    "schedule": "0 0 8 * * *"  // Her gün 08:00'de
  }
}
```

---

## Adım 5: Test

### 5.1 Temel Test
Aşağıdaki komutu çalıştırarak Google OAuth bağlantısını test edin:

```bash
python -c "from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient; client = GoogleOAuthClient(); print(f'Email: {client.get_user_email()}')"
```

**Beklenen Sonuç**: Çıktıda Google hesabınızın e-posta adresi görünecektir
```
Email: your-email@gmail.com
```

### 5.2 Gmail API Test
```bash
python -c "
from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient
client = GoogleOAuthClient()
messages = client.get_gmail_messages(max_results=5)
print(f'Toplam mesaj sayısı (ilk 5): {len(messages)}')
for msg in messages:
    print(f'  - {msg[\"subject\"][:50]}...')
"
```

**Beklenen Sonuç**: Son 5 Gmail mesajınızın özeti görünecektir

### 5.3 Calendar API Test
```bash
python -c "
from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient
client = GoogleOAuthClient()
events = client.get_calendar_events(days=7)
print(f'Gelecek 7 günde {len(events)} etkinlik')
for event in events:
    print(f'  - {event[\"summary\"]}: {event[\"start\"]}')
"
```

**Beklenen Sonuç**: Gelecek 7 günde planlanan etkinlikler görünecektir

### 5.4 Ajanları Test Etme
```bash
# Mail Analyst Ajanını Çalıştırma
python -m src.ai_assistant.agents.mail_analyst

# Day Planner Ajanını Çalıştırma
python -m src.ai_assistant.agents.day_planner
```

---

## Adım 6: Troubleshooting

### Sorun: "Invalid credentials" (Geçersiz kimlik bilgileri)
**Çözüm**:
1. `.env` dosyasında Client ID ve Secret doğru mu kontrol edin
2. Google Cloud Console'dan değerleri yeniden kopyalayın
3. Dosyayı kaydedin ve uygulamayı yeniden başlatın

### Sorun: "Redirect URI mismatch"
**Çözüm**:
1. Google Cloud Console'da OAuth ayarlarına gidin
2. Redirect URI'nın `http://localhost:8080/oauth/callback` olduğunu kontrol edin
3. Eğer farklıysa, `.env` dosyasını buna göre güncelleyin

### Sorun: "Token expiration" (Token Süresi Dolmuş)
**Çözüm**: Sistem otomatik olarak Refresh Token kullanarak yeni Access Token oluşturur. Eğer hata devam ederse:

```bash
python -c "from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient; GoogleOAuthClient().refresh_access_token()"
```

### Sorun: "Insufficient permissions" (Yetersiz İzin)
**Çözüm**:
1. Google Cloud Console'da OAuth izin ekranını açın
2. Kapsamların `gmail.readonly` ve `calendar.readonly` içerdiğini kontrol edin
3. Setup scriptini yeniden çalıştırarak yeniden oturum açın

### Sorun: "Rate limit exceeded" (Oran Sınırı Aşıldı)
**Çözüm**:
1. API isteklerinin sayısını azaltın
2. İstekler arasına bekleme süresi ekleyin
3. Gmail API'yi [Google Cloud Console](https://console.cloud.google.com/apis/dashboard) üzerinden kontrol edin

### Sorun: "Failed to start local server" (Yerel Sunucu Başlatılamadı)
**Çözüm**:
1. Port 8080'in kullanılabilir olduğunu kontrol edin:
   ```bash
   lsof -i :8080  # Linux/Mac
   netstat -ano | findstr :8080  # Windows
   ```
2. Başka bir port kullanın:
   ```env
   GOOGLE_OAUTH_CALLBACK_URL=http://localhost:8081/oauth/callback
   ```
3. Google Cloud Console'da yeni Redirect URI'yi ekleyin

### Sorun: Günlük Hatalar ve Debugging
Ayrıntılı günlükleri görmek için:
```bash
python -m src.ai_assistant.integrations.google_oauth_setup --debug
```

Günlükleri kontrol edin:
```bash
tail -f logs/oauth.log
```

---

## Adım 7: Güvenlik Notları

### 7.1 Refresh Token Güvenliği
- **Hiçbir Durumda Paylaşmayın**: Refresh Token'ı kimseyle paylaşmayın
- **Güvenli Depolama**: Token `.env` veya `secrets.json` gibi güvenli dosyalarda tutulur
- **Dosya İzinleri**: Gizli dosyaların İzinlerini 600 olarak ayarlayın:
  ```bash
  chmod 600 .env
  chmod 600 secrets.json
  ```

### 7.2 Access Token Caching
- Access Token'lar geçici olarak bellekte (cache) saklanır
- Otomatik olarak süresi dolduktan sonra yenilenir
- Production ortamında, token storage şifrelenmeli

### 7.3 HTTPS Kullanımı
- **Development**: `http://localhost:8080` kullanılabilir
- **Production**: Mutlaka HTTPS kullanın: `https://your-domain.com/oauth/callback`
- SSL/TLS sertifikası yapılandırın

### 7.4 State Parameter Doğrulaması
- CSRF saldırılarını önlemek için State parametresi kullanılır
- Sistem otomatik olarak State'i doğrular
- Kendi OAuth implementasyonunda State kullanın:
  ```python
  state = secrets.token_urlsafe(32)
  # State'i session'da saklayın ve sonra doğrulayın
  ```

### 7.5 İzin Kapsamlarını Sınırlama
- Sadece gerekli izinleri isteyiniz:
  - `gmail.readonly` - Yalnızca okuma
  - `calendar.readonly` - Yalnızca okuma
- Değişiklik izinleri (`modify`, `delete`) istemeyiniz

### 7.6 Güvenlik Denetim Kontrol Listesi
- [ ] Client Secret hiçbir yerde kod içinde hardcoded değil
- [ ] `.env` dosyası `.gitignore` içinde
- [ ] Secrets dosyaları version control'e commit edilmedi
- [ ] HTTPS production ortamında etkinleştirildi
- [ ] State parameter CSRF koruması var
- [ ] Access Token'lar SSL/TLS üzerinde iletiliyor

---

## Adım 8: CLI Referansı

### Setup İşlemleri

#### Interactive Setup
```bash
python -m src.ai_assistant.integrations.google_oauth_setup
```
**Açıklama**: Tarayıcı üzerinden Google hesabınızla oturum açma ve token alma
**Çıktı**: Başarılı olursa "✓ Google OAuth setup başarılı!" mesajı

#### Setup with Debug Mode
```bash
python -m src.ai_assistant.integrations.google_oauth_setup --debug
```
**Açıklama**: Ayrıntılı hata ayıklama bilgileriyle setup çalıştırma

---

### Token Yönetimi

#### Access Token'ı Yenile
```bash
python -c "from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient; GoogleOAuthClient().refresh_access_token()"
```
**Açıklama**: Refresh Token kullanarak yeni Access Token oluşturma

#### Mevcut Token Bilgisini Göster
```bash
python -c "from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient; client = GoogleOAuthClient(); print(client.get_token_info())"
```
**Açıklama**: Token bilgisini ve süresi dolma zamanını göster

#### Token'ı Temizle (Logout)
```bash
python -c "from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient; GoogleOAuthClient().logout()"
```
**Açıklama**: Kaydedilmiş token'ı sil ve logout yap

---

### Email İşlemleri

#### E-posta Adresini Al
```bash
python -c "from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient; print(GoogleOAuthClient().get_user_email())"
```
**Çıktı**: `your-email@gmail.com`

#### Son Mesajları Al
```bash
python -c "
from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient
client = GoogleOAuthClient()
messages = client.get_gmail_messages(max_results=10)
for msg in messages:
    print(f'{msg[\"from\"]}: {msg[\"subject\"]}')
"
```
**Açıklama**: Son 10 Gmail mesajını listele

#### Belirli Etiketle Mesaj Al
```bash
python -c "
from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient
client = GoogleOAuthClient()
messages = client.get_gmail_messages(label='INBOX', max_results=5)
print(f'{len(messages)} mesaj bulundu')
"
```
**Açıklama**: Sadece INBOX etiketli mesajları getir

---

### Takvim İşlemleri

#### Gelecek Etkinlikleri Al
```bash
python -c "
from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient
client = GoogleOAuthClient()
events = client.get_calendar_events(days=7)
for event in events:
    print(f'{event[\"start\"]}: {event[\"summary\"]}')
"
```
**Açıklama**: Gelecek 7 günde planlanan etkinlikleri listele

#### Bugünün Etkinlikleri
```bash
python -c "
from src.ai_assistant.integrations.google_oauth import GoogleOAuthClient
from datetime import datetime, timedelta
client = GoogleOAuthClient()
start = datetime.now().isoformat()
end = (datetime.now() + timedelta(days=1)).isoformat()
events = client.get_calendar_events(start_time=start, end_time=end)
print(f'Bugün {len(events)} etkinlik var')
"
```
**Açıklama**: Bugün için planlanan tüm etkinlikleri göster

---

### Ajanlara Başlama

#### Mail Analyst Ajanı
```bash
python -m src.ai_assistant.agents.mail_analyst
```
**Açıklama**: Gmail mesajlarını analiz etme ajanını çalıştır
**İşlem**: Günlük email özeti oluştur, kategorize et, önemli mesajları vurgula

#### Day Planner Ajanı
```bash
python -m src.ai_assistant.agents.day_planner
```
**Açıklama**: Takvim analizi ve planlama ajanını çalıştır
**İşlem**: Günlük etkinlikleri analiz et, boş zamanları göster, önerilerde bulun

#### Tüm Ajanları Başlat
```bash
python -m src.ai_assistant.agents.run_all
```
**Açıklama**: Tüm etkinleştirilmiş ajanları sırayla çalıştır

---

### Sistem Denetimi

#### OAuth Bağlantı Durumu
```bash
python -m src.ai_assistant.integrations.google_oauth --status
```
**Çıktı**:
```
✓ Google OAuth Bağlı
  Email: your-email@gmail.com
  Scope: gmail.readonly, calendar.readonly
  Token Süresi: 2024-12-31 18:45:00
```

#### Tüm Entegrasyonlar
```bash
python -m src.ai_assistant.check_integrations
```
**Çıktı**:
```
✓ Google OAuth: Bağlı
✓ Gmail API: Erişilebilir
✓ Calendar API: Erişilebilir
✗ Slack: Yapılandırılmamış
```

---

## Adım 9: Sonrası - İleri Yapılandırma

### 9.1 Ajanlara Özel Yapılandırma
`/home/user/AI-Executive-Assistant/src/config/agents.json` dosyasını düzenleyin:

```json
{
  "mail_analyst": {
    "enabled": true,
    "schedule": "0 */30 * * * *",
    "max_emails": 50,
    "ignore_labels": ["TRASH", "SPAM"],
    "priority_keywords": ["URGENT", "ASAP", "IMMEDIATE"]
  },
  "day_planner": {
    "enabled": true,
    "schedule": "0 0 8 * * *",
    "time_zone": "Europe/Istanbul",
    "working_hours": "09:00-18:00"
  }
}
```

### 9.2 Bildirim Ayarları
Mail Analyst veya Day Planner tarafından bildirim göndermek için:

```json
{
  "notifications": {
    "enabled": true,
    "channels": ["console", "email", "slack"],
    "urgent_only": false
  }
}
```

### 9.3 Veri Saklama
Günlük email ve takvim geçmişini nasıl saklanacağı:

```json
{
  "storage": {
    "type": "sqlite",  // sqlite, postgresql, mongodb
    "retention_days": 90,
    "encryption": true
  }
}
```

---

## Destek ve İletişim

Sorunla karşılaşırsanız:

1. **GitHub Issues**: [AI Executive Assistant Issues](https://github.com/your-repo/issues)
2. **Documentation**: [Tam Dokümantasyon](/docs)
3. **Email Destek**: Proje yöneticisine başvurun
4. **Debug Mode**: `--debug` flag'ı kullanarak hata ayıklama yapın

---

**Son Güncelleme**: 2024
**Versiyon**: 1.0
**Durum**: Üretim Hazır
