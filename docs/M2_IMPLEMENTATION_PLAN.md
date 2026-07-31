# M2 uygulama planı

> **Tarihsel belge:** Buradaki 1.000/1.000 canary kabulü artık release kalite
> kanıtı sayılmamaktadır. Yeniden denetim ve güncel uygulama sırası için
> [QUALITY_RECOVERY_PLAN.md](QUALITY_RECOVERY_PLAN.md) esas alınmalıdır.

Durum: doğrulanmış çok-sağlayıcılı pilot ve 1k canary tamamlandı; 5k release candidate sırada  
Başlangıç: 2026-07-29

## 2026-07-29 üretim kapsamı güncellemesi

- Kullanıcı kararıyla tüm `open_data` / `izmir_ckan` veritabanı
  arama-sorgulama blueprint'leri üretimden çıkarıldı.
- Tüm `accounting` sipariş/fatura blueprint'leri üretimden çıkarıldı.
- Adapter, registry ve stateful mock doğrulama kodu geriye uyumluluk ve birim
  testleri için korundu; accounting testi üretim blueprint'i yerine bağımsız
  test fixture'ı kullanıyor.
- Etkin üretim kataloğu 20 blueprint ve 20 aileden oluşuyor.
- Yenilenen canary 1.000/1.000 kabul, 0 ret, 0 bütçe ihlali ve
  700/100/200 split ile geçti.
- Canary'de çıkarılan alan/sağlayıcı/ground-truth çağrısı sayısı sıfır.

## 2026-07-29 uygulama kontrol noktası

> Aşağıdaki maddeler kapsam daraltılmasından önceki tarihsel M2 kontrol
> noktasını gösterir.

- 27 canonical tool; hedef aralık 25–35.
- 13 çalışma sağlayıcısı/adapter; 9 harici API yüzeyi.
- 44 blueprint ve 41 aileden 44/44 kabul edilmiş pilot örnek.
- 1.000/1.000 kabul edilen canary; 700/100/200 split, 0 ret, 0 bütçe ihlali,
  0 yinelenen kimlik ve 0 family split sızıntısı.
- 35 kullanılan HTTP cassette, 0 yetim; blob ve manifest hash doğrulaması açık.
- Çoklu sentez kataloğu v2: 2 template, 2 hash'li eksen snapshot'ı ve
  6 deterministik derlenmiş blueprint; katalog lock hash'i kayıtlı.
- Korpus bütçe kapısı ile karar, senaryo türü, zorluk, sağlayıcı, alan, çağrı
  sayısı ve split oranları zorlanıyor.
- Türkçe metin, observation-grounding ve tur akışı için konservatif çevrimdışı
  kalite kontrolleri etkin.
- 506 test; Ruff, strict mypy ve 7/7 import sözleşmesi temiz.
- MET Norway, Frankfurter/ECB, USGS, World Bank/WDI, GBIF,
  Wikimedia metadata-only ve GitHub organization metadata-only dikey dilimleri
  tamamlandı.
- `onmuhasebe_mock` create/get/update/delete, açık onay, episode izolasyonu,
  initial/final state hash ve normalize state delta üretir.
- Open Library pilotu hedef araç sayısı karşılandığı ve yeniden dağıtım durumu
  daha belirsiz olduğu için uygulanmadı.
- 10–15 bin örneklik Faz 5–6 henüz tamamlanmadı; 1k canary ölçekleme kapısının
  geçtiğini kanıtlar, benchmark veya genel yayın değildir.

## Hedef

M1'in doğrulanabilirlik iddiasını koruyarak 8–9 sağlayıcı, yaklaşık 32 araç ve
10.000–15.000 Türkçe örneğe çıkmak. Hacim, canlı çağrı sayısını aynı oranda
artırarak değil; incelenebilir şablonlar, sabit eksen snapshot'ları ve
deterministik varyant üretimiyle oluşturulacak.

## Değişmezler

- Ground-truth LLM tarafından yazılmaz.
- CI ve normal üretim replay modunda ağa çıkmaz.
- Her HTTP yanıtı içerik-adresli cassette ile doğrulanır.
- Lisans ve attribution örnek/export seviyesinde korunur.
- Read-only ortam parmak izi state hash'i gibi gösterilmez.
- Stateful yazmalar yalnızca yerel, deterministik mock üzerinde yapılır.
- Zincirler elle tasarlanır; semantic graph yalnızca doğrular.
- Split, genişleme eksenine göre sızıntıyı önleyecek seviyede atanır.

## Faz 0 — M1 bütünlük borçları

Yeni kayıt alınmadan önce:

1. Örnek kimliğini sıralı sayaçtan blueprint + varyant hash'ine geçir.
2. Episode seed'ini state/cassette episode başlangıcından önce hesapla.
3. Cassette blob okumasında içerik hash'ini doğrula.
4. Tüketilen cassette gövdelerini PII validator'a gerçekten geçir.
5. OpenAI, xLAM ve ShareGPT exporter'larında kaynak/lisans/attribution taşı.
6. Bu davranışların regresyon testlerini ekle.
7. Tüm test, ruff, mypy, import-linter ve offline E2E kapılarını çalıştır.

Çıkış ölçütü: mevcut 26 blueprint aynı trace sonuçlarını üretir; yeni kimlikler
sıra değişiminden etkilenmez; bozulmuş blob ve cassette içindeki gerçek PII
bloklayıcı hata üretir.

## Faz 1 — Çok sağlayıcılı çalışma zamanı

1. `open_izmir_environment` yerine konfigürasyon güdümlü genel environment
   builder ekle; İzmir wrapper'ını geriye uyumluluk için koru.
2. Sağlayıcı politikası modeli ekle:
   User-Agent, timeout, hız, concurrency, cache başlıkları, cassette bütçesi.
3. Rate limiter yalnızca record/record_missing yolunda çalışsın; replay tamamen
   yerel kalsın.
4. Registry ve environment fingerprint tüm etkin sağlayıcıları kapsasın.
5. Provider profile'ları `commercial_safe` ve `research` olarak ayır.

## Faz 2 — İlk dikey dilim: MET Norway

İlk araçlar:

- `search_location`: dondurulmuş, lisansı açık geocoder snapshot'ı.
- `get_current_weather`
- `get_weather_forecast`
- `compare_weather`: temel forecast çağrılarının yerel kompozisyonu.

Zorunlu kurallar:

- Enlem/boylam en çok dört ondalık.
- Kimlikli User-Agent.
- `Expires`/`Last-Modified` metadata kaydı.
- Saatlik ve günlük alanlar ayrı ve açık şemalı.
- Göreli tarihler yalnızca donmuş environment saatinden çözülür.

İlk corpus dilimi: şehir çözümleme, current/forecast ayrımı, göreli tarih,
opsiyonel parametre, iki şehir karşılaştırması, boş/uygunsuz tarih ve belirsiz
şehir senaryoları.

## Faz 3 — Salt-okunur sağlayıcı dalgaları

Sıra:

1. Frankfurter (`providers=ECB`)
2. USGS Earthquake
3. World Bank WDI (`source=2` + gösterge allowlist)
4. GBIF (CC0/CC BY filtreli)
5. Wikimedia metadata-only
6. GitHub metadata-only
7. Open Library küçük pilot

Her sağlayıcı tek dikey dilim olarak eklenir: araç şeması, adapter, cassette
kayıt script'i, normalization, blueprint'ler, lisans kaydı, testler ve dataset
card güncellemesi aynı değişiklikte tamamlanır.

## Faz 4 — Stateful yerel mock

- Create/get/update/delete akışları.
- Yazmadan önce onay gereksinimi.
- Episode başına seed'li başlangıç state'i.
- Optimistic concurrency ve beklenen hata senaryoları.
- Initial/final state hash ve state delta doğrulaması.
- Gerçek kişi veya şirket verisi içermeyen temiz oda fixture'ları.

## Faz 5 — Şablon ve eksen sentezi

- Yaklaşık 100 incelenen template. **Devam ediyor: 2 temel template hazır.**
- Değer eksenleri ayrı, hash'li snapshot dosyalarında. **Tamamlandı.**
- Slot doldurmadan önce template düzeyinde LLM paraphrase.
- Üretim lockfile'ı: template hash, eksen hash, model/prompt sürümü ve seed.
  **Katalog/eksen hash'leri tamamlandı; model/prompt alanı LLM fan-out açılırken eklenecek.**
- Pozitif/negatif, single/sequential/parallel ve kolay/orta/zor bütçeleri
  konfigürasyonda zorlanır. **1k canary için tamamlandı.**
- Aynı semantik örneğin split'ler arasında sızmasını engelleyen holdout modeli.
  **Family seviyesi tamamlandı; değer/kombinasyon holdout'u sırada.**

## Faz 6 — Ölçek ve yayın kapıları

- 1k canary **tamamlandı**; ardından 5k release candidate, son olarak 10–15k.
- %100 şema/registry/execution/state/PII geçişi.
- Cassette ve snapshot hash doğrulaması.
- Lisans allowlist'i dışında sıfır kayıt.
- Duplicate, paraphrase benzerliği ve dilbilgisi kalite raporu.
- Her exporter'da provenance.
- Dataset card, citations, third-party licenses ve bilinen sınırlamalar güncel.

## İlk teslim sırası

1. Faz 0 bütünlük düzeltmeleri.
2. Genel environment/policy iskeleti.
3. MET Norway dört araçlı offline doğrulanmış pilot.
4. İlk sentez template/axis/lockfile prototipi.
