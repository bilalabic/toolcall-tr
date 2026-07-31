# OpenAI entegrasyonu

ToolCall-TR'nin güvenli varsayılanı **çevrimdışı `template` üreticisidir**.
Standart `generate` ve `generate-canary` akışları OpenAI API anahtarı istemez,
ücretli model çağrısı yapmaz ve CI'da ağ erişimi olmadan çalışır.

OpenAI katmanı doğal Türkçe çeşitliliğini artırmak ve üretilen örnekleri ikinci
bir kalite kontrolünden geçirmek için isteğe bağlıdır:

| Rol | Varsayılan model | Yetki alanı |
|---|---|---|
| Soru üreticisi | `gpt-4.1-mini` | Blueprint kısıtlarından özgün Türkçe soru ve kısa karar gerekçesi üretir |
| LLM hakem | `gpt-5-mini` | Örneği tanımlı kalite ölçütlerine göre değerlendirir |

## Değişmez güven sınırı

LLM yalnızca doğal dil katmanına dokunabilir. Ground-truth tool adı,
argümanları, çağrı sırası, beklenen sonuç ve tool gözlemleri deterministik kod,
gerçek yürütme veya kayıtlı cassette tarafından oluşturulur.

OpenAI modeli:

- ground-truth üretmez veya değiştirmez;
- tool çıktısı uydurmaz;
- validator'ları atlayamaz;
- bir örneği tek başına kabul edilmiş veri haline getiremez.

Üretilen sorudaki korunması gereken değerler sonradan grounding ve diğer
deterministik validator'larla yeniden denetlenir. Hakem kararı da yapısal
kapıların yerine geçmez; yalnızca ek bir kalite sinyalidir.

Varsayılan `prompts.mode: synthesize` ayarında model, elle yazılmış ifadeyi
yalnız doğal dil referansı olarak kullanır ve blueprint'ten yeni soru yazar.
Geriye dönük karşılaştırma için `paraphrase` modu da korunur.

Model ayrıca `reasoning_summary_tr` üretir. Bu alan ham veya gizli düşünce
zinciri değildir; kullanıcının amacı ile beklenen üst düzey kararın en fazla üç
cümlelik, denetlenebilir özetidir. Exporter'lar eski tüketiciler için aynı
değeri `toolcall_tr.thinking` uyumluluk alanında da taşır. OpenAI `messages`
dizisine desteklenmeyen özel bir alan eklenmez.

## API ve yapılandırılmış çıktı

İstemci OpenAI **Responses API**'yi kullanır. Her istek veri saklamayı açıkça
`store=false` ile kapatır. Düz metin üretiminin yanında, hakem ve kontrollü
paraphrase yanıtları için strict JSON Schema structured output desteklenir:

1. JSON Schema API çağrısından önce yerelde doğrulanır.
2. Şema Responses API'ye `strict=true` ile gönderilir.
3. Dönen metin JSON olarak ayrıştırılır ve aynı şemaya karşı yeniden doğrulanır.
4. Geçersiz veya eksik yanıt koşuyu görünür bir hatayla durdurur.

Reasoning effort ve verbosity role göre ayrı ayarlanabilir. Üretici için düşük
maliyetli ayarlar, hakem için daha güçlü muhakeme ayarı kullanılabilir; bunlar
ground-truth üzerindeki yetki sınırını değiştirmez.

## Kimlik bilgileri ve ücretli çağrı onayı

`OPENAI_API_KEY` yalnızca ortam değişkeninden okunur. Anahtarı YAML dosyasına,
komut satırı argümanına, prompt'a, cache'e veya veri provenance'ına yazmayın.
İstemci metadata'sı API anahtarını ya da OpenAI yanıt kimliğini taşımaz.

Ücretli OpenAI çağrısı CLI'da **açık opt-in** gerektiren bir işlemdir. Yalnız
`configs/generation.yaml` içinde sağlayıcı/model değiştirmiş olmak ücretli
çağrıya onay sayılmaz.

Çevrimdışı varsayılan:

```text
toolcall-tr generate
```

OpenAI soru üretimi ve `gpt-5-mini` hakemi birlikte:

```text
toolcall-tr generate --generator openai --judge --allow-paid-api
```

Yalnız hakemi template üretimi üzerinde çalıştırmak da mümkündür:

```text
toolcall-tr generate --generator template --judge --allow-paid-api
```

Aynı seçenekler `generate-canary` komutunda da bulunur. Büyük bir hedefte
üretici ve hakem örnek başına iki istek oluşturabileceği için
`llm.budget.max_requests` sınırını hedefe göre bilinçli biçimde ayarlayın.

## Bütçe ve yeniden kullanım

`configs/generation.yaml` istek, girdi token'ı ve çıktı token'ı için sert koşu
bütçelerini tanımlar. Sınır aşımı sessiz bir model/template geçişi yapmaz;
koşu görünür bir hatayla durur. Başarılı koşunun gerçek API kullanımı
`reports/llm_usage_report.json` dosyasına yazılır.

İçerik-adresli LLM cache anahtarına şu alanlar girer:

- prompt sürümü;
- blueprint kimliği;
- blueprint içerik hash'i;
- varyant indeksi;
- sağlayıcı;
- model.

Bu sayede aynı üretim yeniden çalıştırıldığında gereksiz ücret oluşmaz; bir
blueprint düzenlendiğinde eski soru yanlışlıkla yeniden kullanılmaz; model
karşılaştırmalarında bir modelin yanıtı diğerine yanlışlıkla verilmez. Cache
isabeti, OpenAI'nin prompt-prefix cache token sayısından ayrı tutulur.

## Provenance

LLM kullanılan örneklerde provenance en az sağlayıcı, model, prompt sürümü,
temperature, girdi/çıktı token sayıları, sağlayıcı tarafı cached-input token
sayısı ve yerel cache isabetini taşıyabilir. API anahtarı, ham güvenlik
tanımlayıcısı ve OpenAI yanıt kimliği provenance'a yazılmaz.

Generator provenance'ı yalnız kullanıcı sorusunun ve kısa karar gerekçesinin
doğal dil üretimini açıklar. Tool çağrısı ve gözlem provenance'ı deterministik plan, trace,
cassette/snapshot hash'leri ve validator kayıtlarından gelir.

## Hakem sınırlaması

Üretici `gpt-4.1-mini`, hakem `gpt-5-mini` olduğundan aynı sağlayıcı içinde
farklı modeller kullanılır. Bu, aynı modelin kendi çıktısını kayırması riskini
azaltır; ancak sağlayıcıya özgü ortak eğilimleri ortadan kaldırmaz ve tam
bağımsız hakem sayılmaz.

Sonuçlar yayımlanırken bu sınırlama dataset card'da belirtilmeli; kritik veya
uyuşmazlıklı örnekler deterministik kontroller ve gerektiğinde insan incelemesi
ile ele alınmalıdır.
