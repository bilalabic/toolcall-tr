# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Komutlar

```bash
uv sync --all-extras                  # ortam kurulumu
uv run pytest -q                      # tüm testler
uv run pytest tests/test_planner.py -q            # tek dosya
uv run pytest tests/test_planner.py::test_forward_ref_rejected -q   # tek test
uv run pytest -m network               # ağa çıkan testler (varsayılan olarak çalışmaz)
uv run ruff check . && uv run ruff format .
uv run mypy src                        # strict
uv run lint-imports                    # katman ihlali kontrolü -- CI'da zorunlu
```

Pipeline uçtan uca (ağ gerekmez, cassette'lerden çalışır):

```bash
uv run toolcall-tr generate            # planla + çalıştır + doğrula + yaz
uv run toolcall-tr export --format xlam
uv run toolcall-tr quality-report
uv run toolcall-tr stats               # split sızıntısı denetimi
uv run toolcall-tr cassette verify     # yetim kayıt denetimi
```

Cassette kaydı **kasıtlı ve açık** bir eylemdir; hiçbir CLI komutu ağa çıkmaz:

```bash
uv run python scripts/record_ckan_cassettes.py    # --mode record | record_missing
uv run python scripts/record_eshot_cassettes.py
uv run python scripts/fetch_stops_snapshot.py
uv run python scripts/record_cbs_conformance.py
```

Üretici model karşılaştırması (API anahtarı gerektirir):

```bash
uv run python scripts/compare_generators.py --variants 4
```

## LLM seçimi

LLM **yalnızca doğal Türkçe ifadeyi** yazar; ground-truth koddan derlenir.
Bu bir *akıcılık* işidir, muhakeme işi değil.

**Üretici model ölçülerek seçildi: `gpt-4.1-mini`.** 104 çağrılık ölçüm
(2026-07):

| model | kabul | benzersiz | benzerlik | uzunluk | çıkış tok |
|---|---|---|---|---|---|
| **gpt-4.1-mini** | %100 | %99,0 | **0,144** | 64 | 1.889 |
| gpt-5.4-mini | %98,1 | %97,1 | 0,196 | 61 | 2.207 |
| gpt-5-mini | %100 | %41,3 | 0,418 | **22** | **45.931** |

`gpt-5-mini` %100 kabul aldı ama **elendi**: çağrı başına ~440 çıkış token'ı
harcayıp ortalama 22 karakter üretiyor. Bütçe muhakemeye gidiyor, cevap
kırpılıyor; kalıntı argümanı içerdiği için yapısal validator'lar geçiriyor.
Bu, metriğin yanlış pozitifiydi — script'e uzunluk ve görünür-token kontrolü
eklendi ve uyarı alan aday artık öneriden diskalifiye ediliyor.

**Ders:** muhakeme ağırlıklı modeller bu işte zarar veriyor, ve bir modelin
"%100 geçti" demesi metriğin yeterli olduğu anlamına gelmiyor.

Judge üreticiden **farklı bir model** olmalı (self-preference bias). İdeali
farklı bir *sağlayıcı*dır; tek sağlayıcı varsa en azından farklı bir aile
seçilir ve bu sınırlama dataset card'da belirtilir.

**Model seçimi tahminle sabitlenmez, ölçülür:**

```bash
uv run python scripts/compare_generators.py --variants 4
```

Script üç şey raporlar ve karar üçüne birlikte bakılarak verilir:

| Metrik | Anlamı |
|---|---|
| kabul oranı | Validator'lardan geçen örnek payı |
| benzersiz | Üretilen ifadelerin kaçı gerçekten farklı |
| **benzerlik** | Aynı blueprint varyantları arasındaki n-gram benzerliği — **düşük olan iyi** |

**Yalnızca kabul oranına bakma.** Validator'lar yapısaldır; bu boyuttaki bir
korpusta birden fazla model %100'e ulaşır ve tablo ayırt etmeyi bırakır.
Eşitlik durumunda çeşitlilik ayırır, nihai karar insan incelemesidir.

Yanıtlar `data/llm_cache/` altında önbelleklenir ve anahtar **modeli de
içerir** — yoksa adaylar birbirinin yanıtını görür ve karşılaştırma sessizce
anlamsızlaşırdı. Yeniden çalıştırma API'ye gitmez.

### Parametre uyumu tahmin edilmez

`OpenAIClient` "şu önekler `max_completion_tokens` ister" gibi bir liste
tutmaz — böyle bir liste bir kez denendi ve yanlış çıktı (GPT-5 ailesinin
tamamı istiyormuş). Bunun yerine istemci 400 hatasındaki *Unsupported
parameter* mesajını okuyup yükü uyarlar, bir kez yeniden dener ve uyarlamayı
hatırlar. Tanımadığı hatayı **yutmaz**.

## Mimari

### Üç faz — asla tek adımda birleştirme

```
Blueprint --[A: planner, SAF, I/O yok]--> CallPlan
CallPlan  --[B: runner, I/O, seed altında deterministik]--> Trace
Trace     --[C: validation, SAF]--> ValidationResult
```

Bu ayrım tasarımın merkezidir. `groundtruth/planner.py` gerçek derleyicidir:
tool/parametre varlığı, tip uyumu ve `$actions[i].result.x` referanslarının
geçerliliği burada hard-fail eder — hiçbir ağ, cassette veya mock olmadan.
`groundtruth/runner.py` planı bir `Environment` içinde çalıştırıp `Trace`
üretir. Validator'lar yalnızca kaydedilmiş `Trace`'i okur.

**Validator'lar executor import etmez.** Bunu yaparsan
`validation ↔ execution` döngüsü oluşur ve `lint-imports` CI'da patlar.
Yeniden çalıştırma gerekiyorsa o bir `groundtruth/` adımıdır, validator değil.

**Sembolik dry-run yazma.** "Dry run" = `cassette_mode=replay` ile runner.
Ayrı bir yan etkisiz execution yolu iki hafta içinde gerçek yoldan sapar.

### Cassette katmanı

`execution/cassette.py` bir `httpx.BaseTransport` alt sınıfıdır — executor'lar
cassette'ten habersizdir, sadece kendilerine verilen `httpx.Client`'ı kullanır.

Anahtar **HTTP isteğinden** türetilir (method + url + sıralı query + gövde +
allowlist header), **tool argümanından değil**. Tool şeması repodaki en oynak
artefakttır; cassette'leri ona bağlamak her şema değişikliğinde tüm kayıtları
yetim bırakır.

Argümanlar isteğe çevrilmeden önce Pydantic modelinden geçirilerek normalize
edilir. Canonical JSON tek başına `{"rows": 10}` vs `{"rows": "10"}` veya
atlanmış-opsiyonel vs açıkça-verilmiş-default farkını çözmez.

Modlar: `record` / `replay` / `record_missing`. `TOOLCALL_TR_CASSETTE_MODE` ile
seçilir. **CI ağa erişemez** — cassette'siz istek exception fırlatır.

### `state_hash` ile `environment_fingerprint` karıştırılmaz

Read-only provider'da state yoktur: `state_hash = None`. Cassette manifest
hash'i + snapshot hash'leri ayrı bir alan olan `environment_fingerprint`'e
yazılır. Bu ikisini birleştirmek downstream tüketicilere kalıcı olarak yanlış
zihinsel model öğretir.

### Function graph türetilir, elle yazılmaz

Tool parametrelerinde ve output alanlarında `semantic_type` bulunur
(`durak_id`, `resource_id`, `package_id`). Kompozisyon grafiği bundan türetilir.
`configs/function_graph.yaml` yalnızca istisnalar ve açık negatifler içindir.
Aynı alan grounding kontrolünü, distractor üretimini ve "bu `durak_id`
snapshot'ta var mı" validator'ını da bedava sağlar.

### Katmanlama

`.importlinter` bunu zorlar:

```
models/, turkish/  ->  hiçbir iç bağımlılık
registry/          ->  models
providers/         ->  models, registry, turkish
execution/         ->  models, registry, providers
groundtruth/       ->  models, execution
validation/        ->  models          (execution DEĞİL)
cli/               ->  her şey; cli'yi kimse import etmez
```

Provider'lar `TOOLS: list[ToolSpec]` export eder; `build_registry()` birleştirir
ve registry açıkça geçirilir. Decorator tabanlı kayıt singleton'ı **kullanma** —
import sırası bug'ları üretir ve test izolasyonunu bozar.

## Determinizm kuralları

Bunların her biri ihlal edildiğinde flaky hash üretir:

- **Saat donmuştur.** `now()` `Environment`'tan gelir. `datetime.now()` çağırma;
  ruff `DTZ` kuralı bunu yakalar.
- **Seed sıradan bağımsızdır:** `episode_seed = sha256(blueprint_id + variant_index)`.
  Çalışma sırasına göre ilerleyen global RNG kullanma — blueprint #21 eklemek
  #1–20'nin verisini değiştirir.
- **CKAN çağrılarında `sort` her zaman açıktır.** `datastore_search` → `_id asc`;
  `package_search` → `metadata_modified desc`. Aksi hâlde satır sırası garanti
  edilmez ve yeniden kayıt farklı cassette üretir.
- **Replay altında retry/timeout kapalıdır.** Ağa uzanan retry döngüsü CI'da
  flake üreticisidir.
- **State snapshot'ı normalize edildikten sonra hash'lenir**, ham store değil.

## Sağlayıcıya özgü tuzaklar

Hepsi canlı HTTP ile doğrulanmıştır, tahmin değildir. Ayrıntı ve ölçümler:
`legal/DATA_SOURCES.md`.

- `datastore_search_sql` İzmir'de **yoktur** (İBB'de vardır). `query_resource`
  yalnızca `datastore_search` kullanır.
- **404 yanıtları JSON değil HTML'dir.** Portal, CKAN'ın standart hata zarfı
  yerine kendi HTML sayfasını döndürür. Bu yüzden executor HTTP durumuna bakar:
  `2xx` + ayrıştırılamayan gövde = altyapı hatası; `4xx/5xx` + ayrıştırılamayan
  gövde = **domain hatası** ve ground-truth olabilir. Bu ayrım olmadan tüm
  "beklenen hata" senaryoları imkânsızdır.
- **`package_search` sıralaması pinlenmez.** Bir kez `metadata_modified desc`
  denendi ve geri alındı: relevance sıralamasını yok edip `q="otobüs"`
  aramasının ilk sonucunu bir güneş enerjisi veri seti yapıyordu. Determinizmi
  cassette sağlar. `datastore_search` ise **her zaman** `sort=_id asc` alır.
- **Türkçe karakter sonucu değiştirir:** `q="otobüs"` → 17 sonuç,
  `q="otobus"` → 9. Solr analyzer'ı ü/u'yu eşitlemiyor.
- **Türkçe ek morfolojisi sorguyu tamamen boşa çıkarır.** Solr hiç kök bulma
  yapmıyor: `durak` → 8, `durağı` → **0**; `otobüs durak` → 5,
  `otobüs durağı` → **0**. İyelik eki + ünsüz yumuşaması (k→ğ) eşleşmeyi
  bozuyor — üstelik "otobüs durağı" en doğal Türkçe biçimdir. Blueprint
  yazarken sorgu terimlerini **eksiz** tut; olguyu temsil eden ayrı bir
  blueprint zaten var (`izmir_morphology_empty_001`).
- **`datastore_active` her kaynakta true değildir.** Kompozisyon zinciri
  `eshot-otobus-duraklari` üzerinden kurulur (tek kaynak, 11.783 satır);
  `duraga-yaklasan-otobusler`'in **iki kaynağı da false**'tur.
- ESHOT `duragayaklasanotobusler` yanıtında **`KoorX` enlem, `KoorY` boylamdır**
  — isimler terstir. Koordinatlar virgüllü ondalıklı string'dir. Dönüşüm tek
  yerde: `providers/izmir/eshot.py`. Ham gövde cassette'e, normalize gövde tool
  sonucuna yazılır. Normalize sonrası koordinat İzmir aralığı dışına çıkarsa
  **gürültülü patlar** — kaynak takası düzeltirse sessizce bozulmayalım diye.
- **`[]` geçerli bir sonuçtur** ("yaklaşan otobüs yok"), hata değil. İlgili
  tool'da `allow_empty_result=True`.
- `cbs/noktayayakinduraklar` iki ayrı tuzak taşır: (1) `inCoordSys=4326`
  (prefix'siz) verildiğinde CRS'i **sessizce yok sayar**; (2) **yarıçap sınırı
  uygulamaz** — 11–15 sonucu 100 km'ye kadar uzaktan doldurur. Bu yüzden
  `find_nearby_stops` canlı çağrı değil, dondurulmuş tablo üzerinde yerel
  haversine'dir (`execution_class="derived_local"`). Uyum ölçülmüştür: ≤5 km'de
  **%98.3** (229/233).
- İZSU `barajdurum` ve `gunluksuuretimi` kalıcı HTTP 500. Kullanma.

## Doğal dil — validator'a uydurma

Bu proje bir kez şu hatayı yaptı: grounding validator argüman değerinin
kullanıcı mesajında **birebir** geçmesini istediği için ifadelere UUID'ler,
veri seti slug'ları ve ham koordinatlar yazıldı. Sonuç, hiçbir insanın
kurmayacağı cümlelerdi. **Doğal dil validator'a uydurulmaz; validator
gerçekliği modeller.**

Argüman kaynağını doğru seç:

| Kaynak | Ne zaman | Denetim |
|---|---|---|
| `USER_MESSAGE` | Değer mesajda birebir geçiyor (durak no, tutar, tarih) | Birebir arama |
| `USER_MESSAGE_DERIVED` | Değer mesajdan türetilmiş (ek soyma, normalizasyon) | Türkçe gevşek eşleştirme |
| `SYSTEM_STATE` | Uygulamanın bildiği, kullanıcının **söylemediği** şey | `Blueprint.context`'te beyan zorunlu |
| `PINNED_FIXTURE` | Yazarın sabitlediği fixture kimliği | Beyan yeterli |
| `PRIOR_OBSERVATION` | Önceki adımın çıktısı (`StepRefArg`) | Planner kanıtlar |

`USER_MESSAGE_DERIVED` uydurma bir kategori değil: kullanıcı "otobüs
duraklarıyla" der, arama terimi `"otobüs durak"` olur — portal Solr'ı Türkçe
kök bulmadığı için bu dönüşüm **doğru cevabın ön koşuludur**. Eşleştirme
`turkish/morphology.py` içindedir.

Blueprint yazarken:

- Kullanıcı **UUID yapıştırmaz, slug bilmez, koordinat okumaz.** Bunlar
  `context`'e gider (`goruntulenen_tablo`, `cihaz_konumu_enlem`) ya da zincirle
  bulunur.
- Boş sonuç senaryoları **gerçekçi** sorgularla kurulur. `zzzbulunmayan...`
  gibi terimler doğal dil iddiasını çürütür; canlıda 0 sonuç döndüğü
  doğrulanmış makul sorular kullanılır (ör. `elektrikli scooter`).
- Her blueprint **en az iki** ifade taşır.

`tests/test_pipeline_e2e.py` bunların hepsini korpus genelinde zorlar.

## Kırmızı çizgiler

- **Sentetik TCKN'ler `"0"` ile başlar.** Gerçek bir TCKN 0 ile başlayamaz;
  checksum-geçerli 11 haneli bir sayı üretmek gerçek bir vatandaşın KVKK
  korumalı kimliğini açık lisansla yayımlamak demektir. VKN kasten
  checksum-geçersiz, IBAN kasten mod-97-geçersizdir. `PIIScanner` bunu hem
  örnekler hem cassette'ler üzerinde CI'da zorlar.
- **Hiçbir ticari sağlayıcının OpenAPI/Swagger dosyası veya dokümantasyon
  metni** bu depoya girmez — test fixture, yorum satırı, commit mesajı dahil.
  `onmuhasebe_mock` temiz oda yazımıdır ve rezerve `.test` TLD'sini kullanır.
- **Split fan-out'tan ÖNCE, family seviyesinde yapılır.** `family_id`
  blueprint'te beyan edilir, `hash(family_id)`'den türetilir. Paraphrase'ler
  ait oldukları family'nin split'ini miras alır — aksi hâlde benchmark sessizce
  kirlenir.
- **Reddedilen örnekler `data/rejected/` altında gerekçesiyle saklanır.**
  Sessizce silme.
- `Salesforce/APIGen-MT-5k` (CC BY-NC) ve `xlam-function-calling-60k` (çelişkili
  lisans) hiçbir biçimde kullanılmaz. Bkz. `NOTICE.md`.
- `openapi.izmir.bel.tr` lisans durumu **belirsizdir** ve yayın öncesi çözülmesi
  gereken açık bir maddedir. Bu host'un cassette'leri minimumda tutulur ve
  manifest'te `license: "UNDETERMINED"` işaretlenir. Bkz. `LICENSE-DATA` § 3.

## Kapsam

M1 = yalnızca İzmir read-only provider + altyapı + pilot korpus. `onmuhasebe_mock`
ve tüm state makinesi M2'dedir — ancak state **arayüzleri** M1'de yazılır
(read-only için null implementasyon), böylece M2 `Example` şemasını kırmaz.

100 örnek bir **pilottur, benchmark değildir**; dataset card bunu açıkça
söylemelidir. Bu proje ilk Türkçe function-calling veri seti değildir (HF'de 8
tane var, en büyüğü 41k satır) — farkı execution-verified ve stateful olmasıdır.
