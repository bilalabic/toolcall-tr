"""Türkçe ek soyma — gevşek eşleştirme için hafif gövdeleme.

**Neden gerekli:** Türkçe eklemeli bir dildir ve kullanıcı doğal yazdığında
argüman değeri metinde *birebir* geçmez:

    kullanıcı : "Otobüs duraklarıyla ilgili ne tür veriler var?"
    argüman   : q = "otobüs durak"

``"otobüs durak" in metin`` kontrolü burada başarısız olur. Bu yüzden
grounding validator ``USER_MESSAGE_DERIVED`` kaynaklı değerleri **gövde
düzeyinde** arar.

Bu, uydurma bir ihtiyaç değil: İzmir portalının Solr indeksi de Türkçe kök
bulma yapmıyor (`durak` → 8 sonuç, `durağı` → **0**). Yani ajanın yapması
gereken gerçek iş, kullanıcının ekli ifadesinden eksiz bir arama terimi
türetmektir. Bu modül o dönüşümün doğrulanabilir karşılığıdır.

**Hassasiyet değil, tutarlılık hedeflenir.** Aşırı soyma (``kalite`` →
``kalit``) sorun değildir; iki taraf da aynı biçimde soyulduğu için eşleşme
korunur. Bu bir arama motoru değil, uydurma argümana karşı bir korumadır.
"""

from __future__ import annotations

import re

from toolcall_tr.turkish.text import ascii_fold_tr, lower_tr

__all__ = ["MIN_PREFIX_MATCH", "MIN_STEM_LENGTH", "loose_match", "stem_tr", "tokenize_tr"]

#: Soyma sonrası gövde bundan kısalamaz.
#:
#: 3 seçilmesi kasıtlıdır: 4 olduğunda ``yerleri`` -> ``yerler`` ama
#: ``yeri`` -> ``yeri`` kalıyor ve ikisi eşleşmiyordu. Taban düşürülünce
#: her ikisi de ``yer`` oluyor. Aşırı soyma sorun değil, **tutarsız** soyma
#: sorundur.
MIN_STEM_LENGTH = 3

#: Önek karşılaştırması bu uzunluğun altında yapılmaz: ``ver`` gibi kısa
#: gövdeler ``vermek``, ``verim`` gibi ilgisiz kelimelerle eşleşirdi.
#: Tam gövde eşitliği her uzunlukta geçerlidir.
MIN_PREFIX_MATCH = 4

_TOKEN_RE = re.compile(r"[0-9a-zçğıöşü]+", re.IGNORECASE)

#: Uzundan kısaya sıralı. Sıra önemlidir: ``ları`` ``lar``dan önce denenir.
_SUFFIXES: tuple[str, ...] = (
    # iyelik + çoğul + hâl birleşimleri
    "larından",
    "lerinden",
    "larıyla",
    "leriyle",
    "larında",
    "lerinde",
    "larını",
    "lerini",
    "ların",
    "lerin",
    "ları",
    "leri",
    "lara",
    "lere",
    "larda",
    "lerde",
    "lardan",
    "lerden",
    # çoğul
    "lar",
    "ler",
    # araç hâli
    "yla",
    "yle",
    "la",
    "le",
    # ayrılma
    "dan",
    "den",
    "tan",
    "ten",
    # bulunma
    "da",
    "de",
    "ta",
    "te",
    # ilgi
    "nın",
    "nin",
    "nun",
    "nün",
    "ın",
    "in",
    "un",
    "ün",
    # iyelik (3. tekil, ünlüyle biten gövdelerde kaynaştırma)
    "sı",
    "si",
    "su",
    "sü",
    # yönelme / belirtme
    "ya",
    "ye",
    "yı",
    "yi",
    "yu",
    "yü",
    "a",
    "e",
    "ı",
    "i",
    "u",
    "ü",
)

#: Ünsüz yumuşaması geri alınır: ``durak`` + ``ı`` -> ``durağı``.
#: Ek soyulduktan sonra ``durağ`` kalır; gövde ``durak`` olmalıdır.
_DEVOICE = {"ğ": "k", "b": "p", "c": "ç", "d": "t"}


def tokenize_tr(text: str) -> list[str]:
    """Metni Türkçe harfleri koruyarak kelimelere ayırır."""
    return _TOKEN_RE.findall(lower_tr(text))


def stem_tr(word: str) -> str:
    """Kelimeden çekim eklerini sabit noktaya kadar soyar.

    >>> stem_tr("duraklarıyla")
    'durak'
    >>> stem_tr("durağı")
    'durak'
    >>> stem_tr("otobüsler")
    'otobüs'
    """
    current = lower_tr(word).strip()
    if not current:
        return current

    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            if not current.endswith(suffix):
                continue
            candidate = current[: -len(suffix)]
            if len(candidate) < MIN_STEM_LENGTH:
                continue
            current = candidate
            changed = True
            break

    # Ünsüz yumuşamasını geri al: "durağ" -> "durak".
    if current and current[-1] in _DEVOICE:
        current = current[:-1] + _DEVOICE[current[-1]]
    return current


def _forms(word: str) -> tuple[str, str]:
    """Kelimenin (ham, gövde) normalize biçimleri — her ikisi de ASCII katlanmış."""
    return ascii_fold_tr(lower_tr(word)), ascii_fold_tr(stem_tr(word))


def loose_match(needle: str, haystack: str) -> bool:
    """``needle``in her kelimesi ``haystack``te çekim eklerine rağmen geçiyor mu?

    Türkçe **son ekli** bir dildir; çekim daima sona eklenir. Bu yüzden asıl
    araç **önek eşleşmesidir**: ``durak`` ile ``duraklarıyla`` ilk beş harfte
    örtüşür. Gövdeleme ikinci bir yardımcıdır ve asıl olarak ünsüz
    yumuşamasını çözer (``renk`` / ``rengi`` gibi öneki kısa kalan çiftler).

    Açgözlü gövdeleme iki tarafı farklı derinlikte bırakabilir (``kalitesi``
    -> ``kal`` ama ``kalitesini`` -> ``kalites``); üç ölçütün birlikte
    kullanılması bunu tolere eder.

    >>> loose_match("otobüs durak", "Otobüs duraklarıyla ilgili veri var mı?")
    True
    >>> loose_match("hava kalitesi", "havanın kalitesini merak ediyorum")
    True
    >>> loose_match("taksi durak", "Otobüs durakları nerede?")
    False
    """
    needles = [_forms(token) for token in tokenize_tr(needle)]
    if not needles:
        return False

    candidates = [_forms(token) for token in tokenize_tr(haystack)]
    if not candidates:
        return False

    return all(_token_present(form, candidates) for form in needles)


def _token_present(needle: tuple[str, str], candidates: list[tuple[str, str]]) -> bool:
    raw, stem = needle
    for candidate_raw, candidate_stem in candidates:
        if stem == candidate_stem or raw == candidate_raw:
            return True
        if _shared_prefix(raw, candidate_raw) >= MIN_PREFIX_MATCH:
            return True
        if (
            len(stem) >= MIN_PREFIX_MATCH
            and len(candidate_stem) >= MIN_PREFIX_MATCH
            and (stem.startswith(candidate_stem) or candidate_stem.startswith(stem))
        ):
            return True
    return False


def _shared_prefix(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        count += 1
    return count
