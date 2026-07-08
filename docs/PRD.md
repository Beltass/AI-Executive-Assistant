# PRD — Product Requirements Document

**Ürün:** AI Executive Assistant
**Sahip/kullanıcı:** Burak Eltaş (eltas.burak@gmail.com)
**Durum:** Taslak — Faz 0
**Son güncelleme:** 2026-07-08

## 1. Vizyon

Gmail, Google Calendar ve zamanla Microsoft 365, Teams, Zoom, Slack,
Notion, LinkedIn gibi servislerle entegre çalışan; e-postaları, takvimi,
toplantıları ve iş başvurularını kullanıcı adına yönetebilen kişisel bir
yapay zekâ "chief of staff". Kullanıcı görevleri manuel yapmak yerine
asistana devreder, asistan gerektiğinde onay ister ve sonucu raporlar.

**Önemli kapsam notu:** "Kurumsal seviyede dokümantasyon" ifadesi
*dokümantasyonun kalitesine/yapısına* atıfta bulunur — ürünün kendisi
Faz 1-3 boyunca **tek kullanıcılı, kişisel** bir asistan olarak
tasarlanır (çoklu kiracı/SaaS değildir). Çoklu kullanıcı desteği
gündeme gelirse ayrı bir faz olarak ele alınacak ve mimaride köklü
değişiklik gerektirecektir; bugünden o karmaşıklığı eklemiyoruz.

## 2. Problem

Kullanıcı, e-posta triyajı, takvim koordinasyonu, toplantı takibi ve iş
başvurusu süreçlerini elle yönetiyor. Bu işler zaman alıyor, bağlam
değiştirmeyi (context switching) gerektiriyor ve tekrarlayan, düşük
katma değerli adımlar (özetleme, taslak hazırlama, takip kaydı)
içeriyor.

## 3. Hedef kullanıcı

Tek persona: proje sahibinin kendisi. Müşteri deneyimi/operasyon
yöneticisi profilinde, İstanbul merkezli, İngilizce ve Türkçe
çalışıyor, birden fazla servis (Gmail, Google Calendar, LinkedIn,
kariyer.net) kullanıyor. `Dashboard-Project/is-basvuru` becerisindeki
`profil.md` bu kullanıcının somut geçmiş/hedef verisini içerir ve bu
projede de tek doğruluk kaynağı olarak yeniden kullanılacaktır.

## 4. Hedefler (v1 / MVP)

1. Gmail gelen kutusunu özetleyip önceliklendirebilmek ve taslak yanıt
   üretebilmek (gönderim her zaman kullanıcı onayıyla).
2. Google Calendar üzerinde etkinlik oluşturma/düzenleme/çakışma
   tespiti yapabilmek.
3. Kullanıcı tercihlerini, tekrarlayan bağlamı (ör. hedef iş
   unvanları, iletişim tarzı) oturumlar arası hatırlayabilmek (Memory
   Agent).
4. `Dashboard-Project/is-basvuru` içindeki iş ilanı tarama ve başvuru
   materyali hazırlama akışını bu asistanın bir yeteneği olarak sunmak.
5. Tüm bunları tek bir sohbet arayüzünden (dashboard) yönetebilmek;
   Master Orchestrator kullanıcı isteğini doğru ajana yönlendirir.

## 5. Hedef olmayanlar (v1 kapsam dışı)

- Outlook/Microsoft 365, Teams, Zoom, Slack, Notion entegrasyonları
  (bkz. ROADMAP Faz 2-3).
- Sesli arayüz (Voice Agent), otonom tarayıcı ajanı (Browser Agent).
- Toplantı notu çıkarma (Meeting/Note Agent), günlük planlayıcı, ayrı
  bir Reminder/Analytics ajanı.
- Herhangi bir platforma **otomatik form gönderimi** (iş başvurusu,
  e-posta, takvim daveti dahil) — her zaman kullanıcı onayı şarttır.
  Bu kısıtlama `is-basvuru` becerisinden miras alınır ve tüm asistan
  için geçerlidir.
- Çoklu kullanıcı/SaaS altyapısı, faturalandırma, ekip yönetimi.
- Mobil uygulama (klasör iskeletinde yer ayrılmıştır ama Faz 1'de boş
  kalacaktır).

## 6. Kısıtlar ve varsayımlar

- **Bütçe:** "kolay ve ücretsiz" — Faz 1 tamamen ücretsiz katmanlarla
  (Supabase free tier, Vercel Hobby, Google Gemini API ücretsiz
  katmanı) çalışacak şekilde tasarlanır. Not: ilk taslakta AI motoru
  olarak seçilen Anthropic Claude API'nin kredi kartı gerektiren
  ücretli bir katmanı olduğu kullanıcı testinde ortaya çıktı; bütçe
  ilkesine sadık kalmak için Gemini'ye geçildi (bkz.
  `ARCHITECTURE.md` §1, §8).
- **Onay mekanizması:** Kullanıcı adına dış dünyaya giden her eylem
  (e-posta gönderme, takvim daveti, başvuru gönderimi) varsayılan
  olarak taslak/onay bekler modunda çalışır; tam otonom gönderim
  ayrı bir opt-in ayar olarak ileride değerlendirilebilir.
- **Veri gizliliği:** Kullanıcının kişisel verileri (e-posta içeriği,
  iletişim bilgileri, kariyer geçmişi) işlenir. KVKK/GDPR
  değerlendirmesi `SECURITY.md`'de (Faz 2) detaylandırılacak; Faz 1
  boyunca veriler yalnızca kullanıcının kendi Supabase projesinde
  tutulur, üçüncü taraflarla paylaşılmaz.
- **Dil:** Kullanıcı arayüzü ve asistan yanıtları Türkçe öncelikli;
  İngilizce e-posta/içerik de desteklenir.

## 7. Başarı kriterleri (v1)

- Kullanıcı, gün içinde Gmail'i manuel taramadan öncelikli e-postaları
  görebiliyor.
- Takvim çakışmaları asistan tarafından proaktif olarak fark
  ediliyor.
- En az bir gerçek iş başvurusu, `is-basvuru` akışının bu asistana
  taşınmış haliyle uçtan uca (tarama → puanlama → CV/ön yazı taslağı →
  kullanıcı onayı → takip kaydı) tamamlanabiliyor.
- Asistan, önceki oturumda paylaşılan bir tercihi (ör. "toplantıları
  öğleden sonraya alma") sonraki oturumda hatırlıyor.

## 8. Riskler

| Risk | Etki | Azaltma |
|---|---|---|
| OAuth/entegrasyon karmaşıklığı (Gmail/Calendar API kotaları, token yenileme) | Orta | Faz 1'de tek kullanıcı, düşük hacim — kota sorunu düşük ihtimal; `INTEGRATIONS.md`'de ele alınacak |
| Ücretsiz katmanların büyüdükçe yetersiz kalması | Düşük (Faz 1) | Tek kullanıcı için Supabase/Vercel free tier yeterli; `DEPLOYMENT.md`'de eşik ve yükseltme planı |
| Otomatik gönderimin yanlışlıkla tetiklenmesi | Yüksek (güven kaybı) | Varsayılan "taslak/onay" modu, `is-basvuru`'dan miras alınan katı kural: hiçbir form otomatik gönderilmez |
| Kapsam genişlemesi (14 ajanın hepsinin aynı anda geliştirilmeye çalışılması) | Yüksek | Bu PRD ve ROADMAP.md MVP'yi 6 bileşenle sınırlar; genişleme faz faz |

## 9. Bağımlılıklar

- `Dashboard-Project/is-basvuru` — Job Search/CV Optimizer için mevcut
  iş mantığının (scrape/apply becerileri) kaynak referansı.
- Google Gemini API erişimi (ücretsiz katman).
- Google Cloud projesi (Gmail API + Calendar API OAuth kimlik
  bilgileri).
