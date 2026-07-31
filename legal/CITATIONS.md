# Atıflar

ToolCall-TR'nin metodolojik referansları. Bu çalışmaların **fikirleri** yeniden
uygulanmıştır; artefaktları (prompt, taksonomi tablosu, seed verisi, kod)
kopyalanmamıştır. Bkz. `NOTICE.md` § 2 temiz oda beyanı.

---

## Bu projenin nasıl atıf alacağı

```bibtex
@software{toolcall_tr_2026,
  title  = {ToolCall-TR: A Verifiable Tool-Calling Data Generation Framework
            for Turkish and Turkey-Specific APIs},
  author = {ToolCall-TR katkıcıları},
  year   = {2026},
  url    = {https://github.com/toolcall-tr/toolcall-tr},
  note   = {Kod Apache-2.0, veri CC BY 4.0}
}
```

Veri seti kullanılıyorsa İzmir Büyükşehir Belediyesi atfı da zorunludur:

> Atıf 4.0 Uluslararası (CC BY 4.0) kapsamında lisanslanan kamu sektörü
> bilgilerini içerir. Kaynak: İzmir Büyükşehir Belediyesi Açık Veri Portalı,
> https://acikveri.bizizmir.com

---

## Metodolojik referanslar

### APIGen — doğrulama katmanları çekirdeği

Üç aşamalı doğrulama (format → execution → semantic) ve "kod ground-truth
üretir, LLM yalnızca doğal dil üretir" ilkesi buradan alınmıştır.

```bibtex
@inproceedings{liu2024apigen,
  title     = {APIGen: Automated Pipeline for Generating Verifiable and
               Diverse Function-Calling Datasets},
  author    = {Liu, Zuxin and Hoang, Thai and Zhang, Jianguo and others},
  booktitle = {NeurIPS},
  year      = {2024},
  url       = {https://arxiv.org/abs/2406.18518}
}
```

### APIGen-MT — iki aşamalı blueprint→diyalog (M2)

Önce doğrulanmış action blueprint, sonra blueprint üzerinden doğal diyalog
üretimi yaklaşımı.

```bibtex
@article{prabhakar2025apigenmt,
  title   = {APIGen-MT: Agentic Pipeline for Multi-Turn Data Generation via
             Simulated Agent-Human Interplay},
  author  = {Prabhakar, Akshara and Liu, Zuxin and others},
  year    = {2025},
  url     = {https://arxiv.org/abs/2504.03601}
}
```

> Not: `Salesforce/APIGen-MT-5k` veri seti CC BY-NC-4.0'dır ve bu projede
> **kullanılmamaktadır**. Yalnızca makaleye atıf verilmektedir.

### When2Call — karar taksonomisi

`tool_call` / `clarification` / `direct_answer` / `cannot_answer` dörtlüsü.

```bibtex
@misc{when2call2025,
  title  = {When2Call: When (not) to Call Tools},
  author = {NVIDIA},
  year   = {2025},
  url    = {https://huggingface.co/datasets/nvidia/When2Call}
}
```

### ToolACE — negatif vaka tasarımı

Eksik parametre, zor bağımlılık ve gereksiz tool kullanımı kontrolleri.

```bibtex
@misc{toolace2024,
  title  = {ToolACE: Winning the Points of LLM Function Calling},
  author = {Team-ACE},
  year   = {2024},
  url    = {https://huggingface.co/datasets/Team-ACE/ToolACE}
}
```

### ToolMind — turn-level filtreleme

Çok turlu trajectory'de her turun ayrı doğrulanması ve yalnızca hatalı turun
yeniden üretilmesi.

```bibtex
@article{toolmind2025,
  title  = {ToolMind},
  author = {Nanbeige},
  year   = {2025},
  url    = {https://arxiv.org/abs/2511.15718}
}
```

### BFCL / Gorilla — benchmark metrikleri

```bibtex
@misc{patil2023gorilla,
  title  = {Gorilla: Large Language Model Connected with Massive APIs},
  author = {Patil, Shishir G. and Zhang, Tianjun and Wang, Xin and
            Gonzalez, Joseph E.},
  year   = {2023},
  url    = {https://github.com/ShishirPatil/gorilla}
}
```

### τ-bench — state-diff tabanlı değerlendirme

Final-state karşılaştırmasının yanıt eşleştirmesinden daha güvenilir bir
başarı ölçütü olduğu fikri.

```bibtex
@article{yao2024taubench,
  title   = {tau-bench: A Benchmark for Tool-Agent-User Interaction in
             Real-World Domains},
  author  = {Yao, Shunyu and Shinn, Noah and Razavi, Pedram and
             Narasimhan, Karthik},
  year    = {2024},
  url     = {https://github.com/sierra-research/tau-bench}
}
```

---

## Mevcut Türkçe function-calling veri setleri

ToolCall-TR **ilk Türkçe function-calling veri seti değildir.** Aşağıdakiler
zaten mevcuttur. ToolCall-TR'nin farkı, bunların hiçbirinin sahip olmadığı
özellikler: **execution-verified**, **stateful**, **observation-grounded** ve
**yeniden üretilebilir** olması.

| Veri seti | Satır | Lisans | Köken |
|---|---|---|---|
| `ituperceptron/turkish-tool-calling` | 41.480 | Apache-2.0 | çeviri tabanlı |
| `atasoglu/turkish-function-calling-20k` | 22.000 | MIT | sentetik, İngilizce tool kataloğu |
| `BTX24/turkish-mobile-function-calling-dataset` | 17.826 | Apache-2.0 | doğal Türkçe, dar domain (12 mobil tool) |
| `Tuguberk/turkish-hermes-function-calling` | 11.600 | Apache-2.0 | çeviri tabanlı |
| `atasoglu/turkish-tool-calling-10k` | 10.875 | MIT | sentetik, tek tur |

Hiçbiri çalıştırılabilir bir ortama, state doğrulamasına veya Türkçe bir
benchmark'a sahip değildir. Karşılaştırma ve konumlandırma dataset card'da
açıkça yapılır.
