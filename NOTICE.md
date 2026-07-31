# NOTICE

ToolCall-TR
Copyright 2026 ToolCall-TR katkıcıları

Bu ürün Apache License 2.0 altında lisanslanmış yazılım (bkz. `LICENSE`) ve
CC BY 4.0 altında lisanslanmış veri (bkz. `LICENSE-DATA`) içerir.

---

## 1. Bağımsızlık beyanı

Bu proje **Salesforce tarafından geliştirilmemiştir** ve Salesforce ile resmî bir
bağlantısı bulunmamaktadır. APIGen, APIGen-MT, ToolACE, When2Call, ToolMind, BFCL
ve τ-bench, açıkça atıf verilen **metodolojik referanslardır**.

Bu proje herhangi bir ticari muhasebe/ön muhasebe yazılımı sağlayıcısı tarafından
geliştirilmemiştir, onaylanmamıştır ve onlarla bağlantılı değildir.

## 2. Temiz oda (clean-room) beyanı

Metodoloji referanslarının **fikirleri** yeniden uygulanmıştır; **artefaktları**
kopyalanmamıştır. Bu depoya aşağıdakilerin hiçbiri alınmamıştır:

- prompt metinleri,
- taksonomi/kategori tabloları,
- seed verisi veya örnek kayıtlar,
- kaynak kod parçaları.

Atıflar için `legal/CITATIONS.md` dosyasına bakınız.

### Lisans uyumluluğu notu

Referans veri setlerinin lisansları farklıdır ve karıştırılmaları güvenli
değildir:

| Artefakt | Lisans | Ticari |
|---|---|---|
| `Team-ACE/ToolACE` | Apache-2.0 | evet |
| `Nanbeige/ToolMind` | Apache-2.0 | evet |
| `nvidia/When2Call` | CC BY 4.0 | evet |
| BFCL / Gorilla | Apache-2.0 | evet |
| τ-bench / τ²-bench | MIT | evet |
| `Salesforce/APIGen-MT-5k` | **CC BY-NC-4.0** | **hayır** |
| `Salesforce/xlam-function-calling-60k` | **çelişkili** (kart CC BY 4.0, GitHub README CC BY-NC-4.0) | **belirsiz** |

Son iki satır bu projede **hiçbir biçimde kullanılmamaktadır** — ne veri, ne
prompt, ne taksonomi olarak. `mixtures/commercial_safe.yaml` bunları asla
içermez.

## 3. Kurgusal sağlayıcı: `onmuhasebe_mock`

Milestone 2'de eklenen ön muhasebe sağlayıcısı **tamamen kurgusaldır**.

- Marka adı, alan adı ve şirket unvanları uydurmadır.
- Servis tabanı rezerve `.test` TLD'sini kullanır (`https://api.ornek-onmuhasebe.test`);
  tescil edilebilir hiçbir alan adı kullanılmaz.
- Şema, JSON:API tarzı bir ön muhasebe kaynak modelinin **genel biçimini** izler.
  Bu biçim sektörde yaygındır ve tek bir sağlayıcıya özgü değildir.
- Herhangi bir ticari sağlayıcının OpenAPI/Swagger dosyası, açıklama metni veya
  dokümantasyonu bu depoya **hiçbir biçimde** (test fixture, yorum satırı, commit
  mesajı dahil) dâhil edilmemiştir.
- Tüm şirket, müşteri, ürün, fatura ve tahsilat verileri sentetiktir.

## 4. Üçüncü taraf veri kaynakları

**İzmir Büyükşehir Belediyesi Açık Veri Portalı** — https://acikveri.bizizmir.com
CC BY 4.0 (İzmir Büyükşehir Belediyesi Açık Veri Lisansı).
Bu depodaki `data/cassettes/izmir/` ve `data/snapshots/` içerikleri bu kaynaktan
türetilmiş ve değiştirilmiştir. Değişikliklerin listesi `LICENSE-DATA` § 2'dedir.

**ESHOT / İztek gerçek zamanlı servisleri** — https://openapi.izmir.bel.tr
Lisans durumu **belirsiz**; bkz. `LICENSE-DATA` § 3. Yayın öncesi çözülmesi
gereken açık madde.

Tam envanter: `legal/THIRD_PARTY_LICENSES.csv` ve `legal/DATA_SOURCES.md`.
