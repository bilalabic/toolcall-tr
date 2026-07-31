# M2 sağlayıcı araştırması

Son doğrulama: 2026-07-29

Bu belge hukuki görüş değildir. M2 için sağlayıcı seçimini, kayıt politikasını ve
yayın kapılarını belirleyen mühendislik araştırmasıdır. Kararlar yalnızca resmi
sağlayıcı belgelerine dayanır; belirsiz durumlar veri setine içerik almamak
lehine çözülür.

## Araştırmanın düzelttiği iki önceki sonuç

### Open-Meteo tamamen elenmek zorunda değil

Open-Meteo iki ayrı koşulu birlikte yayımlıyor:

- API'den sunulan veri CC BY 4.0 altında ticari kullanıma ve yeniden dağıtıma
  açık.
- Ücretsiz barındırılan API hizmeti yalnızca ticari olmayan kullanım için ve
  günlük 10.000 çağrı sınırıyla sunuluyor.

Dolayısıyla veri lisansı ile barındırılan ücretsiz hizmetin kullanım şartı aynı
şey değildir. CC BY 4.0 veri seti üretmek lisans bakımından mümkün olabilir;
fakat ticari kullanıma açık bir üretim hattı ücretsiz endpoint'e dayanamaz.
Seçenekler ücretli plan, kendi sunucumuz veya ham upstream kaynaklarıdır.
Operasyon ve tekrar üretilebilirlik bakımından varsayılan hava sağlayıcısı yine
MET Norway olmalıdır.

Kaynaklar:

- https://open-meteo.com/
- https://open-meteo.com/en/terms

### GitHub için sorun mutlak yeniden dağıtım yasağı değil

GitHub şartlarının D.5 bölümü kullanıcıya, kamuya açık içeriği GitHub işlevleri
üzerinden kullanma lisansı verir. Ancak D.8, kamuya açık depolara üçüncü
tarafların yasal erişimini veya kullanımını şartların genel olarak
kısıtlamadığını ayrıca söyler. Sonuç “GitHub dışına hiçbir veri çıkarılamaz”
değildir.

Yine de issue/PR gövdeleri, yorumlar ve kod kullanıcı içeriğidir; lisansları
depo ve içerik sahibi bazında değişir. Kullanıcı adları da kişisel veri riski
taşır. M2 bu nedenle yalnızca olgusal organization repository metadata'sı
kullanmalıdır. Bireysel hesaplar filtrelenir; yalnızca zincir için gereken
organization slug'ı korunur. Ad, avatar, e-posta, description, issue/PR veya
release metni, README ve kod yayımlanmaz.

2026 şartlarının D.9 bölümü ayrıca, ticari AI sistemi geliştirmek amacıyla
otomatik erişim yapan çok büyük hizmetlere “access reciprocity” yükümlülüğü
getiriyor. Akademik araştırma ve belirtilen kullanıcı eşiğinin altındaki
ürünler için istisna yazılmış olsa da, yayın öncesi yeniden kontrol edilmelidir.

Kaynaklar:

- https://docs.github.com/en/site-policy/github-terms/github-terms-of-service
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

## Önerilen sağlayıcı matrisi

| Sağlayıcı | M2 kararı | Yayın sınıfı | Zorunlu sınır |
|---|---|---|---|
| MET Norway | Dahil | CC BY 4.0 | Kimlikli User-Agent, koordinat en çok 4 ondalık, cache/Expires, 20 req/s altı |
| Frankfurter | Dahil | Sağlayıcıya bağlı | `providers=ECB` sabit; v2 API; ham harmanlanmış oran yok |
| World Bank Indicators | Koşullu dahil | WDI için CC BY 4.0 + ek şartlar | `source=2` ve incelenmiş gösterge allowlist'i |
| USGS Earthquake | Dahil | ABD kamu malı | USGS atfı; gerçek zamanlı liste için feed tercih et |
| GBIF | Koşullu dahil | Kayıt bazında CC0/CC BY | Yalnızca izinli lisans filtresi; kayıt başına lisans ve datasetKey sakla |
| Wikimedia | Metadata-only | Metin CC BY-SA 4.0 | Extract, açıklama ve makale metni yok; başlık/ID/URL gibi metadata |
| GitHub | Metadata-only | İçeriğe göre değişir | Kullanıcı verisi ve serbest metin yok; cassette bütçesi çok düşük |
| Open Library | Pilot/koşullu | Hak durumu belirsiz | Yalnızca düşük hacimli lookup; toplu üretim için API kullanma |
| Yerel stateful mock | Dahil | Proje lisansı | Kontrollü yazma, onay ve state doğrulama bununla yapılır |
| Open-Meteo | Araştırma profilinde opsiyonel | Veri CC BY 4.0 | Ücretsiz endpoint ticari olmayan kullanımla sınırlı |
| Nager.Date | Hariç | Veri lisansı açık değil | Kodun MIT lisansı, tatil verisini otomatik lisanslamaz |
| JSONPlaceholder | Hariç | Test servisi | Yazmalar kalıcı değil; state doğrulaması yapılamaz |

Bu matris dokuz çekirdek sağlayıcı verir: MET Norway, Frankfurter, World Bank,
USGS, GBIF, Wikimedia metadata, GitHub metadata, Open Library pilot ve yerel
stateful mock. Open Library yayın kapısını geçemezse çekirdek sayı sekize iner;
bu, belirsiz bir onuncu sağlayıcıyı zorlamaktan daha güvenlidir.

## Sağlayıcıya özgü bulgular

### MET Norway

Locationforecast açık verisi CC BY 4.0'dır. Her istek tanımlayıcı ve iletişim
bilgisi taşıyan User-Agent içermeli; koordinatlar dört ondalıkla
sınırlandırılmalı; `Expires` ve `Last-Modified` başlıklarına göre cache
yapılmalıdır. Sağlayıcı, özel anlaşma olmadan uygulama başına 20 istek/saniye
üzerini istemiyor.

Kaynaklar:

- https://docs.api.met.no/doc/TermsOfService.html
- https://docs.api.met.no/doc/Licensing.html
- https://docs.api.met.no/weatherapi/locationforecast/2.0/documentation

### Frankfurter

Frankfurter v2, birden çok merkez bankasını harmanlayabiliyor. Kendi
dokümantasyonu uyumluluk için belirli sağlayıcıya sabitlemeyi öneriyor.
`providers=ECB` kullanmak provenance'ı tek kaynağa indirir. Genel günlük/aylık
kota yoktur; kötüye kullanımı engelleyen açıklanmamış rate limit vardır.

Kaynak:

- https://frankfurter.dev/

### World Bank

Indicators API anahtar istemez ve yaklaşık 16.000 seri sağlar. Dünya Bankası
veri şartları, aksi belirtilmedikçe veri setlerini CC BY 4.0 altında sunar,
ancak üçüncü taraf göstergeler farklı koşullara tabi olabilir. Genel web/API
şartları ile belirli veri seti şartları arasında kapsam farkı bulunduğundan
yalnızca World Development Indicators (`source=2`) ve ayrıca incelenmiş bir
gösterge allowlist'i kullanılmalıdır. Her örnekte gösterge kodu, kaynak ID ve
erişim tarihi provenance'a yazılmalıdır.

Kaynaklar:

- https://data.worldbank.org/summary-terms-of-use
- https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
- https://datahelpdesk.worldbank.org/knowledgebase/articles/898581

### USGS

USGS üretimi veri ve bilgiler ABD'de kamu malıdır; kurum yine de kaynak
gösterilmesini ister. FDSN Event API tarih, büyüklük, koordinat, yarıçap,
sıralama ve limit filtrelerini destekler. Sürekli “son depremler” senaryoları
için sorgu endpoint'i yerine gerçek zamanlı GeoJSON feed önerilir.

Kaynaklar:

- https://earthquake.usgs.gov/fdsnws/event/1/
- https://www.usgs.gov/faqs/are-usgs-reportspublications-copyrighted
- https://www.usgs.gov/media/files/anss-data-and-products-policy

### GBIF

Occurrence kayıtları CC0, CC BY veya CC BY-NC olabilir. Ticari kullanıma açık
korpus CC BY-NC kayıtlarını dışlamalıdır. Arama API'si sayfa başına en çok 300,
offset+limit için 100.000 sınırı uygular; büyük veri çekimi için asenkron
download servisi gerekir. Her sonuçta `license`, `datasetKey`, `key` ve
`publishingOrgKey` korunmalı; attribution kayıt bazında türetilmelidir.

Kaynaklar:

- https://techdocs.gbif.org/en/openapi/v1/occurrence
- https://www.gbif.org/terms

### Wikimedia

Makale metni CC BY-SA 4.0'dır. CC BY-SA metni, tüm veri setinin CC BY 4.0 olduğu
iddiasıyla paketlenemez. M2 yalnızca sayfa kimliği, başlık, namespace, canonical
URL, disambiguation işareti ve yönlendirme ilişkisi gibi metadata kullanmalıdır.
Summary/extract, kategori adları ve bağlantı başlıkları dahi ihtiyatlı olarak
research profilinde tutulmalıdır. API istekleri seri, kimlikli User-Agent ile,
`maxlag` ve cache kullanılarak yapılmalıdır.

Kaynaklar:

- https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use
- https://www.mediawiki.org/wiki/API:Etiquette

### Open Library

Open Library veritabanı üzerinde yeni hak iddia etmediğini söyler; bu pozitif
bir veri lisansı değildir ve katkılarda mevcut haklar olabileceğini açıkça
belirtir. API, insan odaklı düşük hacimli lookup içindir; toplu backend veya
hasat için değildir. Kimliksiz istekler 1/s, kimlikli istekler 3/s ile
sınırlıdır ve cache zorunlu beklentidir. Bu yüzden 10–15 bin örneğin eksenlerini
Open Library çağrılarıyla doldurmak uygun değildir. Küçük, sabit bir pilot
cassette kümesi dışında yayın kapısı hukuk incelemesine bağlı kalmalıdır.

Kaynaklar:

- https://openlibrary.org/developers/api
- https://openlibrary.org/developers/licensing

## 25–35 araç için güvenli hedef

İlk M2 hedefi 32 araçtır:

- MET Norway: 4 — `search_location` yerel snapshot/geocoder, current,
  forecast, compare.
- Frankfurter: 4 — currencies, latest rate, historical series, convert.
- World Bank: 4 — indicator search, value, time series, country compare.
- USGS: 4 — search, recent feed, near location, event detail.
- GBIF: 4 — name match, species search, occurrence search, species detail.
- Wikimedia metadata: 3 — search, resolve page, page metadata.
- GitHub metadata: 3 — repository search, repository metadata, releases.
- Open Library pilot: 2 — search books, ISBN lookup.
- Stateful mock: 4 — create, get, update, delete.

Karşılaştırma işlemleri mümkün olduğunda ayrı upstream çağrı değil, temel
araçların deterministik yerel kompozisyonu olmalıdır. Böylece araç çeşitliliği
artarken cassette sayısı patlamaz.

## Uygulamadan önce zorunlu kapılar

1. Cassette gövdelerinin PII tarayıcısına gerçekten ulaştığını kanıtlayan
   uçtan uca test eklenmeli.
2. Export formatları örnek başına lisans, attribution, upstream URL, erişim
   tarihi ve kaynak hash'i taşımalı.
3. Cassette blob'u okunurken içerik hash'i yeniden hesaplanıp dosya adı/index
   ile karşılaştırılmalı.
4. `example_id` sıra sayacından değil blueprint/template kimliği, eksen
   değerleri ve varyanttan türetilmeli.
5. Stateful environment `begin_episode()` çağrısını episode seed ve reset
   işleminden sonra yapmalı.
6. Ortak HTTP istemcisi sağlayıcı başına User-Agent, hız, cache ve retry
   politikasını zorlamalı; replay modunda ağ ve retry tamamen kapalı kalmalı.
7. Her sağlayıcıda yayınlanabilen alanlar allowlist ile belirlenmeli; ham API
   yanıtı exporter'a sızmamalı.
8. Lisans ve şart URL'leri cassette kayıt anında snapshot/hash ile
   sabitlenmeli; yayın öncesi yeniden doğrulanmalı.

## Açık kararlar

- Open-Meteo commercial-safe profile'a ücretli/self-hosted kanıtıyla mı
  alınacak, yoksa yalnızca research profile'da mı kalacak?
- Open Library pilotu için Internet Archive'dan açık yazılı izin aranacak mı?
- World Bank WDI gösterge allowlist'inin ilk sürümünde hangi 20–50 gösterge
  bulunacak?
- GitHub D.9 istisnasının projeye uygulanabilirliği yayın öncesi hukuk
  incelemesine gönderilecek mi?
