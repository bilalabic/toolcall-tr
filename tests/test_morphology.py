"""Türkçe ek soyma ve gevşek eşleştirme.

Bu modül olmadan doğal Türkçe imkânsız: kullanıcı "otobüs duraklarıyla" der,
argüman ``"otobüs durak"`` olur ve birebir arama başarısız olur. Grounding
validator'ın türetilmiş değerleri denetleyebilmesi buna bağlıdır.
"""

from __future__ import annotations

import pytest

from toolcall_tr.turkish import loose_match, stem_tr, tokenize_tr

# ---------------------------------------------------------------------------
# Gövdeleme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("durak", "durak"),
        ("durağı", "durak"),  # ünsüz yumuşaması geri alınır
        ("durakları", "durak"),
        ("duraklarıyla", "durak"),
        ("duraklarında", "durak"),
        ("otobüsler", "otobüs"),
        ("otobüs", "otobüs"),
    ],
)
def test_cekim_ekleri_soyulur(word: str, expected: str) -> None:
    assert stem_tr(word) == expected


def test_unsuz_yumusamasi_geri_alinir() -> None:
    """`durak` + `ı` -> `durağı`; gövde yine `durak` olmalı.

    Bu, Türkçe'ye özgü ve kritik: ek soyulduğunda `durağ` kalır, `durak`
    değil.
    """
    assert stem_tr("durağı") == stem_tr("durak") == "durak"


def test_gövdeleme_idempotent() -> None:
    for word in ("duraklarıyla", "otobüsler", "hava"):
        once = stem_tr(word)
        assert stem_tr(once) == once


def test_bos_girdi() -> None:
    assert stem_tr("") == ""
    assert tokenize_tr("") == []


def test_tokenize_turkce_harfleri_korur() -> None:
    assert tokenize_tr("Otobüs durağı nerede?") == ["otobüs", "durağı", "nerede"]


def test_tokenize_kesme_isaretinde_boler() -> None:
    """`Konak'taki` -> `konak` + `taki`; ilki eşleşme için yeterli."""
    assert "konak" in tokenize_tr("Konak'taki duraklar")


# ---------------------------------------------------------------------------
# Gevşek eşleştirme -- grounding'in dayandığı asıl işlev
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [
        ("otobüs durak", "Otobüs duraklarıyla ilgili ne tür veriler var?"),
        ("otobüs durak", "Duraklarda hangi otobüsler geçiyor?"),
        ("otobüs durak", "otobus duraklari nerede"),  # ASCII yazan kullanıcı
        ("hava kalitesi", "İzmir'de hava kalitesi ölçülüyor mu?"),
        ("hava kalitesi", "havanın kalitesini merak ediyorum"),
        ("taksi durak", "Taksi duraklarının verisini bulur musun?"),
        ("KONAK", "Konak'taki durakları görebilir miyim?"),
        ("elektrikli scooter", "Elektrikli scooter park yerleri var mı?"),
        ("Beşiktaş", "Beşiktaş'ta durak var mı bu listede?"),
    ],
)
def test_turetilmis_deger_eslesir(needle: str, haystack: str) -> None:
    assert loose_match(needle, haystack)


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [
        ("taksi durak", "Otobüs durakları nerede?"),
        ("hava kalitesi", "Otobüs durakları nerede?"),
        ("metro", "Otobüs durakları nerede?"),
        ("elektrikli scooter", "Yarın hava nasıl olacak?"),
    ],
)
def test_ilgisiz_deger_eslesmez(needle: str, haystack: str) -> None:
    """Gevşetme, uydurma argümanı görünmez yapmamalı."""
    assert not loose_match(needle, haystack)


def test_cok_kelimeli_terimde_hepsi_gerekli() -> None:
    """ "otobüs durak" için yalnızca "otobüs" geçmesi yetmez."""
    assert not loose_match("otobüs durak", "Otobüsler kaçta kalkıyor?")


def test_bos_girdiler_eslesmez() -> None:
    assert not loose_match("", "bir şey")
    assert not loose_match("durak", "")
