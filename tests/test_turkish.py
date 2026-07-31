"""Türkçe metin, sayı ve tarih işleme.

Bu testlerin çoğu, Python'un varsayılan davranışının Türkçe'de **yanlış**
olduğu noktaları sabitler. Her biri gerçek bir hata modudur.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from toolcall_tr.turkish import (
    DateParseError,
    NumberParseError,
    ascii_fold_tr,
    casefold_tr,
    format_tr_date,
    format_tr_number,
    format_try,
    lower_tr,
    normalize_phone,
    parse_tr_date,
    parse_tr_number,
    parse_tr_percent,
    title_tr,
    upper_tr,
)

#: `configs/project.yaml` ile aynı donmuş an.
FROZEN = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)  # 28 Temmuz 2026, salı


# ---------------------------------------------------------------------------
# Büyük/küçük harf -- Python'un varsayılanı Türkçe'de yanlış
# ---------------------------------------------------------------------------


def test_noktasiz_I_kucultme() -> None:
    """Python `"IZMIR".lower()` -> "izmir" der; Türkçe'de doğrusu "ızmır"."""
    assert "IZMIR".lower() == "izmir"  # Python'un yanlış davranışı
    assert lower_tr("IZMIR") == "ızmır"


def test_noktali_I_kucultme() -> None:
    assert lower_tr("İSTANBUL") == "istanbul"


def test_i_buyutme() -> None:
    """Python `"izmir".upper()` -> "IZMIR" der; doğrusu "İZMİR"."""
    assert "izmir".upper() == "IZMIR"  # Python'un yanlış davranışı
    assert upper_tr("izmir") == "İZMİR"


def test_noktasiz_i_buyutme() -> None:
    assert upper_tr("ırmak") == "IRMAK"


def test_casefold_ad_eslestirmesi() -> None:
    """Sessizce bozulan asıl senaryo: aynı adın iki yazımı eşleşmeli."""
    assert casefold_tr("İZMİR Büyükşehir") == casefold_tr("izmir büyükşehir")


def test_title_tr() -> None:
    assert title_tr("izmir büyükşehir belediyesi") == "İzmir Büyükşehir Belediyesi"


def test_ascii_katlama() -> None:
    """Solr analyzer'ı ü/u'yu eşitlemiyor; iki biçim de üretilebilmeli."""
    assert ascii_fold_tr("otobüs durağı") == "otobus duragi"
    assert ascii_fold_tr("Çeşme İzmir") == "Cesme Izmir"


@pytest.mark.parametrize("text", ["", "abc", "1234"])
def test_katlama_ascii_metni_bozmaz(text: str) -> None:
    assert ascii_fold_tr(text) == text


# ---------------------------------------------------------------------------
# Sayı ve para -- üç yanlış yol var, biri doğru
# ---------------------------------------------------------------------------


def test_python_float_turkce_biçimi_ayristiramaz() -> None:
    """Neden bu modül var: hazır çözüm yok."""
    with pytest.raises(ValueError):
        float("1.250,50")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.250,50", "1250.50"),
        ("1.250,50 TL", "1250.50"),
        ("18.500", "18500"),
        ("18.500 TL", "18500"),
        ("1.234.567,89", "1234567.89"),
        ("1234,56", "1234.56"),
        ("0,5", "0.5"),
        ("42", "42"),
        ("1.23", "1.23"),
        ("-1.250,50", "-1250.50"),
        ("₺1.250,50", "1250.50"),
        ("1 250,50 TL", "1250.50"),
    ],
)
def test_turkce_sayi_ayristirma(text: str, expected: str) -> None:
    assert parse_tr_number(text) == Decimal(expected)


def test_para_decimal_dondurur() -> None:
    """Float yuvarlama hatası para ground-truth'unu bozar."""
    assert isinstance(parse_tr_number("18.500,25 TL"), Decimal)


@pytest.mark.parametrize("text", ["", "abc", "TL", "on bin"])
def test_bozuk_sayi_gurultulu_patlar(text: str) -> None:
    with pytest.raises(NumberParseError):
        parse_tr_number(text)


def test_yuzde_isareti_onde_de_arkada_da_olabilir() -> None:
    """Türkçe'de `%20`, İngilizce'de `20%`."""
    assert parse_tr_percent("%20") == Decimal("20")
    assert parse_tr_percent("20%") == Decimal("20")


def test_bicimlendirme_gidis_donus() -> None:
    assert format_tr_number(Decimal("1250.50")) == "1.250,50"
    assert format_try(Decimal("1250.5")) == "1.250,50 TL"
    assert parse_tr_number(format_try(Decimal("1234567.89"))) == Decimal("1234567.89")


# ---------------------------------------------------------------------------
# Telefon
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["0532 000 00 00", "+90 532 000 00 00", "05320000000", "5320000000", "(0532) 000-00-00"],
)
def test_telefon_normalizasyonu(text: str) -> None:
    assert normalize_phone(text) == "+905320000000"


@pytest.mark.parametrize("text", ["123", "0532 000 00", "abcdefghij"])
def test_gecersiz_telefon_reddedilir(text: str) -> None:
    with pytest.raises(NumberParseError):
        normalize_phone(text)


# ---------------------------------------------------------------------------
# Tarih -- göreli ifadeler DONMUŞ saate göre çözülür
# ---------------------------------------------------------------------------


def test_referans_an_zorunlu() -> None:
    """Varsayılan değer, çağıranın yanlışlıkla gerçek saati kullanmasına kapı açardı."""
    with pytest.raises(TypeError):
        parse_tr_date("bugün")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bugün", date(2026, 7, 28)),
        ("yarın", date(2026, 7, 29)),
        ("dün", date(2026, 7, 27)),
        ("öbür gün", date(2026, 7, 30)),
    ],
)
def test_basit_goreli_ifadeler(text: str, expected: date) -> None:
    assert parse_tr_date(text, now=FROZEN) == expected


def test_onumuzdeki_gun_ileri_gider() -> None:
    """28 Temmuz 2026 salı; önümüzdeki cuma 31 Temmuz."""
    assert parse_tr_date("önümüzdeki cuma", now=FROZEN) == date(2026, 7, 31)


def test_gecen_gun_geri_gider() -> None:
    assert parse_tr_date("geçen cuma", now=FROZEN) == date(2026, 7, 24)


def test_ayni_gun_ise_gelecek_haftaya_atlar() -> None:
    """Referans salı; "önümüzdeki salı" bugün değil, gelecek hafta."""
    assert parse_tr_date("önümüzdeki salı", now=FROZEN) == date(2026, 8, 4)


def test_gecen_ayni_gun_gecen_haftaya_gider() -> None:
    assert parse_tr_date("geçen salı", now=FROZEN) == date(2026, 7, 21)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15.03.2026", date(2026, 3, 15)),
        ("15/03/2026", date(2026, 3, 15)),
        ("15 Mart 2026", date(2026, 3, 15)),
        ("1 Ocak 2027", date(2027, 1, 1)),
        ("9 Eylül 2026", date(2026, 9, 9)),
    ],
)
def test_mutlak_tarihler(text: str, expected: date) -> None:
    assert parse_tr_date(text, now=FROZEN) == expected


def test_turkce_karaktersiz_yazim_da_kabul_edilir() -> None:
    """Kullanıcılar "carsamba" da yazar."""
    assert parse_tr_date("önümüzdeki carsamba", now=FROZEN) == date(2026, 7, 29)


@pytest.mark.parametrize("text", ["bir ara", "32.13.2026", "15 Xyzay 2026"])
def test_cozulemeyen_tarih_gurultulu_patlar(text: str) -> None:
    with pytest.raises(DateParseError):
        parse_tr_date(text, now=FROZEN)


def test_tarih_bicimlendirme() -> None:
    assert format_tr_date(date(2026, 3, 15)) == "15 Mart 2026"
    assert format_tr_date(date(2026, 9, 9)) == "9 Eylül 2026"


def test_donmus_saat_sonucu_sabitler() -> None:
    """Aynı ifade + aynı referans an = aynı tarih. Her zaman."""
    first = parse_tr_date("önümüzdeki cuma", now=FROZEN)
    second = parse_tr_date("önümüzdeki cuma", now=FROZEN)
    assert first == second == date(2026, 7, 31)
