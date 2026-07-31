# Eski üretim altyapısından alınan kararlar

İncelenen eski `toolcall-dataset` projesi iki aşamalı bir akış kullanıyordu:

1. Model konu/senaryodan soru ve tool şemaları üretiyordu.
2. Başka bir çağrı `thinking`, tool çağrıları, varsayımsal tool sonuçları ve
   nihai cevabı üretiyordu.

Mevcut ToolCall-TR hattına yararlı fikirler taşındı:

- Soru üretiminin ayrı bir model rolü ve provenance kaydı olması.
- Yapılandırılmış JSON çıktı kullanılması.
- Soru ve değerlendirme aşamalarının ayrı ölçülmesi.
- Eski tüketiciler için `thinking` alanı uyumluluğu.

Taşınmayan davranışlar:

- LLM'in tool şeması üretmesi.
- LLM'in ground-truth çağrı veya argüman belirlemesi.
- LLM'in tool sonucu uydurması.
- Uzun, birinci tekil şahıs, adım adım gizli düşünce zinciri üretmesi.
- JSON'u kod bloğundan düzenli ifadeyle kurtarıp sessizce kabul etme.

Yeni tasarımda `gpt-4.1-mini`, doğrulanmış blueprint'ten yalnızca:

- `query`: özgün Türkçe kullanıcı sorusu;
- `reasoning_summary_tr`: en fazla üç cümlelik gözlenebilir karar gerekçesi

üretir. Yanıt strict JSON Schema ile sınırlandırılır. Tool çağrısı, argümanlar,
tool sonuçları ve beklenen davranış deterministik plan/runner tarafından
oluşturulur. `gpt-5-mini`, soru ile kısa gerekçeyi blueprint ve planla birlikte
değerlendirir.

Canonical alan `reasoning_summary_tr` adını kullanır. Exporter yan alanında
`thinking` yalnız geriye dönük uyumluluk takma adıdır; OpenAI mesaj şemasına
özel veya desteklenmeyen bir `thinking` anahtarı eklenmez.
