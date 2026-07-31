# Veri Kaynakları Envanteri

Bu dosya, ToolCall-TR'nin kullandığı her dış veri kaynağını, doğrulanmış lisans
durumunu ve bilinen teknik tuzaklarını kayıt altına alır.

Son doğrulama: **2026-07-29**.

## Production kaynak profili

Varsayılan production registry artık İzmir belediye araçlarını ve kurgusal ön
muhasebe araçlarını içermez. İzmir sağlayıcı kodu ve eski cassette'ler yalnız
geçmiş koşuların yeniden üretilebilmesi için arşiv/uyumluluk malzemesidir;
release manifestine alınmaz.

Etkin Türkiye/genel katalogda aşağıdaki yeni kaynaklar bulunur:

| Kaynak | Çalışma biçimi | Lisans/politika | İçerik sınırı |
|---|---|---|---|
| GeoNames Türkiye | Yerel snapshot | CC BY 4.0 | 81 il merkezi ve gruplanmış posta kodu metadata'sı |
| Türkiye resmî tatilleri | Yerel snapshot | Kamu mevzuatı + resmî takvim metadata'sı | Yalnız 2026, yarım gün ayrımı dâhil |
| Wikidata | Cassette'li HTTP | CC0 1.0 | Entity etiketi, kısa açıklama, sitelink ve yapılandırılmış ilişkiler |
| Crossref | Cassette'li HTTP | Açık bibliyografik metadata | Abstract ve tam metin hariç |
| Güvenli web federasyonu | Yerel snapshot federasyonu | Kaynağa özgü | Başlık, URL, kaynak, tür, tarih ve lisans; snippet/içerik yok |
| General local | Deterministik yerel | Apache-2.0 | Güvenli hesap makinesi ve dondurulmuş saat |
| Calendar mock | Episode-izole simülasyon | Apache-2.0 | Yalnız `.test` verisi; create/cancel açık onaylı |

### GeoNames Türkiye

Kaynak dosyalar:

- `https://download.geonames.org/export/dump/TR.zip`
- `https://download.geonames.org/export/zip/TR.zip`

`scripts/build_geonames_tr_snapshot.py`, ana dump'taki `PPLA/PPLC`
kayıtlarından 81 il merkezini seçer. Posta kodu dump'ını posta kodu, il ve ilçe
seviyesinde gruplar. Ham dump release paketine girmez; normalize snapshot kendi
hash, satır sayısı, alınma tarihi ve değişiklik bildirimini taşır.

### Türkiye resmî tatilleri

Dinî bayram tarihleri Diyanet İşleri Başkanlığının 2026 listesine; ulusal ve
genel tatiller 2429 sayılı kanundaki günlere dayanır. Snapshot yalnız 2026'yı
destekler. Başka yıl için tahmin yapılmaz ve araç yapılandırılmış domain hatası
döndürür.

### Wikidata

Wikidata yapılandırılmış verisi CC0 1.0'dır. Action API üzerinden yalnız
`wbsearchentities` ve `wbgetentities` kullanılır. Makale/Commons içeriği
alınmaz. Entity ilişkilerinde yalnız başka item'lara giden yapılandırılmış
claim hedefleri korunur.

### Crossref

Crossref bibliyografik olguları metadata olarak sunar. Bazı kayıtlardaki
abstract alanları telifli olabileceğinden request `select` listesinde yer almaz
ve cassette sanitizer ayrıca bu alanı dışarı atar.

### Güvenli web metadata federasyonu

`web.search` genel internet crawler'ı değildir. GeoNames, World Bank WDI ve
resmî tatil snapshot'larında başlık/kimlik eşleştirmesi yapar. Serbest URL
getirme, snippet, sayfa gövdesi, abstract ve yeniden dağıtılabilir arama sonucu
önbelleği yoktur.

---

## Arşiv kaynağı: İzmir Büyükşehir Belediyesi Açık Veri Portalı (CKAN)

| Alan | Değer |
|---|---|
| Taban URL | `https://acikveri.bizizmir.com` |
| API | CKAN Action API v3 (`/api/3/action/...`) |
| CKAN sürümü | 2.8.5 |
| Kimlik doğrulama | **Yok** — anonim okuma. Anonim yazma denemesi HTTP 403. |
| Lisans | **CC BY 4.0** — İzmir Büyükşehir Belediyesi Açık Veri Lisansı |
| Lisans sayfası | `https://acikveri.bizizmir.com/tr/license` |
| Kullanım koşulları | `https://acikveri.bizizmir.com/tr/terms-of-use` |
| Rate limit | Beyan edilmiş sınır **yok**; yanıtlarda `X-RateLimit-*` başlığı yok |
| Otomatik erişim | Koşullarda yasak **değil** |
| Ölçek | 257 veri seti, 694 resource, 35 organizasyon |

Lisans sayfasındaki bağlayıcı ifade:

> "Bu site altında yer alan tüm materyaller aksi belirtilmedikçe CC BY 4.0
> uluslararası lisansı ile İzmir Büyükşehir Belediyesi tarafından
> lisanslanmıştır."

Ticari kullanım, uyarlama ve yeniden dağıtım açıkça serbesttir; yalnızca atıf
gerekir.

### Kullanılan endpoint'ler

| Tool | Endpoint | Not |
|---|---|---|
| `search_datasets` | `/api/3/action/package_search` | Solr relevance sıralı |
| `get_dataset_metadata` | `/api/3/action/package_show` | |
| `query_resource` | `/api/3/action/datastore_search` | 694 resource'un 434'ü `datastore_active` |

### Determinizm tuzakları (ground truth'u sessizce bozar)

1. **`datastore_search` açık `sort` olmadan satır sırasını garanti etmez.**
   Her çağrıda `sort=_id asc` gönderilir. `_id asc` hem deterministik hem de
   bir tablo için doğal sıradır.
2. **`package_search` sıralaması pinlenmez.** Bu bir kez
   `sort=metadata_modified desc` olarak denendi ve **geri alındı**: pinleme
   Solr relevance sıralamasını yok ediyor ve `q="otobüs"` aramasının ilk
   sonucu bir *güneş enerjisi santrali* veri seti oluyordu. Determinizm zaten
   cassette replay ile sağlanır; pinlemenin çözdüğü tek şey yeniden kayıtta
   sıranın kayması ki bu **değer drift'idir**, yapısal drift değil.
3. **`datastore_search_sql` bu portalda YOKTUR.** Çağrı
   `"Geçersiz istek - Action name not known: datastore_search_sql"` döner.
   (Karşılaştırma: İBB portalında bu action etkindir.)
4. **Türkçe karakter farkı ölçüldü.** Solr analyzer'ı ü/u'yu eşitlemiyor:

   | Sorgu | Sonuç sayısı |
   |---|---|
   | `q=otobüs` | 17 |
   | `q=otobus` | 9 |

   Yani kullanıcının Türkçe karakter kullanıp kullanmaması sonucu değiştirir.
   Bu, Türkçe'ye özgü gerçek bir başarısızlık modudur ve veri setinde kasıtlı
   olarak temsil edilir (`yazim_hatali` stil varyantı).

5. **Türkçe eklemeli yapı sorguyu tamamen boşa çıkarıyor.** Portal Solr'ı
   **hiçbir Türkçe kök bulma (stemming)** yapmıyor. Ölçüm (2026-07):

   | Sorgu | Sonuç |
   |---|---|
   | `durak` | 8 |
   | `durağı` | **0** |
   | `otobüs durak` | 5 |
   | `otobüs durağı` | **0** |
   | `taksi durak` | 1 |
   | `taksi durağı` | **0** |

   İyelik eki + ünsüz yumuşaması (`k` → `ğ`) eşleşmeyi tümüyle bozuyor. Kritik
   nokta: **"otobüs durağı", bu şeyi Türkçe'de adlandırmanın en doğal
   biçimidir.** Yani kullanıcının doğru Türkçe yazması sonucu bozuyor.

   İngilizceden türetilmiş bir veri seti bu hata modunu üretemez; "bus stop"
   ile "the bus stop" arasında böyle bir kök farkı yoktur. Bu olgu
   `data/blueprints/izmir_morphology_empty_001.yaml` ile temsil edilir.
5. Varsayılan `limit=100`. Sayfalama tool şemasında açıktır.

### Yanıt tuzakları

6. **404 yanıtları JSON değil HTML'dir.** Var olmayan bir veri seti veya
   resource istendiğinde portal, CKAN'ın standart JSON hata zarfı
   (`{"success": false, "error": {...}}`) yerine **kendi HTML 404 sayfasını**
   `Content-Type: text/html` ile döndürür.

   Bu, "beklenen hata" senaryoları için kritiktir: ayrıştırılamayan gövdeyi
   altyapı hatası saymak bu senaryoları tamamen imkânsız kılar. Executor bu
   yüzden HTTP durumuna bakar — `2xx` + bozuk gövde altyapı hatasıdır,
   `4xx/5xx` + bozuk gövde ise domain hatasıdır ve ground-truth olabilir.

7. **`datastore_active` her kaynakta `true` değildir.** `duraga-yaklasan-otobusler`
   veri setinin **iki kaynağı da** `false`'tur (biri API tanımı, biri PDF
   dokümanı). Kompozisyon zincirini oradan kurmak, sessizce sorgulanamayan bir
   `resource_id` üretirdi. Zincir `eshot-otobus-duraklari` üzerinden kurulur;
   tek kaynağı `datastore_active: true` ve 11.783 satırlıdır.

### Kullanılmayan endpoint'ler

`api/izsu/barajdurum` ve `api/izsu/gunluksuuretimi` kalıcı olarak HTTP 500
döner. Bu projede kullanılmazlar.

---

## Arşiv kaynağı: ESHOT / İztek gerçek zamanlı servisleri

| Alan | Değer |
|---|---|
| Taban URL | `https://openapi.izmir.bel.tr` |
| Kimlik doğrulama | Yok |
| Lisans | **BELİRSİZ — açık madde** |

> **Bu, `acikveri.bizizmir.com` ile AYRI BİR HOST'tur.**
>
> CC BY 4.0 teyidi CKAN portalı için doğrulanmıştır. Bu host için beyan edilmiş
> bir lisans metni bulunamamıştır. Veri setleri resmî portalda kayıtlı ve resmî
> bir kullanım dokümanı mevcut olsa da (`İztek Web Servis Kullanım Dokümanı`),
> yanıt gövdelerinin **toplu yeniden dağıtımına** dair açık izin tespit
> edilememiştir.

**Uygulanan politika:** bu host production registry'den ve release
manifestinden çıkarılmıştır. Eski cassette'ler
`data/cassettes/izmir_realtime/` altında `license: "UNDETERMINED"` işaretiyle
yalnız geçmiş koşuların denetimi için kalır; yayımlanan eğitim veya benchmark
verisine alınmaz.

### Kullanılan endpoint

```
GET /api/iztek/duragayaklasanotobusler/{durakId}
```

Yanıt tuzakları — hepsi `providers/eshot/normalize.py` içinde tek noktada
düzeltilir:

- Koordinatlar **string** ve **virgüllü ondalık ayraçlı** (`"27,175345"`).
- **`KoorX` aslında ENLEM, `KoorY` aslında BOYLAM** — isimler ters.
- Boş dizi `[]` **geçerli** bir sonuçtur ("yaklaşan otobüs yok"), hata değil.

### Conformance fixture'ı (veri setine girmez)

```
GET /api/ibb/cbs/noktayayakinduraklar?x={lon}&y={lat}&inCoordSys=EPSG:4326&outCoordSys=EPSG:4326
```

İki bağımsız tuzak vardır; ikisi de `find_nearby_stops`'un neden canlı çağrı
değil yerel hesaplama olduğunu gerekçelendirir.

> **Tuzak 1 — CRS sessizce yok sayılıyor.** `inCoordSys=4326` (prefix'siz)
> gönderilirse servis CRS'i yok sayar, girdiyi projeksiyon metresi kabul eder
> ve ilin bambaşka bir ucundan sonuç döner. **Hata vermez.** `EPSG:` prefix'i
> zorunludur.

> **Tuzak 2 — yarıçap sınırı uygulanmıyor.** Servis her sorguda 11–15 sonuç
> döndürür ve listeyi mesafeye bakmadan doldurur. 25 örneklik ölçümde en uzak
> sonucun **medyanı ~62 km, maksimumu ~106 km**'dir — yani İzmir il sınırının
> dışı. Bu uzak kayıtların çoğu yayımlanan ESHOT durak tablosunda bulunmayan
> ayrı bir veritabanından gelir (`Telekler Çiflik`, `Trafo Merkezi` gibi
> kayıtlar örneklemin 100/358'ini tek başına oluşturuyor).

### Conformance ölçüm sonuçları (25 örnek, 2026-07-28)

`find_nearby_stops`'un yerel haversine implementasyonu, belediyenin CBS
servisiyle **tool'un gerçek çalışma aralığında** (`radius_m` üst sınırı 5000 m)
karşılaştırıldı:

| Ölçüt | Sonuç |
|---|---|
| En yakın durak aynı mı | ≥ %80 örnekte evet |
| Mesafe farkı | tümünde < 25 m (projeksiyon düzlemi vs büyük daire) |
| Recall, yarıçap ≤ 300 m | 145/148 = **%98.0** |
| Recall, yarıçap ≤ 1000 m | 220/223 = **%98.7** |
| Recall, yarıçap ≤ 5000 m | 229/233 = **%98.3** |

Kalan ~%2, CBS veritabanında bulunan ancak açık veri olarak yayımlanan
`eshot-otobus-duraklari` tablosunda yer almayan duraklardır.

Uzak alan (>5 km) karşılaştırması kasıtlı olarak yapılmaz: `find_nearby_stops`
oraya hiç bakmaz, CBS ise 100 km'den sonuç doldurur. Bu sayılar dataset card'da
alıntılanır; test `tests/test_stops.py::test_conformance_recall_calisma_araliginda`
sessizce sapmalarını engeller.

---

## 3. Dondurulmuş snapshot'lar

| Snapshot | Kaynak | Satır | Lisans |
|---|---|---|---|
| `data/snapshots/eshot_stops/` | CKAN datastore resource `0c791266-a2e4-4f14-82b8-9a9b102fbf94` | 11.783 | CC BY 4.0 |

Alanlar: `DURAK_ID`, `DURAK_ADI`, `ENLEM`, `BOYLAM`, `DURAKTAN_GECEN_HATLAR`.
Koordinatlar temiz WGS84.

Her snapshot yanında `SNAPSHOT.json` bulunur: resource id, alınma tarihi, satır
sayısı, içerik hash'i, lisans ve atıf.

---

## 4. Değerlendirilip reddedilen kaynaklar

| Kaynak | Neden reddedildi |
|---|---|
| Ticari ön muhasebe SaaS OpenAPI şemaları | Kullanım koşulları çoğaltmayı ve marka kullanımını yasaklıyor; depodaki izin sinyalleri çelişkili. Yerine kurgusal `onmuhasebe_mock` yazılır. |
| Üçüncü taraf posta kodu API'leri (`ubilisim`, `zumbo` vb.) | PTT verisinin resmî olmayan aynaları; lisans beyanı yok |
| e-Devlet / MERNİS / KPS | Kapalı servis, yasal olarak erişilemez |
| Banka ve kargo özel endpoint'leri | Tersine mühendislik gerektirir; kapsam dışı |
| TCMB EVDS | Ücretsiz ama **API anahtarı zorunlu**; sıfır yapılandırmalı anonim erişim hedefiyle uyumsuz |
| İBB Açık Veri | Teknik olarak uygun (ve `datastore_search_sql` etkin), ancak M1 kapsamı dışında. M2+ için aday. |

---

## 5. Yeniden doğrulama prosedürü

Yapısal drift ground-truth'u geçersiz kılar; değer drift'i normaldir. Haftalık
job bu ikisini ayırır ve yalnızca **yapısal** drift insan müdahalesi ister:

```bash
uv run toolcall-tr cassette verify --drift-check --sample 25
```

Karşılaştırma, gövde **değerleri** üzerinden değil, özyinelemeli **tip/anahtar
iskeleti** üzerinden yapılır.
