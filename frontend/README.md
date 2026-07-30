# Ajan Panosu (frontend)

Danışman ekibinin **canlı izleme panosu**. Saf statik bir site: düz HTML + CSS +
vanilla JS. Derleme adımı yok, npm bağımlılığı yok, CDN yok — dosyaları herhangi
bir statik sunucuya koymak yeterli.

```
frontend/
├── index.html    # sayfa iskeleti
├── styles.css    # koyu/açık tema, mobil öncelikli düzen
├── app.js        # status.json'u çeker ve çizer (60 sn'de bir otomatik yeniler)
└── status.json   # veri — her brifing çalıştırmasında yeniden üretilir
```

## Ne gösterir?

- **Özet şeridi:** toplam ajan sayısı, ✅ çalıştı / ⚠️ hata / ⏭️ atlandı sayıları,
  çalıştırma süresi ve Slack teslim rozeti.
- **Danışman kartları:** her ajan için Türkçe ad, durum rozeti, hata/atlanma
  nedeni, üretilen bölümün karakter sayısı ve kategori etiketi (kariyer, aile,
  sektör, kişisel gelişim, operasyon). Kategoriye göre filtrelenebilir.
- **Geçmiş:** son ~30 çalıştırmanın yığılmış çubuk grafiği ve son 10
  çalıştırmanın tablosu (zaman, sonuç, sayılar, süre, Slack).
- **Hesap sorucu koç paneli:** 🔥 güncel seri ve bugünün görev sayısı.
- **Çalıştırma motoru:** tek toplu model çağrısının kullanılıp kullanılmadığı,
  kaç bölüm ürettiği ve hangi modelin yanıtladığı.

Renk asla tek başına anlam taşımaz: her durum rengi bir ikon ve Türkçe etiketle
birlikte gelir, grafikteki "hata" dilimleri ayrıca çapraz dokuyla ayrışır ve
aynı veriler tablo olarak da bulunur.

## Veri nereden geliyor?

`status.json`'u `ai_assistant.status_report` üretir. Brifing (Slack teslimi
denendikten **sonra**) bu dosyayı yazar, `Daily Briefing` iş akışı da `main`'e
geri commit'ler. Böylece pano gerçek çalıştırmaları yansıtır: 10:00 İstanbul'da
**tam brifing**, 14:00 / 18:00 / 22:00'de yalnızca yeni bulguları getiren
**artımlı** çalıştırmalar. Artımlı bir çalıştırmada yeni bir şey yoksa Slack'e
mesaj gitmez ama `status.json` yine yazılır — pano "artımlı" rozetini, ajan
başına yeni bulgu sayısını ve "yeni bulgu yok" durumunu gösterir.

Yol `STATUS_REPORT_FILE` ile değiştirilebilir (varsayılan
`frontend/status.json`).

> **Gizlilik:** dosyada brifing METNİ asla yer almaz — yalnızca durum, neden ve
> karakter sayısı. Depo herkese açık olduğu için tüm neden metinleri API
> anahtarlarına karşı ayrıca temizlenir.

## Nasıl yayınlanıyor?

### 1. Vercel (birincil)

Depoya bağlı `ai-executive-assistant-uerc` projesinin kök dizini `frontend`
olarak ayarlı, yani Vercel bu klasörü ve buradaki `vercel.json`'u okur.

`vercel.json` yalnızca "burada derlenecek bir şey yok" der: framework yok,
build komutu yok, kurulum komutu yok, çıktı dizini bu klasörün kendisi. Böylece
projede kayıtlı bir framework/build ayarı varsa geçersiz kılınır ve dosyalar
olduğu gibi servis edilir. Depo kökündeki diğer Vercel projesi bu dosyayı hiç
görmez — kök dizini farklı olduğu için etkilenmez.

### 2. GitHub Pages (yedek)

`.github/workflows/pages.yml`, `main`'e her push'ta `frontend/` klasörünü
Pages'e dağıtır.

İş akışı Pages'i ilk çalıştırmada kendisi açmaya çalışır
(`configure-pages` → `enablement: true`). Bu yetkiyle yapılamazsa iş akışı
"Get Pages site failed" ile durur; o durumda **tek seferlik** olarak GitHub'da
→ **Settings → Pages → Source: GitHub Actions** seçilmesi yeterlidir.

Adres:

```
https://beltass.github.io/AI-Executive-Assistant/
```

## Yerelde çalıştırma

```bash
# depo kökünde: örnek veriyi üret (boş .env ile ajanlar "skipped" olur)
python -m ai_assistant.notifiers.slack_notifier

# panoyu aç
python -m http.server 8000 --directory frontend
# → http://localhost:8000
```

`file://` ile açarsan tarayıcı `fetch` isteğini engelleyebilir; küçük bir yerel
sunucu kullanmak en kolayı.
