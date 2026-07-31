# Ajan Panosu (frontend)

Danışman ekibinin **günlük raporları** ve **canlı izleme panosu**. Saf statik
bir site: düz HTML + CSS + vanilla JS. Derleme adımı yok, npm bağımlılığı yok,
CDN yok — dosyaları herhangi bir statik sunucuya koymak yeterli.

```
frontend/
├── index.html    # 5 sekmelik iskelet + okuma görünümü + arşiv
├── styles.css    # tasarım sistemi: tokenlar, koyu/açık tema, bileşenler
├── charts.js     # bağımlılıksız satır içi SVG grafikler
├── markdown.js   # küçük ve GÜVENLİ markdown → HTML dönüştürücü
├── app.js        # veriyi çeker, sekmeleri çizer, hash router'ı yönetir
├── status.json   # çalıştırma durumu — her brifingde yeniden üretilir
├── metrics.json  # token/gecikme geçmişi (son 60 çalıştırma)
├── health.json   # teknik nöbetçinin sağlık raporu (saat başı)
└── reports/      # ajan başına rapor belgeleri
    ├── index.json                  # arşiv (son 30 gün)
    └── 2026-07-31/
        ├── index.json              # o günün kart listesi
        └── leadership_coach.json   # tek bir ajanın tam raporu
```

## Sekmeler

| Sekme | Ne gösterir |
| ----- | ----------- |
| 🖥️ **Sistem & Ajanlar** | Genel sağlık başlığı (son çalıştırma, süre, mod, Slack teslimi, başarı oranı, sonraki saatler), teknik nöbetçinin bulguları, ajan kartları + kategori filtresi, çalıştırma geçmişi grafiği |
| 📄 **İçerik & Raporlar** | Bugünün rapor kartları (özet + okuma süresi), okuma görünümü, tarih arşivi ve istemci tarafı metin araması |
| 📊 **Performans & Token** | Çalıştırma başına token, girdi/çıktı/düşünme dağılımı, ajan başına **tahmini token payı ↔ çıktı payı** karşılaştırması, gecikme trendi ve **💡 Optimizasyon Önerileri** |
| ✅ **İşler & Takip** | Hesap Sorucu Koç'un gün serisi ve bugünün görev listesi |
| 💡 **Öneriler & Fikirler** | İnovasyon & Proje Geliştirme Ajanı'nın proje önerileri |

Aktif sekme **URL hash'inde** tutulur (`#/sistem`, `#/performans`, …), yani her
sekme paylaşılabilir, yer imlenebilir ve geri tuşu çalışır.

## 📄 Raporlar (okuma görünümü)

Brifing artık Slack'te tek bir uzun mesaj değil. Her ajanın bölümü **kendi
belgesi** olarak yazılır ve pano onu telefonda rahat okunacak bir sayfa gibi
dizer: ölçülü satır uzunluğu, net başlık hiyerarşisi, ferah satır aralığı,
yatay kaydırma yok.

Adresler (hash router, tek sayfa):

```
#/sistem                      🖥️ sistem & ajanlar (varsayılan)
#/icerik                      📄 içerik & raporlar
#/performans                  📊 performans & token
#/isler                       ✅ işler & takip
#/fikirler                    💡 öneriler & fikirler
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

## Tasarım ve erişilebilirlik

- **Mobil öncelikli.** Her düzen tek sütun başlar, kırılma noktalarında genişler.
- **Koyu tema varsayılan**, açık temaya geçiş `localStorage`'da saklanır ve ilk
  boyamadan önce uygulanır (tema titremesi yok).
- **Renk asla tek başına anlam taşımaz:** her durum bir ikon **ve** Türkçe
  etiketle gelir; iki ve üzeri serili her grafikte gösterge (legend) vardır ve
  her grafiğin bir **tablo görünümü** bulunur.
- **Klavye:** sekmeler ok tuşlarıyla gezilir, her etkileşimli öğede görünür
  odak halkası vardır, `prefers-reduced-motion` tüm geçişleri kapatır.
- **Grafik kuralları:** ince işaretler, yığılmış dilimler arasında 2px yüzey
  boşluğu (çerçeve değil), 1px düz ızgara çizgileri, tek eksen — asla çift eksen.

## Grafikler neden kendi dosyasında?

`charts.js` satır içi SVG üretir; hiçbir grafik kütüphanesi yoktur. DOM'a
`createElementNS` ile dokunduğu için `node` altında küçük bir DOM taklidiyle
test edilebilir (`tests/test_frontend_dashboard.py`) — geometri gözle değil
gerçekten çalıştırılarak doğrulanır.

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

# örnek token geçmişi (pano ilk yayında boş görünmesin diye; "örnek" damgalı)
python scripts/seed_metrics.py

# ya da gerçek bir çalıştırma (boş .env ile ajanlar "skipped" olur)
python -m ai_assistant.notifiers.slack_notifier

# panoyu aç
python -m http.server 8000 --directory frontend
# → http://localhost:8000
```

`file://` ile açarsan tarayıcı `fetch` isteğini engelleyebilir; küçük bir yerel
sunucu kullanmak en kolayı.
