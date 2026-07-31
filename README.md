# ToolCall-TR

**A Verifiable Tool-Calling Data Generation Framework for Turkish and Turkey-Specific APIs**

Türkiye'ye özgü gerçek API şemalarından **execution-verified**, **policy-aware**,
**observation-grounded** ve **yeniden üretilebilir** Türkçe tool-calling veri
setleri üreten açık kaynak bir veri mühendisliği platformu.

> **Durum:** Mevcut 1.000 örneklik çıktı yeniden denetimde **smoke artefaktı**
> olarak sınıflandırıldı; eğitim veya yayın verisi değildir. 384 tekrar, eksik
> semantik/politika doğrulaması ve temsil etmeyen splitler giderilmeden release
> üretilemez. Sıradaki eşik 100–200 örneklik insan denetimli ücretli pilottur.

---

## Ayırt edici iddia

> Veri setindeki **her tool çağrısı gerçek bir implementasyon tarafından
> çalıştırıldı ve çıktısı doğrulandı. Hiçbir tool çıktısı bir LLM tarafından
> yazılmadı.**

Bu, "geçerli JSON üreten" bir sistem değildir. LLM yalnızca doğal Türkçe
kullanıcı ifadesini yazar; ground-truth tool çağrıları kod tarafından
deterministik olarak derlenir, gerçekten çalıştırılır ve bağımsız validator'lar
tarafından denetlenir.

## Bu neden gerekliydi?

Hugging Face'te **zaten 8 Türkçe function-calling veri seti var** (en büyüğü
41.480 satır). ToolCall-TR ilk olduğu için değil, şunlara sahip **ilk** olduğu
için var:

| | Mevcut TR veri setleri | ToolCall-TR |
|---|---|---|
| Kaynak | Çeviri veya İngilizce tool kataloğu | Türkiye'ye özgü gerçek API'ler |
| Tool çıktısı | LLM tarafından yazılmış | Gerçek çalıştırma ile üretilmiş |
| Doğrulama | Şema geçerliliği | Şema + execution + state + observation |
| Yeniden üretilebilirlik | — | Cassette + donmuş saat + seed |
| Benchmark | — | Family/tool/provider holdout profilleri + güvenlik eval seti |

## Mimari

```
Blueprint ──[planner: saf, I/O yok]──> CallPlan
CallPlan  ──[runner: I/O, deterministik]──> Trace
Trace     ──[validators: saf]──> ValidationResult ──> Example
```

Ayrıntı ve tasarım gerekçeleri için [`CLAUDE.md`](CLAUDE.md).

### Yeniden üretilebilirlik

Gerçek zamanlı bir API her çağrıda farklı veri döndürür — bu, doğrulanabilir
bir veri seti ile doğrudan çelişir. Çözüm bir **cassette (record/replay)**
katmanıdır: her HTTP yanıtı içerik-adresli olarak kaydedilir, pipeline replay
modunda çalışır ve **CI ağa hiç çıkmaz**. Buna donmuş saat ve sıradan bağımsız
seed türetimi eklendiğinde `run` iki kez çalıştırıldığında birebir aynı
`trace_id` üretilir.

## Sağlayıcılar

| Sağlayıcı | Mod | Üretim durumu |
|---|---|---|
| `general_local` hesaplama ve saat | `derived_local` | Etkin |
| `calendar_mock` sentetik takvim | `simulated` + stateful | Etkin; state doğrulamalı |
| GeoNames Türkiye + resmî tatil snapshot'ları | `derived_local` | Etkin |
| MET Norway + şehir snapshot'ı | `live_recorded` + `derived_local` | Etkin |
| Frankfurter (`providers=ECB`) | `live_recorded` | Etkin |
| USGS Earthquake | `live_recorded` | Etkin |
| World Bank WDI (`source=2`) | `live_recorded` + allowlist | Etkin |
| GBIF (CC0 / CC BY filtreli) | `live_recorded` | Etkin |
| Türkçe Vikipedi ve Wikidata metadata | `live_recorded` | Etkin |
| GitHub ve Crossref metadata | `live_recorded` | Etkin |
| İzmir Açık Veri / ESHOT | `live_recorded` | 8 blueprint arşivde; varsayılan üretimde kapalı |
| `onmuhasebe_mock` (kurgusal ön muhasebe) | `simulated` | Test fixture'ı; üretim sorularından çıkarıldı |

`onmuhasebe_mock` **tamamen kurgusaldır**. Hiçbir ticari sağlayıcı ile
bağlantısı yoktur, hiçbir sağlayıcının şeması veya dokümantasyonu
kullanılmamıştır ve rezerve `.test` TLD'sini kullanır.

CKAN veritabanı arama/sorgulama ve ön muhasebe sipariş/fatura aileleri üretim
blueprint kataloğunda yer almaz. Registry ve adapter kodları geriye uyumluluk
ile birim testleri için korunur; yeni veri üretimi bu araçları ground-truth
olarak seçmez.

## Kurulum

```bash
uv sync --all-extras
uv run pytest -q
```

Testler ve varsayılan pipeline **API anahtarı olmadan** çalışır: HTTP çağrıları
cassette'lerden gelir, doğal dil üretimi deterministik template kullanır.

OpenAI kullanımı isteğe bağlıdır; güvenli varsayılan çevrimdışı template
üreticisidir. Model rolleri, ücretli çağrı onayı, bütçe/cache, provenance ve
ground-truth güven sınırları için
[`docs/OPENAI_INTEGRATION.md`](docs/OPENAI_INTEGRATION.md) belgesine bakın.
Eski iki aşamalı çeviri/üretim altyapısından hangi parçaların taşındığı
[`docs/LEGACY_TRANSLATION_MIGRATION.md`](docs/LEGACY_TRANSLATION_MIGRATION.md)
belgesinde açıklanır.
Sistemin uçtan uca akışı ve yeni bir API/provider ekleme kontrol listesi için
[`docs/ADDING_API_PROVIDER.md`](docs/ADDING_API_PROVIDER.md) belgesine bakın.

## Kullanım

Tek adımda üretim (ağ gerekmez):

```bash
uv run toolcall-tr generate
```

100 örneklik çevrimdışı smoke canary üretimi:

```bash
uv run toolcall-tr generate-canary --profile smoke --target 100
```

Smoke profili yapısal pipeline'ı sınar; çıktısı tek başına eğitim/yayın onayı
değildir. Release profili tekrarları bloklar ve `semantic_valid`,
`policy_valid`, `language_valid` alanlarının tüm kayıtlarda `true` olmasını
zorunlu tutar. Canary kota planı karar, senaryo türü, zorluk, tool çağrı
sayısı ve split oranlarını API çağrısından önce dengeler. Hakem bir adayı
reddederse ret nedeni aynı planlanmış family'nin sonraki üretimine onarım
geri bildirimi olarak verilir:

```bash
uv run toolcall-tr generate-canary \
  --profile release \
  --generator openai \
  --judge \
  --allow-paid-api
```

OpenAI soru üretimi, kısa karar gerekçesi ve ek hakem doğrulaması:

```bash
uv run toolcall-tr generate --generator openai --judge --allow-paid-api
```

Fazları ayrı ayrı çalıştırmak için:

```bash
uv run toolcall-tr build-registry
uv run toolcall-tr plan
uv run toolcall-tr run
uv run toolcall-tr validate
uv run toolcall-tr export --format xlam
uv run toolcall-tr quality-report
uv run toolcall-tr stats
uv run toolcall-tr cassette verify
```

Tool-call eğitim çıktılarında iki açık OpenAI görünümü vardır:

- `openai_call_only`: İlk tool seçim kararında durur; observation veya final
  yanıt içermez.
- `openai_trajectory`: Tool çağrıları, observation mesajları ve yalnız son
  observation'dan deterministik türetilmiş Türkçe final assistant yanıtını
  taşır.

`reasoning_summary_tr` yalnız kısa ve denetlenebilir karar özetidir; ham veya
gizli düşünce zinciri hiçbir görünüme eklenmez. Blueprint modeli
`interaction_type: single_turn|multi_turn` ve çok turlu tek amaç için
deterministik `conversation_prefix` sözleşmesini destekler.

### Genelleme holdout profilleri

Varsayılan `standard` split family-disjoint davranışını korur ve train/test tool
ile sağlayıcı kesişimini raporlar. Gerçek genelleme benchmark'ları için canary
komutunda ayrıca `--holdout-profile unseen_tool` veya
`--holdout-profile unseen_provider` seçilebilir. Seçilen eksende train ve test
kesişimi sıfır değilse canary kapısı kapanır; ölçüm
`generalization_report.json` içinde tool, provider ve family listeleriyle
yayınlanır. Ölçüm yalnız çağrılan aracı değil, modele gösterilen bütün tool
şemalarını kapsar.

### Eğitime kapalı güvenlik eval'leri

Sentetik tool-output prompt-injection vakaları
`data/evaluation/security/` altındadır. Kullanıcı amacı, güvenilmez araç çıktısı,
çıktıya gömülü talimat ve beklenen gözlenebilir davranış ayrı alanlardadır. Bu
kayıtlarda `training_eligible=false` şema tarafından zorlanır; gizli düşünce
zinciri tutulmaz. Release artifact manifesti eğitim ve rapor dosyalarını ayrı
sınıflandırır ve `evaluation` ağacındaki bir dosyanın eğitim girdisi olarak
işaretlenmesini reddeder.

Cassette kaydı **kasıtlı ve açık** bir eylemdir; hiçbir CLI komutu ağa çıkmaz:

```bash
uv run python scripts/record_ckan_cassettes.py
```

## Mevcut durum

Varsayılan Türkiye geneli katalogda 35 kayıtlı tool ve üretimde etkin 74
blueprint/family vardır. İzmir'e özgü 8 eski blueprint arşive taşınmıştır. Eski 1.000 kayıt,
boru hattı ile cassette yürütmesini sınar; ancak 616 benzersiz soru, 384 tekrar,
yalnız 19 çağrı planı ve 18 observation dizisi içerir. Semantik, politika ve
doğal dil doğrulamaları bu koşuda yapılmamıştır. Bu nedenle çıktı
`data/archive/invalid-canary-1000-20260729` altına karantinaya alınmıştır ve
eğitim/yayın girdisi değildir. Ayrıntılı bulgular, kalite sözleşmesi ve uygulama
sırası için [kalite kurtarma planına](docs/QUALITY_RECOVERY_PLAN.md) bakın.

İlk family genişletme aşamasındaki doğrulanmış çevrimdışı smoke koşusu
`data/smoke/current-100-v4` altında
100/100 kabul, 100 benzersiz soru ve sıfır duplicate ile tamamlanmıştır.
Bu koşuda dört karar türü train, validation ve test'in her birinde
bulunur; 35 no-call kaydının tamamında asistan hedefi vardır. Rapor açıkça
`release_ready=false` yazar; ücretli hakem ve insan denetiminin yerine geçmez.

Pilot hazırlığı sonrasında katalog Türkiye geneli yer, takvim, hesaplama,
bibliyografik metadata ve kamu verisi senaryolarıyla genişletilmiştir. Güncel
varsayılan katalog 74 aktif family'dir.

Veritabanı/açık veri sorguları ile sipariş/fatura senaryoları aktif blueprint
kapsamından çıkarılmıştır. Eski pilot, cache, trace ve SFT dosyaları da yeni
release manifestine otomatik olarak dahil edilmemelidir.

## Kişisel veri politikası

Sentetik kimlik numaraları kasıtlı olarak **geçersiz** aralıklardan üretilir:
TCKN'ler `0` ile başlar (gerçek bir TCKN başlayamaz), VKN'ler checksum-geçersiz,
IBAN'lar mod-97-geçersizdir. `PIIScanner` validator'ı hem üretilen örnekleri hem
de cassette'leri tarar; gerçek checksum'ı geçen herhangi bir tanımlayıcı CI'ı
kırar.

## Lisans

- **Kod:** Apache-2.0 — [`LICENSE`](LICENSE)
- **Veri:** CC BY 4.0 — [`LICENSE-DATA`](LICENSE-DATA)

Veri; ESHOT, MET Norway, ECB/Frankfurter, USGS, World Bank, GBIF, Wikimedia,
GitHub metadata yüzeyi ve lisanslı yerel snapshot'lardan türetilmiştir. Kaynak
bazlı atıf yükümlülükleri ve yapılan değişikliklerin listesi `LICENSE-DATA` ile
`legal/DATA_SOURCES.md` belgelerindedir.

> `openapi.izmir.bel.tr` (ESHOT gerçek zamanlı) için beyan edilmiş bir lisans
> bulunamamıştır. Bu **yayın öncesi çözülmesi gereken açık bir maddedir**; ilgili
> cassette'ler ayrı tutulur ve `UNDETERMINED` işaretlenir.

## Atıf ve bağımsızlık

Bu proje Salesforce tarafından geliştirilmemiştir ve Salesforce ile bağlantısı
yoktur. APIGen, APIGen-MT, When2Call, ToolACE, ToolMind, BFCL ve τ-bench açıkça
atıf verilen metodolojik referanslardır; fikirleri yeniden uygulanmış,
artefaktları kopyalanmamıştır. Bkz. [`NOTICE.md`](NOTICE.md) ve
[`legal/CITATIONS.md`](legal/CITATIONS.md).
