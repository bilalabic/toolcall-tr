"""PII tarayıcı — projeyi bitirebilecek tek teknik hatanın önündeki engel.

**Bu dosyada hiçbir checksum-geçerli TCKN literal olarak yazılmaz.**
Gerekli olduğunda çalışma anında üretilir: bir TCKN'yi kaynak koda yazmak,
tam da önlemeye çalıştığımız şeyi yapmak olurdu.
"""

from __future__ import annotations

import pytest

from toolcall_tr.validation.identifiers import (
    SYNTHETIC_TCKN_PREFIX,
    is_synthetic_tckn,
    is_valid_iban,
    is_valid_tckn,
    is_valid_vkn,
)
from toolcall_tr.validation.pii import scan_json, scan_text


def _make_valid_tckn(prefix: str = "123456789") -> str:
    """Checksum-geçerli bir TCKN'yi **çalışma anında** üretir.

    Literal olarak yazılsaydı depoda gerçek bir kişinin kimlik numarasına
    denk gelebilecek bir sayı bulunurdu. Üretilen değer yalnızca tarayıcının
    onu yakaladığını kanıtlamak için kullanılır ve hiçbir yere yazılmaz.
    """
    numbers = [int(char) for char in prefix]
    tenth = (sum(numbers[0::2]) * 7 - sum(numbers[1::2])) % 10
    eleventh = (sum(numbers) + tenth) % 10
    return f"{prefix}{tenth}{eleventh}"


def _make_valid_vkn(prefix: str = "123456789") -> str:
    total = 0
    for index in range(9):
        digit = int(prefix[index])
        temp = (digit + 9 - index) % 10
        total += temp if temp == 9 else (temp * pow(2, 9 - index)) % 9
    return f"{prefix}{(10 - (total % 10)) % 10}"


# ---------------------------------------------------------------------------
# Checksum algoritmaları
# ---------------------------------------------------------------------------


def test_uretilen_tckn_gercekten_gecerli() -> None:
    """Test yardımcısı doğru çalışmazsa asıl testler anlamsız olur."""
    assert is_valid_tckn(_make_valid_tckn())


def test_sifirla_baslayan_tckn_asla_gecerli_degil() -> None:
    """Sentetik aralığın tüm dayanağı bu: gerçek TCKN 0 ile başlayamaz."""
    for suffix in ("0000000000", "1234567890", "9876543210"):
        assert not is_valid_tckn(f"0{suffix}")


def test_sentetik_tckn_tanimi() -> None:
    assert is_synthetic_tckn("01234567890")
    assert not is_synthetic_tckn("11234567890")
    assert not is_synthetic_tckn("0123456789")  # 10 hane
    assert not is_synthetic_tckn("0123456789a")


def test_sentetik_prefix_sabiti() -> None:
    assert SYNTHETIC_TCKN_PREFIX == "0"


@pytest.mark.parametrize("value", ["", "123", "1234567890a", "12345678901234"])
def test_bicimsiz_deger_tckn_degil(value: str) -> None:
    assert not is_valid_tckn(value)


def test_vkn_checksum() -> None:
    valid = _make_valid_vkn()
    assert is_valid_vkn(valid)
    # Son haneyi bozmak geçersizleştirmeli.
    broken = valid[:-1] + str((int(valid[-1]) + 1) % 10)
    assert not is_valid_vkn(broken)


def test_iban_mod97() -> None:
    # Kamuya açık örnek IBAN (ISO 13616 dokümantasyon örneği).
    assert is_valid_iban("GB82 WEST 1234 5698 7654 32")
    assert not is_valid_iban("GB82 WEST 1234 5698 7654 33")


def test_gecersiz_tr_iban() -> None:
    assert not is_valid_iban("TR00 0000 0000 0000 0000 0000 00")


# ---------------------------------------------------------------------------
# Metin taraması
# ---------------------------------------------------------------------------


def test_gercek_tckn_yakalanir() -> None:
    tckn = _make_valid_tckn()
    hits = scan_text(f"Müşterinin kimlik numarası {tckn} olarak kayıtlı.")
    assert [hit.kind for hit in hits] == ["real_tckn"]


def test_bitisik_yazilmis_tckn_de_yakalanir() -> None:
    """`TCKN:12345678901` gibi bitişik yazımlar kaçmamalı."""
    hits = scan_text(f"TCKN:{_make_valid_tckn()}")
    assert any(hit.kind == "real_tckn" for hit in hits)


def test_sentetik_tckn_temiz_gecer() -> None:
    """Politikaya uyan kimlik hiçbir bulgu üretmemeli."""
    assert scan_text("Müşteri kimliği 01234567890.") == []


def test_sentetik_olmayan_11_hane_politika_modunda_isaretlenir() -> None:
    """Bizim ürettiğimiz içerikte 11 hane sentetik aralıkta olmalı."""
    hits = scan_text("Kimlik 19999999999 olarak girildi.", policy=True)
    assert [hit.kind for hit in hits] == ["nonconforming_tckn"]


def test_politika_kontrolu_ucuncu_taraf_verisinde_kapali() -> None:
    """Yanlış pozitif gerçekten yaşandı: bir belediye referans numarası
    (`10861282522`, İzmir taksi durak tablosu) geçerli bir örneği reddetmişti.

    Üçüncü taraf yanıtlarında 11 haneli sayı sıradandır. Politika yalnızca
    kendi ürettiğimiz içerik için anlamlıdır; gerçek TCKN taraması ise her
    yerde açık kalır.
    """
    assert scan_text("Referans 10861282522") == []
    assert scan_text("Referans 10861282522", policy=True)


def test_gercek_tckn_politika_kapaliyken_de_yakalanir() -> None:
    """Asıl koruma her koşulda çalışır."""
    hits = scan_text(f"kimlik {_make_valid_tckn()}", policy=False)
    assert [hit.kind for hit in hits] == ["real_tckn"]


def test_gercek_vkn_yakalanir() -> None:
    hits = scan_text(f"Vergi numarası {_make_valid_vkn()}.")
    assert any(hit.kind == "real_vkn" for hit in hits)


def test_belgelenmis_teknik_kimlik_alani_dar_bicimde_atlanabilir() -> None:
    vkn = _make_valid_vkn()
    hits = scan_json(
        {"key": int(vkn), "customer_number": vkn},
        ignored_numeric_keys=frozenset({"key"}),
    )
    assert [hit.path for hit in hits] == ["$.customer_number"]


def test_gecerli_iban_yakalanir() -> None:
    """Ülke ne olursa olsun: geçerli IBAN finansal kişisel veridir."""
    hits = scan_text("IBAN: GB82 WEST 1234 5698 7654 32")
    assert any(hit.kind == "valid_iban" for hit in hits)


def test_kasten_gecersiz_tr_iban_temiz_gecer() -> None:
    """Sentetik IBAN'lar kasten mod-97-geçersiz üretilir."""
    assert scan_text("Hesap: TR00 0000 0000 0000 0000 0000 00") == []


def test_siradan_sayilar_bulgu_uretmez() -> None:
    """11.783 satır, 38.4192 koordinat, 10030 durak -- hiçbiri PII değil."""
    assert scan_text("11783 satır, durak 10030, koordinat 38.4192") == []


def test_bulgu_maskelenir() -> None:
    """Bulgunun kendisi de kişisel veridir; rapora ham gitmemeli."""
    tckn = _make_valid_tckn()
    hit = scan_text(tckn)[0]
    assert hit.redacted != tckn
    assert hit.redacted.count("*") == len(tckn) - 4
    assert tckn not in hit.redacted


# ---------------------------------------------------------------------------
# JSON taraması
# ---------------------------------------------------------------------------


def test_ic_ice_json_taranir() -> None:
    payload = {"musteri": {"kayitlar": [{"kimlik": _make_valid_tckn()}]}}
    hits = scan_json(payload)
    assert len(hits) == 1
    assert hits[0].path == "$.musteri.kayitlar[0].kimlik"


def test_sayisal_alan_da_taranir() -> None:
    """TCKN'nin JSON'da int durması onu daha az kişisel veri yapmaz."""
    hits = scan_json({"kimlik": int(_make_valid_tckn())})
    assert any(hit.kind == "real_tckn" for hit in hits)


def test_bool_deger_taranmaz() -> None:
    assert scan_json({"aktif": True, "pasif": False}) == []


def test_gercek_cassette_govdesi_temiz() -> None:
    """Kaydedilmiş İzmir verisine benzeyen bir gövde bulgu üretmemeli."""
    payload = {
        "success": True,
        "result": {
            "total": 11783,
            "records": [
                {
                    "DURAK_ID": 10005,
                    "DURAK_ADI": "Bahribaba",
                    "ENLEM": 38.4152683626015,
                    "BOYLAM": 27.1276395272209,
                    "DURAKTAN_GECEN_HATLAR": "32",
                }
            ],
        },
    }
    assert scan_json(payload) == []
