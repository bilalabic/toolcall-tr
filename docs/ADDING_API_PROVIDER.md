# ToolCall-TR işleyişi ve yeni API kaynağı ekleme rehberi

## Sistem nasıl çalışır?

Her veri kaydı aşağıdaki güven zincirinden geçer:

```text
Blueprint
  → deterministik korpus kota planı
  → deterministik CallPlan
  → cassette/snapshot üzerinde gerçek araç yürütmesi
  → Trace
  → Türkçe kullanıcı sorusu
  → deterministik validator'lar
  → gpt-5-mini judge (release profilinde)
  → korpus bütçesi ve split kapıları
  → staging
  → canonical + OpenAI + ShareGPT + xLAM
  → yalnız bütün kapılar geçerse promotion
```

### 1. Blueprint

Blueprint modelden bağımsız doğruluk sözleşmesidir. Şunları belirtir:

- kullanıcının tek nihai amacı;
- bilinen ve bilerek eksik bırakılan bilgiler;
- modele sunulacak araçlar;
- beklenen karar;
- araç çağrıları ve her argümanın kaynağı;
- no-call kararında gerçek asistan hedefi;
- family ve split.

LLM hiçbir zaman doğru araç çağrısını üretmez. Doğru çağrı blueprint'ten kodla
derlenir.

### 2. Planlama

Planner blueprint'i registry ile karşılaştırır. Bilinmeyen araç, parametre,
geçersiz observation referansı veya karar/çağrı çelişkisi varsa daha API
çalıştırılmadan plan reddedilir.

### 3. Gerçek yürütme

Araç adaptörü çağrıyı normalize eder ve gerçek cevap biçimine dönüştürür.
Normal üretim `REPLAY` modundadır; internete çıkmaz. Daha önce kontrollü olarak
kaydedilmiş cassette veya sürümlenmiş yerel snapshot kullanılır.

Bağımlı çağrılar şu sırayla saklanır:

```text
user
assistant(tool call 1)
tool(observation 1)
assistant(tool call 2)
tool(observation 2)
```

### 4. Soru üretimi

- Smoke: sınırlı kapasiteli deterministik template.
- Release: `gpt-4.1-mini`.

Model yalnız kullanıcı sorusunu ve kısa, denetlenebilir karar özetini üretir.
Araç çağrısını veya sonucunu değiştiremez. Template kapasitesi dolunca başa
dönüp tekrar üretmez. Hakem veya deterministik kontrol bir adayı reddederse
ret nedenleri bir sonraki OpenAI üretimine sınırlı onarım notu olarak eklenir;
modelden yeni ground-truth istenmez.

### 5. Doğrulama

Deterministik kontroller:

- format ve model sözleşmesi;
- JSON Schema;
- registry;
- argüman grounding;
- açık onay;
- PII;
- execution;
- konuşma sırası;
- tool observation;
- dil artıkları;
- exact/normalized/near duplicate.

Release hakemi ayrıca şunların tamamını doğrular:

- semantik uyum;
- politika uyumu;
- doğal Türkçe;
- tek bağımsız amaç;
- aracın isteği gerçekten karşılayabilmesi;
- iç araç planının kullanıcı diline sızmaması;
- doğru tool/no-tool kararı;
- zorunlu değer ve kısıtların korunması.

### 6. Replenishment ve bütçe

Karar, senaryo türü, zorluk, tool çağrı sayısı ve split kotaları API
çağrısından önce planlanır. Katalog bu kotaları karşılayamıyorsa ücret
harcanmadan açık hata verilir.

Release üretiminde ret edilen aday hedef sayısından düşmez. Dağılımı
bozmamak için aynı planlanmış family'nin yeni varyantı, önceki ret
gerekçeleriyle yeniden üretilir. Döngü şu üç koşuldan birinde durur:

- her split kabul hedefini doldurur;
- `--max-candidates` tavanına ulaşır;
- istek veya token bütçesi dolar.

200 kabul için varsayılan aday tavanı 225'tir. `max_requests: 450`, her aday
için en fazla bir generator ve bir judge çağrısına sert üst sınır koyar.

### 7. Yayın

Koşu önce `reports/.../.runs/<run-id>` staging alanına yazılır. Başarısız koşu
kalıcı çıktının üzerine yazamaz. Yalnız gate geçerse canonical ve bütün SFT
formatları hedef dizine taşınır.

## Yeni bir API kaynağı nasıl eklenir?

### A. Kaynağı kabul etmeden önce

Önce şu sorular yanıtlanır:

1. Resmî veya güvenilir bir upstream mi?
2. Kullanım ve yeniden dağıtım lisansı açık mı?
3. Kimlik doğrulama gerekiyor mu?
4. Kişisel veri döndürebilir mi?
5. Yanıt yeniden üretilebilir biçimde kaydedilebilir mi?
6. Araç gerçek bir kullanıcı ihtiyacını karşılıyor mu?
7. Aynı yetenek mevcut bir provider'da zaten var mı?

Lisans belirsizse provider kodu test amacıyla bulunabilir; fakat release
mixture'ına alınmaz.

### B. Provider paketi

Yeni paket:

```text
src/toolcall_tr/providers/<provider_name>/
  __init__.py
  <capability>.py
```

Modül şu parçaları tanımlar:

- namespace;
- lisans ve atıf;
- kaynak URL ve şema sürümü;
- `ToolSpec`;
- HTTP request builder;
- response normalizer;
- adapter.

Araç şeması dar tutulmalıdır:

- `additionalProperties: false`;
- gerekli parametreler açık;
- enum/min/max/pattern sınırları;
- çıktı alanları ve semantik tipleri;
- boş sonuç izni;
- read/write ve onay gereksinimi;
- execution class.

API'nin ham yanıtı doğrudan eğitim verisine koyulmaz. Adapter yalnız gerekli,
kararlı ve lisanslanabilir alanları canonical cevaba dönüştürür.

### C. Registry ve environment

Provider araçları registry'ye eklenir; executor environment'a bağlanır.

Kontrol:

```bash
uv run toolcall-tr build-registry
```

Beklenti:

- tool ID çakışması yok;
- bilinmeyen parametre yok;
- registry hash deterministik.

### D. Cassette kayıt scripti

`scripts/record_<provider>_cassettes.py` oluşturulur.

Kurallar:

- normal pipeline hiçbir zaman canlı ağa çıkmaz;
- yalnız açık kayıt scripti `RECORD_MISSING` kullanır;
- kimlikli User-Agent ve makul timeout uygulanır;
- secret cassette'e yazılmaz;
- header'lar allowlist ile budanır;
- lisans/atıf ve upstream URL her kayıtta bulunur;
- bütün namespace'leri içeren manifest yeniden hesaplanır.

Kayıt:

```bash
uv run python scripts/record_<provider>_cassettes.py
uv run toolcall-tr cassette verify
```

### E. Blueprint family'leri

Tek bir API eklemek tek bir soru eklemek değildir. En az şu çeşitler
değerlendirilir:

- başarılı tek çağrı;
- geçerli boş sonuç;
- eksik parametre → clarification;
- araçsız cevaplanabilen istek → direct_answer;
- kapsam dışı istek → cannot_answer;
- yalnız gerçekten gerekliyse bağımlı iki çağrı.

Her family'de bütün utterance'lar aynı argüman varlığı ve kökenine sahip
olmalıdır. Kullanıcı aracın iç adımlarını söylemez; nihai amacını söyler.

### F. Testler

Asgari test paketi:

- request URL/parametre normalizasyonu;
- response normalizasyonu;
- hata ve boş sonuç;
- cassette replay;
- planner;
- grounding;
- PII;
- uçtan uca blueprint;
- exporter;
- lisans/envanter;
- ağsız çalışma.

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run lint-imports
```

### G. Smoke ve release

Önce ücretsiz smoke:

```bash
uv run toolcall-tr generate-canary \
  --profile smoke \
  --target 100 \
  --generator template
```

Smoke yalnız mekanik doğrulamadır.

Ücretli release pilotu:

```bash
uv run toolcall-tr generate-canary \
  --profile release \
  --target 200 \
  --max-candidates 225 \
  --generator openai \
  --judge \
  --allow-paid-api \
  --config configs/generation-pilot-200.yaml \
  --out data/pilot/release-200 \
  --reports reports/pilot/release-200
```

Son olarak karar/alan/çağrı sayısına göre katmanlı insan incelemesi yapılır.
İnsan incelemesi tamamlanmadan 1.000 veya daha büyük release üretilmez.

## Yeni provider için tamamlanma ölçütü

Bir API kaynağı ancak aşağıdakilerin tamamı sağlandığında “eklenmiş” sayılır:

- lisans ve atıf kaydı;
- dar ve sürümlü ToolSpec;
- gerçek adapter;
- kontrollü cassette/snapshot;
- registry bağlantısı;
- en az bir bağımsız family;
- provider ve E2E testleri;
- sıfır PII/unknown tool/unknown parameter;
- smoke başarısı;
- release pilotunda judge ve insan denetimi.
