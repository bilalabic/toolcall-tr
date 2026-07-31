"""Canonical JSON — tüm hash'lerin tabanı.

Bu biçim bir uyumluluk sözleşmesidir: değişirse her cassette anahtarı, her
``trace_id`` ve her blueprint hash'i geçersizleşir.
"""

from __future__ import annotations

import math

import pytest

from toolcall_tr.canonical import (
    CANONICAL_JSON_VERSION,
    canonical_json,
    sha256_of,
    short_hash,
    type_skeleton,
)


def test_anahtar_sirasi_hash_i_etkilemez() -> None:
    assert sha256_of({"b": 1, "a": 2}) == sha256_of({"a": 2, "b": 1})


def test_turkce_karakterler_kacislanmaz() -> None:
    """Kaçışlama kapalı: Türkçe okunabilir kalır ve UTF-8 byte'ları kararlıdır."""
    assert canonical_json({"ad": "İzmir Büyükşehir"}) == '{"ad":"İzmir Büyükşehir"}'


def test_bosluk_yok() -> None:
    assert canonical_json({"a": [1, 2]}) == '{"a":[1,2]}'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nan_ve_infinity_reddedilir(value: float) -> None:
    """JSON'da karşılıkları yok ve platforma göre farklı davranıyorlar."""
    with pytest.raises(ValueError):
        canonical_json({"x": value})


def test_farkli_icerik_farkli_hash() -> None:
    assert sha256_of({"a": 1}) != sha256_of({"a": 2})


def test_hash_sha256_onekli() -> None:
    digest = sha256_of({"a": 1})
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_short_hash_oneki_atar() -> None:
    assert short_hash("sha256:abcdef0123456789", 6) == "abcdef"


def test_canonical_surumu_kayitli() -> None:
    """Sürüm provenance'a yazılır; biçim değişirse artırılmalıdır."""
    assert CANONICAL_JSON_VERSION == 1


# ---------------------------------------------------------------------------
# type_skeleton -- drift tespitinin temeli
# ---------------------------------------------------------------------------


def test_iskelet_deger_driftini_yok_sayar() -> None:
    """Otobüsün varış süresi değişti: normal, müdahale gerektirmez."""
    once = {"KalanDurakSayisi": 14, "HatAdi": "TINAZTEPE-KONAK"}
    sonra = {"KalanDurakSayisi": 3, "HatAdi": "BORNOVA-KONAK"}
    assert type_skeleton(once) == type_skeleton(sonra)


def test_iskelet_yapisal_drifti_yakalar() -> None:
    """Bir anahtar kayboldu veya tip değişti: ground-truth geçersiz."""
    once = {"KalanDurakSayisi": 14}
    anahtar_gitti = {"HatAdi": "X"}
    tip_degisti = {"KalanDurakSayisi": "14"}

    assert type_skeleton(once) != type_skeleton(anahtar_gitti)
    assert type_skeleton(once) != type_skeleton(tip_degisti)


def test_bos_dizi_ayirt_edilir() -> None:
    """`[]` ESHOT'ta geçerli bir sonuçtur; dolu diziyle karıştırılmamalı."""
    assert type_skeleton([]) == ["<empty>"]
    assert type_skeleton([]) != type_skeleton([{"a": 1}])


def test_bool_int_ten_ayrilir() -> None:
    """Python'da bool bir int'tir; iskelet bunları karıştırmamalı."""
    assert type_skeleton(True) == "bool"
    assert type_skeleton(1) == "int"
    assert type_skeleton({"x": True}) != type_skeleton({"x": 1})


def test_heterojen_dizi_tum_varyantlari_tutar() -> None:
    skeleton = type_skeleton([{"a": 1}, {"b": "x"}])
    assert isinstance(skeleton, list)
    assert len(skeleton) == 2
