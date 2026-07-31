---
language: [tr]
license: cc-by-4.0
task_categories: [text-generation]
tags: [tool-calling, function-calling, turkish, execution-verified, agent]
pretty_name: ToolCall-TR (development smoke corpus)
---

# ToolCall-TR — geliştirme smoke korpusu

> **Bu bir eğitim korpusu, benchmark veya genel yayın değildir.** Eski 1.000
> kayıt yeniden denetimde 384 tekrar, eksik no-call asistan hedefleri ve
> çalıştırılmamış semantik/politika/dil kontrolleri nedeniyle karantinaya
> alınmıştır. Güncel çevrimdışı smoke ayrıca `release_ready=false` taşır.

## Özet

Türkiye'ye özgü gerçek API'lerden üretilmiş Türkçe tool-calling verisi.
Ayırt edici özelliği:

> Veri setindeki **her tool çağrısı gerçek bir implementasyon tarafından
> çalıştırıldı ve çıktısı doğrulandı. Hiçbir tool çıktısı bir LLM tarafından
> yazılmadı.**

## Bu neden var?

Hugging Face'te zaten sekiz Türkçe function-calling veri seti bulunuyor (en
büyüğü 41.480 satır). ToolCall-TR ilk olduğu için değil, aşağıdakilere sahip
**ilk** olduğu için var:

| | Mevcut TR veri setleri | ToolCall-TR |
|---|---|---|
| Kaynak | Çeviri veya İngilizce tool kataloğu | Türkiye'ye özgü gerçek API'ler |
| Tool çıktısı | LLM tarafından yazılmış | Gerçek çalıştırma ile üretilmiş |
| Doğrulama | Şema geçerliliği | Şema + registry + grounding + PII + execution |
| Yeniden üretilebilirlik | — | Cassette + donmuş saat + sıradan bağımsız seed |
| Negatif senaryolar | Sınırlı | clarification / cannot_answer / boş sonuç |

Karşılaştırılan veri setleri `legal/CITATIONS.md`'de listelenmiştir.

## Dağılım

**1.000 satır, 20 blueprint, 20 senaryo ailesi.** Yalnız 616 kullanıcı sorusu
birebir benzersizdir; 384 satır tekrardır. Family split sızıntısı yoktur, ancak
validation tek family/tek alandan oluşur ve train splitinde no-call davranışı
yoktur. Eski `passed=true` kararı yalnız yapısal smoke kapısını ifade eder;
release kalitesi anlamına gelmez.

| Karar | Adet |
|---|---|
| `tool_call` | 943 |
| `clarification` | 29 |
| `cannot_answer` | 28 |

| Senaryo türü | Adet |
|---|---|
| `successful_tool_call` | 292 |
| `empty_result` | 87 |
| `sequential_tool_call` | 564 |
| `should_ask_clarification` | 29 |
| `should_refuse` | 28 |

| Bölme | Adet |
|---|---|
| train | 700 |
| validation | 100 |
| test | 200 |

Bölme **fan-out'tan önce, senaryo ailesi seviyesinde** yapılır ve
`hash(family_id)`'den türetilir. Hiçbir aile birden fazla bölmede yer almaz;
`toolcall-tr stats` bunu her çalıştırmada denetler.

Family ayrıklığı tek başına gerçek genelleme kanıtı değildir.
`generalization_report.json`, train ile test arasında modele gösterilen bütün
tool şemalarının ve sağlayıcıların kesişimini ayrıca yayınlar. Varsayılan
`standard` profil mevcut split davranışını korur; `unseen_tool` ve
`unseen_provider` profilleri seçildiğinde ilgili kesişimin sıfır olması release
kapısıdır.

`data/evaluation/security/` altındaki sentetik tool-output prompt-injection
vakaları bu eğitim korpusunun parçası değildir. Şemaları
`training_eligible=false` değerini zorlar; release manifesti de `evaluation`
ağacındaki dosyaları eğitim girdisi olarak kabul etmez.

Bu sürümde veritabanı/açık veri arama-sorgulama ile sipariş/fatura üretim
aileleri bilinçli olarak kapsam dışıdır. Canary'de `open_data`, `izmir_ckan`
ve `accounting` alan/sağlayıcı/ground-truth çağrısı sayısı **0**'dır. İlgili
adapter ve tool tanımları geriye uyumluluk ve birim testleri için registry'de
kalabilir; bu durum üretim örneği oluşturdukları anlamına gelmez.

## Çalıştırma sınıfları — dürüstlük notu

Her çağrı **üretim biçimiyle birlikte** yayımlanır. "Tüm cevaplar canlı
API'den geldi" iddiası yapılmaz.

| Sınıf | Örnek etiketi | Anlamı |
|---|---|---|
| `live_recorded` | 857 | Üçüncü taraf API'ye gerçek HTTP; yanıt cassette'e kaydedilmiş |
| `derived_local` | 360 | Dondurulmuş, lisanslı snapshot üzerinde deterministik yerel hesaplama |

Bir örnek birden fazla yürütme sınıfı taşıyabildiği için bu sütunların toplamı
tool çağrısı yapan örnek sayısına eşit olmak zorunda değildir.

`derived_local`; durak, şehir ve WDI gösterge allowlist'i gibi sürümlenmiş
snapshot'lar içindir. Durak hesaplamasının gerekçesi şudur: belediyenin
CBS endpoint'i (a) `EPSG:` prefix'i verilmezse CRS'i sessizce yok sayıp yanlış
sonuç döner, (b) yarıçap sınırı uygulamaz — 11–15 sonucu 100 km'ye kadar
uzaktan doldurur. Yerel implementasyon **ölçülmüştür**: tool'un çalışma
aralığında (≤ 5 km) belediye servisiyle uyum **%98,3** (229/233). Ayrıntı:
`legal/DATA_SOURCES.md`.

## Doğrulama zinciri

Her örnek aşağıdaki zincirden geçer. İlk yedi kontrol bloklayıcıdır; `duplicate`,
`language`, `observation` ve `turn` canary aşamasında raporlayan erken
uyarılardır.

| Validator | Ne kontrol eder |
|---|---|
| `format` | Canonical JSON'a çevrilebilirlik, mesaj rolleri |
| `schema` | Tip, zorunluluk, sınır, enum, `additionalProperties: false` |
| `registry` | Bilinmeyen tool/parametre oranı **sıfır** |
| `grounding` | Her argümanın **beyan edilmiş** bir kaynağı var ve türüne göre doğrulanıyor |
| `confirmation` | Yan etkili çağrıda `confirmed=true` ve kullanıcı mesajında açık onay |
| `pii` | Gerçek TCKN/VKN checksum'ı, mod-97 geçerli IBAN |
| `execution` | Kaydedilmiş `Trace`, state hash ve state delta beklentiyle uyuşuyor |
| `duplicate` | Birebir, normalize edilmiş ve yakın tekrar (karakter n-gram) |
| `language` | Boş/bozuk metin, yer tutucu, mojibake ve tool adı sızıntısı |
| `observation` | Final cevap varsa güçlü sayısal/URL iddiaları gözlemde bulunuyor |
| `turn` | Tool çağrısı–yanıtı ve mesaj turu akışı tutarlı |

Stateful mock doğrulama yeteneği birim testlerinde korunur; mevcut smoke
çıktısında stateful çağrı yoktur. `duplicate` kontrolü 384 bulgu üretmiş, fakat
eski smoke profilinde bloklayıcı olmadığı için kayıtlar yazılmıştır.
Çevrimdışı koşuda ayrı bir LLM judge olarak çalıştırılmayan `semantic`,
`policy` ve doğal dil değerlendirmeleri `null` kalmıştır. `VerificationFlags`
alanındaki `null`, "bu kontrol yapılmadı" anlamına gelir ve `false` ile aynı
değildir. Release profili bu alanlar `true` olmadan geçemez.

## Kişisel veri politikası

Sentetik kimlik numaraları kasıtlı olarak **geçersiz** aralıklardan üretilir:

* **TCKN'ler `0` ile başlar.** Gerçek bir TCKN 0 ile başlayamaz; bu numaralar
  11 hane ve sayısaldır (format doğrulamasını egzersiz eder) ama
  kanıtlanabilir şekilde hiçbir gerçek kişiye ait değildir.
* VKN'ler kasten checksum-geçersizdir.
* IBAN'lar kasten mod-97-geçersizdir.

`PIIScanner` hem üretilen örnekleri hem de **cassette'leri** tarar; gerçek
checksum'ı geçen herhangi bir tanımlayıcı CI'ı kırar. Mevcut korpusta sıfır
bulgu vardır.

## Doğal dil

Kullanıcı mesajları gerçek insanların kuracağı cümlelerdir. Kimse UUID
yapıştırmaz, veri seti slug'ı bilmez, koordinat okumaz — bunlar uygulama
bağlamından (`context`) gelir. Boş sonuç senaryoları da gerçekçi ulaşım,
biyoçeşitlilik ve diğer salt-okunur API sorgularıyla kurulur.

Bu kurallar test ile zorlanır: korpusta UUID, slug, ham koordinat veya
yer tutucu metin içeren bir ifade bulunursa CI kırılır.

## Kaynaklar ve lisans

* **Kod:** Apache-2.0
* **Veri:** CC BY 4.0

Veri; ESHOT, MET Norway, ECB/Frankfurter, USGS, World Bank, GBIF, Wikimedia,
GitHub metadata yüzeyi ve lisanslı yerel snapshot'lardan türetilmiştir. Kaynak
bazlı lisans ve atıf ayrıntıları `LICENSE-DATA` ile
`legal/DATA_SOURCES.md` belgelerindedir.

> **Açık madde.** Gerçek zamanlı ESHOT servisleri (`openapi.izmir.bel.tr`)
> **ayrı bir host**tur ve beyan edilmiş bir lisansı yoktur. Bu kaynağın
> kayıtları ayrı bir namespace'te tutulur, sayıca sınırlıdır ve manifest'te
> `UNDETERMINED` işaretlenir. **Herhangi bir veri seti yayımlanmadan önce bu
> madde çözülmelidir.** Bkz. `LICENSE-DATA` § 3.

## Yeniden üretilebilirlik

```bash
uv sync --all-extras
uv run toolcall-tr generate     # ağ gerekmez
uv run toolcall-tr quality-report
```

Aynı depo durumu daima aynı `trace_id` ve aynı örnek içerik hash'lerini
üretir. Bu bir iddia değil, test edilen bir özelliktir
(`tests/test_pipeline_e2e.py::test_uretim_deterministik`). Ayrıca ayrı bir
test soket açmayı engelleyip boru hattının ağsız tamamlandığını doğrular.

## Bilinen sınırlamalar

* **Eski 1.000 satır karantinadadır.** 10–15 binlik nihai yayın veya benchmark değildir.
* Çok turlu kayıtlar yalnız doğrulanmış, tek kullanıcı amacı taşıyan
  `conversation_prefix` sözleşmesiyle üretilebilir.
* Tool-call trajectory görünümü, son doğrulanmış observation'dan deterministik
  türetilen bir final cevap taşır. `call_only` görünümü yalnız araç seçim
  hedefinde durur.
* **Template yalnız smoke içindir.** İnsan yazımı ifadeleri 32 deterministik
  çerçeveyle çeşitlendirir, kapasite dolunca tekrar üretmek yerine koşuyu
  durdurur. Release doğal dili OpenAI üreticisi ve ayrı hakemle oluşturulur.
* **Varyantların tamamı tek tek insan etiketlemesi almadı.** `human_reviewed`
  tüm canary örneklerinde `false`'tur.
* Veritabanı/açık veri arama-sorgulama ve sipariş/fatura senaryoları bu sürümün
  üretim kapsamına dahil değildir.

## Kullanım dışı

* Gerçek kişilere ait kimlik bilgisi çıkarımı — veri tamamen sentetiktir.
* İzmir Büyükşehir Belediyesi'nin resmî bir ürünü değildir.
* Mevcut boyutuyla model karşılaştırması veya sıralama.

## Atıf

Kaynak bazlı atıflar ve metodolojik referanslar `legal/CITATIONS.md`,
`legal/DATA_SOURCES.md` ve `LICENSE-DATA` içinde listelenmiştir.
