# ToolCall-TR kalite kurtarma planı

Tarih: 29 Temmuz 2026

## Türkiye geneli 35 araç revizyonu

Kullanıcı onayıyla production kapsamı İzmir pilotundan Türkiye geneli ve genel
amaçlı araç kullanımına taşınmıştır. Yeni hedef **35 aktif araçtır**:

| Katman | Araç |
|---|---:|
| Hava durumu | 2 |
| Döviz | 3 |
| Afet | 1 |
| İstatistik | 2 |
| Biyoçeşitlilik | 3 |
| Türkçe Vikipedi metadata | 3 |
| GitHub metadata | 3 |
| GeoNames Türkiye | 4 |
| Wikidata | 3 |
| Crossref | 2 |
| Güvenli web metadata federasyonu | 2 |
| Türkiye resmî tatilleri | 2 |
| Hesaplama ve saat | 2 |
| Sentetik kişisel takvim | 3 |
| **Toplam** | **35** |

İzmir CKAN/ESHOT/snapshot, eski `weather.search_location` ve ön muhasebe
araçları production registry'ye girmez. Kod/cassette arşivi geçmiş koşuların
denetlenmesi için tutulabilir; release manifesti bunları dışlar.

### Yeni davranış sözleşmesi

- Her tool-call trajectory'si doğrulanmış terminal observation'a dayalı final
  asistan mesajıyla biter.
- Call-selection ve tam agent trajectory ayrı export edilir.
- Çok turlu örnekler tek kullanıcı amacını korur.
- Paralel çağrı yalnız aynı amacın bağımsız alt çağrıları için kullanılır.
- Beklenen hata, hata sonrası toparlanma, açık onay ve kullanıcı iptali ayrı
  blueprint türleridir.
- Ham/gizli düşünce zinciri yayımlanmaz; `reasoning_summary_tr` yalnız kısa,
  gözlenebilir karar özetidir.
- Web araması snippet veya sayfa içeriği değil, allowlist metadata'sı döndürür.
- Tool-output prompt injection vakaları eğitimden ayrı security eval katmanında
  tutulur.

### Hedef dağılım

Birbirini dışlayan çağrı yapısı hedefi:

| Yapı | Hedef |
|---|---:|
| No-call | %30 |
| Tek çağrı | %45 |
| Bağımlı sıralı çağrı | %18 |
| Bağımsız paralel çağrı | %7 |

Kesişen davranış hedefleri: çok turlu `%12–15`, stateful yaklaşık `%10`,
beklenen hata/toparlanma `%8–10`, onay/iptal `%6–8`.

### Güncel uygulama sırası

1. 35 araçlık registry ve environment kablolamasını tamamla.
2. İzmir/ön muhasebe/eski konum araçlarını production yolundan çıkar.
3. Yeni davranış blueprintlerini planner/runner ile çalıştır.
4. Schema çeşitliliği ve unseen-tool/unseen-provider eval kapılarını ekle.
5. 200 örneklik çevrimdışı smoke canary'yi sıfır retle geçir.
6. `gpt-4.1-mini` üretici + `gpt-5-mini` hakem ile ücretli 200 release pilotu
   çalıştır.
7. En az 100 örneği katmanlı insan incelemesine gönder.
8. Yalnız bu kapılardan sonra 1.000 release candidate üret.

Bu belge, mevcut kodun, aktif blueprint kataloğunun, üretilmiş 1.000
örneklik canary'nin ve kullanıcı tarafından sağlanan araştırma raporunun
yeniden denetlenmesi sonucunda hazırlanmıştır.

## Karar

Eski `data/canary` çıktısı yalnızca çevrimdışı boru hattının çalıştığını
gösteren bir **smoke artefaktıdır**. Eğitim, model karşılaştırması veya yayın
verisi olarak kullanılmamalıdır; bu nedenle
`data/archive/invalid-canary-1000-20260729` altına karantinaya alınmıştır.

Bunun nedeni yürütmenin çalışmaması değildir. Araç çağrıları gerçekten
çalıştırılmıştır; fakat soru çeşitliliği, semantik doğrulama, no-call hedefleri,
split temsiliyeti ve artefakt bütünlüğü release düzeyinde değildir.

## Ölçülen durum

| Ölçüt | Sonuç |
|---|---:|
| Toplam kayıt | 1.000 |
| Birebir benzersiz kullanıcı sorusu | 616 |
| Fazladan yinelenen satır | 384 |
| Aktif blueprint / family | 20 / 20 |
| Yazılmış kaynak soru | 52 |
| Canary'de kullanılan kaynak soru | 20 |
| Benzersiz çağrı planı | 19 |
| Benzersiz observation dizisi | 18 |
| `semantic_valid=true` | 0 |
| `policy_valid=true` | 0 |
| `language_valid=true` | 0 |
| Clarification/cannot-answer asistan hedefi | 0 / 57 |
| Direct-answer örneği | 0 |

Splitler family-disjoint olsa da temsil edici değildir:

- Train: 700 kayıt; yalnız `tool_call`.
- Validation: 100 kayıt; tek family ve tek alan; 68 birebir tekrar.
- Test: 200 kayıt; bütün clarification ve cannot-answer örnekleri burada.

Kök `data/sft` dosyaları da güncel canonical çıktı ile aynı koşuya ait değildir.
Bu nedenle klasör glob'ları eğitim girdisi olarak kullanılmamalıdır.

## Raporla uyumlu veri katmanları

Tek bir karışık çıktı yerine dört ayrı artefakt profili kullanılacaktır:

1. `call_selection`: Kullanıcı amacı ve doğru araç/argüman seçimi.
2. `decision_policy`: `tool_call`, `clarification`, `direct_answer` ve
   `cannot_answer` davranışları.
3. `agent_trajectory`: Observation'a bağlı ardışık çağrılar ve hata kurtarma.
4. `benchmark`: Eğitim family'leriyle kesişmeyen, ayrıca insan denetimli test.

Benchmark katmanı üç açık holdout profili taşır: `standard` yalnız family
ayrıklığını zorlar; `unseen_tool` train/test tool şeması kesişimini,
`unseen_provider` ise sağlayıcı kesişimini sıfıra indirir. Her profil iki
kesişimi de ölçüp raporlar. Tool-output prompt-injection güvenlik kayıtları
`data/evaluation/security/` altında sentetik ve `training_eligible=false`
olarak tutulur; release eğitim manifestine alınmaları politika hatasıdır.

Tek kullanıcı amacı için iki bağımlı araç çağrısı geçerlidir. Engellenecek olan,
tek mesajdaki bağımsız birden fazla amaç ve iç uygulama planının kullanıcı
cümlesine sızmasıdır.

## Release kalite sözleşmesi

### Kayıt düzeyi

Release adayındaki her kayıt:

- tek bağımsız kullanıcı amacı taşımalı;
- araç adını, snake_case adı veya iç sorgu sözdizimini doğal dile sızdırmamalı;
- available tool kapasitesinin karşılayamadığı ETA, insan sayısı, yürüyüş süresi
  veya kesinlik iddiası taşımamalı;
- bütün kullanıcı-kökenli argümanları metinde açıkça veya kanıtlanabilir biçimde
  türetilmiş olarak taşımalı;
- yapısal, registry, grounding, PII ve execution kontrollerini geçmeli;
- release profilinde semantik, politika ve dil kontrolleri yapılmış ve `true`
  olmalı;
- bağımlı çağrıları `assistant call → tool result` sırasıyla yürütmeli;
- no-call kararında gerçek bir asistan hedef mesajı taşımalıdır.

### Tekrar ve çeşitlilik

- Exact duplicate: 0
- Normalize duplicate: 0
- Eşik üstü near-duplicate: 0
- Yalnız genel ön ek/sonek eklenmiş sözde varyant: 0
- 1.000 kayıt öncesinde en az 100–200 bağımsız semantik scenario/argument
  kompozisyonu
- Trace ID yanında benzersiz soru, çağrı planı ve observation sayısı raporu

### Split ve karar dengesi

Her karar türü için en az üç, tercihen beş bağımsız family oluşturulmadan
family-disjoint train/validation/test yayını yapılmayacaktır.

Başlangıç hedefleri:

| Karar | Oran |
|---|---:|
| `tool_call` | %60–75 |
| `clarification` | %8–15 |
| `direct_answer` | %8–15 |
| `cannot_answer` | %5–12 |

| Çağrı sayısı | Oran |
|---|---:|
| 0 | %20–35 |
| 1 | %45–60 |
| 2 | %15–30 |
| 3+ | pilotta 0 veya çok düşük |

Validation en az dört alan, sekiz family ve dört karar türünü kapsamalıdır.
Family kesişimi her zaman sıfır olmalıdır.

### Artefakt bütünlüğü

- Üretim önce staging dizinine yazılır.
- Yalnız bütün release kapıları geçerse kalıcı release dizinine taşınır.
- Başarısız koşu quarantine altında tutulur.
- Canonical, OpenAI, ShareGPT ve xLAM ID kümeleri ve satır sayıları eşit olur.
- Manifest her dosyanın hash'ini, kaynak manifest hash'ini, pipeline/prompt
  sürümünü, model provenance'ını ve Git SHA'yı taşır.
- `pilot`, `llm_cache`, `cassettes`, `traces` ve eski SFT dosyaları eğitim
  manifestine otomatik olarak giremez.

## Uygulama sırası

### P0 — ücretli pilottan önce

1. Bağımlı çağrı mesaj sırasını düzelt ve regresyon testi ekle. **Tamamlandı.**
2. Sayı/kısa kod grounding alt-dize açığını kapat. **Tamamlandı.**
3. No-call kararlarına gerçek asistan hedefi ekle. **Tamamlandı.**
4. 52 kaynak soruyu araç kapasitesi, tek amaç ve doğal Türkçe açısından düzelt.
   **Tamamlandı.**
5. Smoke ve release kalite profillerini ayır. **Tamamlandı.**
6. Release profilinde duplicate ve eksik semantik doğrulamayı blokla.
   **Tamamlandı.**
7. Güncel olmayan kök SFT çıktılarını release yolundan çıkar. **Tamamlandı.**
8. Staging → gate → promotion akışını ekle. **Tamamlandı.**

### P1 — 100–200 örneklik ücretli pilot

1. Her karar türünde ve her splitte yeterli family oluştur. **Tamamlandı:
   74 aktif family, her splitte dört karar türü ve 35/35 araç için gerçek
   çağrı kapsamı vardır; zincirler replay edilebilir cassette veya sürümlü
   yerel snapshot üzerinde yürür.**
2. `gpt-4.1-mini` ile bağımsız doğal Türkçe sorular üret. **Tamamlandı.**
3. Deterministik kontrollerden geçenleri ToolSpec kapasitesini de gören
   `gpt-5-mini` hakemine gönder. **Tamamlandı.**
4. Hakeme `single_intent`, `capability_supported`, `no_internal_plan`,
   `decision_correct` ve `required_constraints_preserved` ölçütlerini ekle.
   **Tamamlandı (judge v3).**
5. 200 kabul hedefi için bütçe içinde sınırlı replenishment kullan; yalnız 200
   aday üretip retleri hedef kaybı sayma. **Tamamlandı: kota planı üretimden
   önce kurulur; ret edilen koltuk aynı family ve judge geri bildirimiyle
   yeniden üretilir.**
6. Ret aşaması, ret nedeni, generator/judge token kullanımı ve cache durumunu
   kayıt bazında sakla. **Tamamlandı.**
7. Pilotun tamamını veya en az 100 katmanlı örneği insan incelemesine gönder.

Pilot, açık kullanıcı onayı olmadan çalıştırılmaz.

### P2 — 1.000 release candidate

1. Pilot ölçümlerine göre istek/token bütçesini yeniden hesapla.
2. 100–200 bağımsız semantik scenario/argument kompozisyonuyla 1.000 kayıt üret.
3. Karar, alan, zorluk ve çağrı sayısına göre katmanlı split manifesti oluştur.
4. Bütün formatları aynı koşudan atomik biçimde yayınla.
5. Release raporu ve dataset card'ı yalnız üretilen manifestten türet.

### P3 — 5.000 ve 10–15.000 ölçeği

1. Domain ve provider kapsamını lisans ve kalite kapılarıyla genişlet.
2. `agent_trajectory` ve hata kurtarma verisini call-selection verisinden ayrı
   üret.
3. Family-disjoint ve insan denetimli benchmark oluştur.
4. Ancak 1.000 release candidate kalite ve maliyet eşiklerini geçtikten sonra
   5.000, ardından 10–15.000 ölçeğine çık.

## Pilot bütçesi

Mevcut pilot bütçesi:

```yaml
budget:
  max_requests: 450
  max_input_tokens: 400000
  max_output_tokens: 120000
```

Bu bir harcama hedefi değil, sert güvenlik tavanıdır. 200 kabul için her adayda
bir generator ve deterministik kontrolden geçenlerde bir judge çağrısı gerekir.
Ret ve yeniden doldurma nedeniyle teorik taban yaklaşık 400 istektir; 450 tavanı
sınırlı hata payı bırakır. Pilot sonunda gerçek p50/p95 token kullanımı ve ret
oranı ölçülmeden 1.000 kayıt bütçesi belirlenmeyecektir.

## Gönderilen araştırma raporuna notlar

Raporun ana ilkeleri sisteme doğrudan uygulanacaktır:

- schema doğruluğu ile semantik doğruluk ayrılmalıdır;
- sentetik ölçekleme doğrulanabilir olmalıdır;
- turn-level filtre yalnız rol sırası değildir;
- When2Call karar verisi ayrı ve dengeli bir katmandır;
- tek turlu function-selection ile çok turlu agent trajectory karıştırılmaz.

Raporda When2Call test büyüklüğü bir yerde 3.652, bir tabloda 3.952 olarak
geçmektedir. Ayrıca çözümlenmemiş `filecite` işaretleri vardır. Bu iki nokta
metodolojik yönü değiştirmez, fakat rapor kaynak olarak yayımlanacaksa
düzeltilmelidir.
