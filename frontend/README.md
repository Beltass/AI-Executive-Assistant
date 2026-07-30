# Ajan Panosu (frontend)

Danışman ekibinin **günlük raporları** ve **canlı izleme panosu**. Saf statik
bir site: düz HTML + CSS + vanilla JS. Derleme adımı yok, npm bağımlılığı yok,
CDN yok — dosyaları herhangi bir statik sunucuya koymak yeterli.

```
frontend/
├── index.html    # sayfa iskeleti (pano + okuma görünümü + arşiv)
├── styles.css    # koyu/açık tema, mobil öncelikli düzen, okuma tipografisi
├── markdown.js   # küçük ve GÜVENLİ markdown → HTML dönüştürücü
├── app.js        # veriyi çeker, çizer, hash router'ı yönetir
├── status.json   # çalıştırma durumu — her brifingde yeniden üretilir
└── reports/      # ajan başına rapor belgeleri
    ├── index.json                  # arşiv (son 30 gün)
    └── 2026-07-31/
        ├── index.json              # o günün kart listesi
        └── leadership_coach.json   # tek bir ajanın tam raporu
```

## 📄 Raporlar (okuma görünümü)

Brifing artık Slack'te tek bir uzun mesaj değil. Her ajanın bölümü **kendi
belgesi** olarak yazılır ve pano onu telefonda rahat okunacak bir sayfa gibi
dizer: ölçülü satır uzunluğu, net başlık hiyerarşisi, ferah satır aralığı,
yatay kaydırma yok.

Adresler (hash router, tek sayfa):

```
#/                            pano
#/raporlar                    arşiv (son 30 gün)
#/raporlar/2026-07-31         o günün raporları
#/rapor/2026-07-31/ajan_id    tek rapor
```

Slack'e giden mesaj bunun **indeksidir**: tarih başlığı, çalıştırma özeti ve
ajan başına tek satır (emoji + ad + "öne çıkan bulgu" + `📄 Tam rapor` bağlantısı).

> **Gizlilik:** pano herkese açıktır. Kişisel veri içerebilecek bölümler
> (Gmail/Takvim brifingi) `reports/` altına **hiç** yazılmaz; onlar yalnızca
> Slack mesajının içinde gider.

### Markdown neden kendi dosyasında?

`markdown.js` küçük ve kasıtlı olarak sınırlı bir dönüştürücüdür. Kaynağı
**önce HTML olarak kaçırır (escape)**, sonra yalnızca desteklenen az sayıda
yapıyı işaretlemeye çevirir; bağlantılar `http(s)`/`mailto` ile sınırlıdır.
Böylece model üretimi bir metin sayfaya HTML enjekte edemez. CDN'den kütüphane
çekilmez — DOM'a dokunmadığı için `node` altında test edilir
(`tests/test_frontend_markdown.py`).

## Ne gösterir? (pano)

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

`.github/workflows/pages.yml`, `frontend/` klasörünü Pages'e dağıtır. **İki**
tetikleyicisi var ve ikincisi bir hata düzeltmesidir:

1. `push` — `main`'e `frontend/**` altına yapılan normal (insan) değişiklikler.
2. `workflow_run` — `Daily Briefing` iş akışı **bittiğinde**.

İkincisi olmadan pano bayat kalıyordu: brifing `status.json` ve `reports/`
dosyalarını `main`'e geri commit'liyor, ama (a) commit mesajındaki `[skip ci]`
tüm iş akışlarını atlatıyor, (b) daha temelde `GITHUB_TOKEN` ile yapılan bir
push GitHub'da **hiçbir zaman** yeni bir iş akışı tetiklemiyor. Yani depodaki
dosya tazeyken yayındaki site eski derlemeyi servis ediyordu. `workflow_run`
commit'i değil, iş akışının kendisini dinlediği için bu zinciri kapatır.

Döngü riski yok: `pages.yml` yalnızca okur ve yayınlar, hiçbir şey push
etmez; `daily-briefing.yml` ise sadece `schedule` ve `workflow_dispatch` ile
tetiklenir, `push`/`workflow_run` ile değil.

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
# depo kökünde: örnek rapor belgeleri üret (ağ/model gerektirmez)
python scripts/seed_dashboard.py

# ya da gerçek bir çalıştırma (boş .env ile ajanlar "skipped" olur)
python -m ai_assistant.notifiers.slack_notifier

# panoyu aç
python -m http.server 8000 --directory frontend
# → http://localhost:8000
```

`file://` ile açarsan tarayıcı `fetch` isteğini engelleyebilir; küçük bir yerel
sunucu kullanmak en kolayı.
