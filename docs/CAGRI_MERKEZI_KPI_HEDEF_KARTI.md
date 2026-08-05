# Çağrı Merkezi KPI Hedef Kartı (Scorecard)

> **Amaç:** Çağrı merkezi operasyonunun performansını tek bir sayfada ölçülebilir, karşılaştırılabilir ve yönetilebilir hâle getirmek. Bu hedef kartı; her metrik için tanım, hesaplama formülü, sektör kıyaslaması (benchmark), hedef değer ve renk eşiklerini (yeşil/sarı/kırmızı) içerir.
>
> **Hazırlanma tarihi:** 2026-08-05
> **Kapsam:** Sesli çağrı (inbound/outbound) operasyonu — çok kanallı (omnichannel) merkezler için "Dijital Kanallar" bölümüne bakınız.
> **Gözden geçirme sıklığı:** Aylık (hedeflerin revizyonu çeyreklik).

---

## 1. Nasıl Okunur?

- **Hedef:** Operasyonun ulaşmayı taahhüt ettiği değer.
- **Yeşil (🟢) / Sarı (🟡) / Kırmızı (🔴):** Performans bandı. Yeşil = hedefte veya üstünde; Sarı = kabul edilebilir ama izlenmeli; Kırmızı = aksiyon gerektirir.
- **Benchmark:** Sektör genel ortalaması (yatay kıyaslama için referans; kendi geçmiş performansınız = dikey kıyaslama).
- **Sıklık:** Ölçüm/raporlama periyodu.
- **Sahip:** Metrikten birinci derecede sorumlu rol.

> ⚠️ **Uyarı:** Metrikler tek başına yanıltıcı olabilir. Örn. AHT'yi (Ortalama Görüşme Süresi) düşürmek FCR'yi (İlk Temasta Çözüm) bozabilir. Bu yüzden kartı "denge" içinde okuyun — hız metriklerini her zaman kalite ve müşteri metrikleriyle birlikte değerlendirin.

---

## 2. Çekirdek KPI Hedef Tablosu

### 2.1 Erişilebilirlik & Hız (Accessibility & Speed)

| KPI | Tanım / Formül | Benchmark | 🎯 Hedef | 🟢 Yeşil | 🟡 Sarı | 🔴 Kırmızı | Sıklık | Sahip |
|---|---|---|---|---|---|---|---|---|
| **Servis Seviyesi (SL)** | Belirli sürede yanıtlanan çağrı oranı (klasik: 80/20 = %80'i 20 sn içinde) | 80/20 | %80 ≤20 sn | ≥%80 | %70–79 | <%70 | Gerçek zamanlı / Günlük | WFM / Operasyon |
| **Ortalama Yanıt Hızı (ASA)** | Toplam bekleme süresi ÷ yanıtlanan çağrı sayısı | ~28 sn | ≤20 sn | ≤20 sn | 21–40 sn | >40 sn | Günlük | WFM |
| **Terk Oranı (Abandonment)** | Yanıtlanmadan bırakılan çağrı ÷ toplam gelen çağrı | %5–8 | ≤%5 | ≤%5 | %5–8 | >%8 | Günlük | WFM |
| **Kuyrukta Ort. Bekleme** | Kuyrukta geçen toplam süre ÷ kuyruğa giren çağrı | — | ≤30 sn | ≤30 sn | 31–60 sn | >60 sn | Günlük | WFM |
| **Meşguliyet/Bloke Oranı (Blockage)** | Hatların dolu olması nedeniyle ulaşılamayan çağrı oranı | <%2 | ≤%2 | ≤%2 | %2–5 | >%5 | Günlük | Telekom / IT |

### 2.2 Verimlilik & Operasyon (Efficiency & Operations)

| KPI | Tanım / Formül | Benchmark | 🎯 Hedef | 🟢 Yeşil | 🟡 Sarı | 🔴 Kırmızı | Sıklık | Sahip |
|---|---|---|---|---|---|---|---|---|
| **Ort. Görüşme Süresi (AHT)** | (Konuşma + Bekletme + Çağrı Sonrası İş) ÷ çağrı sayısı | ~6 dk | Kuyruğa özel hedef* | Hedef ±%10 | ±%10–20 | >±%20 | Günlük | Takım Lideri |
| **Çağrı Sonrası İş (ACW)** | Görüşme sonrası kayıt/işlem süresi | 30–60 sn | ≤45 sn | ≤45 sn | 46–90 sn | >90 sn | Günlük | Takım Lideri |
| **Doluluk (Occupancy)** | Çağrıyla meşgul süre ÷ oturum açık toplam süre | %75–85 | %80–85 | %80–85 | %70–79 / %86–90 | <%70 / >%90 | Günlük | WFM |
| **Kullanım (Utilization)** | Üretken süre ÷ ödenen toplam süre | %60–70 | ≥%65 | ≥%65 | %55–64 | <%55 | Haftalık | WFM |
| **Program Uyumu (Adherence)** | Planlanan vardiyaya uyum oranı | %85–90 | ≥%90 | ≥%90 | %80–89 | <%80 | Günlük | WFM |
| **Transfer Oranı** | Başka birime aktarılan çağrı ÷ toplam çağrı | %10 | ≤%10 | ≤%10 | %10–15 | >%15 | Haftalık | Operasyon |
| **Eskalasyon Oranı** | Üst seviyeye taşınan çağrı ÷ toplam çağrı | <%10 | ≤%8 | ≤%8 | %8–12 | >%12 | Haftalık | Operasyon |

*\*AHT için tek bir "iyi" değer yoktur; iş türüne göre kuyruk bazlı hedef belirlenir. Kısa AHT tek başına iyi değildir — FCR ile birlikte okunmalıdır.*

### 2.3 Kalite & Çözüm (Quality & Resolution)

| KPI | Tanım / Formül | Benchmark | 🎯 Hedef | 🟢 Yeşil | 🟡 Sarı | 🔴 Kırmızı | Sıklık | Sahip |
|---|---|---|---|---|---|---|---|---|
| **İlk Temasta Çözüm (FCR)** | Tek temasta çözülen talep ÷ toplam talep | %70–75 | ≥%75 | ≥%75 | %65–74 | <%65 | Haftalık | Kalite / Operasyon |
| **Kalite Skoru (QA)** | Değerlendirilen çağrıların ortalama kalite puanı | %85–90 | ≥%90 | ≥%90 | %80–89 | <%80 | Haftalık | Kalite |
| **Tekrar Arama Oranı** | 7 gün içinde aynı konuyla yeniden arayan ÷ toplam | <%20 | ≤%15 | ≤%15 | %15–25 | >%25 | Haftalık | Kalite |
| **Uyumluluk/Compliance İhlali** | Zorunlu senaryo/regülasyon ihlali sayısı | 0 | 0 | 0 | 1–2 (kritik olmayan) | ≥1 kritik | Haftalık | Kalite / Uyum |

### 2.4 Müşteri Deneyimi (Customer Experience)

| KPI | Tanım / Formül | Benchmark | 🎯 Hedef | 🟢 Yeşil | 🟡 Sarı | 🔴 Kırmızı | Sıklık | Sahip |
|---|---|---|---|---|---|---|---|---|
| **CSAT** | Memnun (4–5) yanıt ÷ toplam anket yanıtı × 100 | ~%80 | ≥%85 | ≥%85 | %75–84 | <%75 | Sürekli / Haftalık | CX / Operasyon |
| **NPS** | %Tavsiye edenler − %Eleştirenler (−100…+100) | +30–40 | ≥+40 | ≥+40 | +20…+39 | <+20 | Aylık | CX |
| **Müşteri Eforu (CES)** | "Sorunumu kolayca çözdüm" algısı (1–7 ölçek) | ~5.0 | ≥5.5 | ≥5.5 | 4.5–5.4 | <4.5 | Aylık | CX |
| **Anket Yanıt Oranı** | Yanıtlanan anket ÷ gönderilen anket | %10–15 | ≥%15 | ≥%15 | %8–14 | <%8 | Aylık | CX |

### 2.5 Maliyet & Çalışan (Cost & People)

| KPI | Tanım / Formül | Benchmark | 🎯 Hedef | 🟢 Yeşil | 🟡 Sarı | 🔴 Kırmızı | Sıklık | Sahip |
|---|---|---|---|---|---|---|---|---|
| **Temas Başına Maliyet** | Toplam operasyon maliyeti ÷ temas sayısı | Sektöre göre | Hedef bütçe | ≤bütçe | +%0–10 | >+%10 | Aylık | Finans / Operasyon |
| **Çalışan Devir Hızı (Attrition)** | Ayrılan temsilci ÷ ortalama temsilci sayısı (yıllık) | %30–45 | ≤%25 | ≤%25 | %25–35 | >%35 | Aylık | İK |
| **Çalışan Bağlılığı (eNPS)** | Temsilci tavsiye skoru | — | ≥+20 | ≥+20 | 0…+19 | <0 | Çeyreklik | İK |
| **Devamsızlık (Absenteeism)** | Plansız devamsızlık süresi ÷ planlanan süre | <%5 | ≤%5 | ≤%5 | %5–8 | >%8 | Aylık | İK / WFM |
| **İlk Çağrıya Kadar Yetkinlik (Speed to Proficiency)** | Yeni temsilcinin hedef performansa ulaşma süresi | 60–90 gün | ≤60 gün | ≤60 gün | 61–90 gün | >90 gün | Çeyreklik | Eğitim / İK |

### 2.6 Dijital & Çok Kanallı (Opsiyonel — omnichannel merkezler)

| KPI | Tanım / Formül | Benchmark | 🎯 Hedef | 🟢 Yeşil | 🟡 Sarı | 🔴 Kırmızı | Sıklık | Sahip |
|---|---|---|---|---|---|---|---|---|
| **Self-Servis / Deflection Oranı** | IVR/bot ile canlıya düşmeden çözülen ÷ toplam | %20–30 | ≥%30 | ≥%30 | %15–29 | <%15 | Haftalık | Dijital Kanallar |
| **Bot Çözüm (Containment)** | Bot'un canlıya aktarmadan çözdüğü sohbet oranı | %40–60 | ≥%50 | ≥%50 | %35–49 | <%35 | Haftalık | Dijital Kanallar |
| **Chat Ort. Yanıt Süresi (İlk)** | İlk mesaja ilk yanıt süresi | <30 sn | ≤30 sn | ≤30 sn | 31–60 sn | >60 sn | Günlük | Dijital Kanallar |
| **E-posta İlk Yanıt Süresi** | E-posta talebine ilk yanıt süresi | <4 saat | ≤4 saat | ≤4 saat | 4–8 saat | >8 saat | Günlük | Dijital Kanallar |

---

## 3. KPI'lar Arası Denge (Trade-off) İlişkileri

Metrikleri izole optimize etmek zararlıdır. En kritik gerilimler:

| Baskı altındaki metrik | Yan etki riski | Denge kuralı |
|---|---|---|
| AHT ↓ (süre kısaltma) | FCR ↓, CSAT ↓, Tekrar Arama ↑ | AHT'yi yalnızca FCR ve CSAT sabit/artarken düşür |
| Occupancy ↑ (>%90) | Tükenmişlik, Attrition ↑, Kalite ↓ | Doluluğu %80–85 bandında tut |
| Servis Seviyesi ↑ (aşırı personel) | Temas başına maliyet ↑ | SL hedefini müşteri değeriyle orantılı belirle |
| Terk oranı ↓ hedefi | Suni kuyruk yönetimi, ASA ↑ | Terk + ASA + SL üçlüsünü birlikte izle |

---

## 4. Kuzey Yıldızı (North Star) Önerisi

Tek bir "sağlık" göstergesi izlenecekse, hız + kalite + deneyimi birleştiren şu bileşik öneriliyor:

> **Operasyon Sağlık Skoru = FCR × CSAT × (Servis Seviyesi ağırlığı)**

Alternatif olarak müşteri odaklı merkezlerde **CES (Müşteri Eforu)** kuzey yıldızı olarak kullanılabilir; çünkü tekrar arama ve sadakat ile en güçlü korelasyona sahiptir.

---

## 5. Uygulama Notları

1. **Hedefleri kendinize göre kalibre edin.** Yukarıdaki benchmark'lar genel sektör aralıklarıdır; ilk 1–2 ay temel çizginizi (baseline) ölçüp hedefleri ona göre revize edin.
2. **Segmentasyon şart.** SL/AHT/FCR gibi metrikleri kuyruk, kanal ve müşteri segmenti bazında ayrıştırın — genel ortalama sorunları gizler.
3. **Aksiyon eşiği tanımlayın.** Her 🔴 için önceden belirlenmiş bir müdahale planı (ek personel, çağrı yönlendirme, koçluk) olsun.
4. **Gözden geçirme ritmi:** Günlük operasyon panosu (hız/erişim), haftalık kalite kurulu (FCR/QA), aylık liderlik gözden geçirmesi (CX/maliyet/İK).
5. **Veri kalitesi.** Metrikler ancak ölçüm sisteminiz kadar iyidir; ACW, terk ve occupancy tanımlarını sistem genelinde standartlaştırın.

---

## 6. Sözlük (Kısaltmalar)

| Kısaltma | Açılım |
|---|---|
| SL | Service Level — Servis Seviyesi |
| ASA | Average Speed of Answer — Ortalama Yanıt Hızı |
| AHT | Average Handle Time — Ortalama Görüşme Süresi |
| ACW | After Call Work — Çağrı Sonrası İş |
| FCR | First Call Resolution — İlk Temasta Çözüm |
| QA | Quality Assurance — Kalite Güvence |
| CSAT | Customer Satisfaction — Müşteri Memnuniyeti |
| NPS | Net Promoter Score — Net Tavsiye Skoru |
| CES | Customer Effort Score — Müşteri Eforu Skoru |
| WFM | Workforce Management — İş Gücü Yönetimi |
| eNPS | Employee Net Promoter Score — Çalışan Tavsiye Skoru |

---

*Bu hedef kartı bir başlangıç şablonudur. Sektör (bankacılık, telekom, e-ticaret, sağlık), kanal karması ve regülasyon gereksinimlerine göre metrik seti ve eşikler uyarlanmalıdır.*
