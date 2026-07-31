"""Türk kimlik/vergi/IBAN numaralarının checksum doğrulaması.

**Bu modül doğrulamak için değil, KAÇINMAK için var.**

Checksum-geçerli 11 haneli bir TCKN neredeyse kesinlikle gerçek bir vatandaşın
kimlik numarasıdır. "Rastgele geçerli TCKN üret" default'u, gerçek kişilerin
KVKK korumalı kimliklerini açık lisansla yayımlamak demektir. Bu yüzden:

* Sentetik TCKN'ler **``0`` ile başlar**. Gerçek bir TCKN 0 ile başlayamaz,
  dolayısıyla bu numaralar 11 hane ve sayısaldır (format doğrulamasını
  egzersiz eder) ama **kanıtlanabilir şekilde hiçbir gerçek kişiye ait
  değildir**.
* VKN'ler kasten checksum-geçersiz üretilir.
* IBAN'lar kasten mod-97-geçersiz üretilir.

Buradaki fonksiyonlar `PIIScanner` tarafından, "yanlışlıkla gerçek bir
tanımlayıcı ürettik mi?" sorusunu cevaplamak için kullanılır.
"""

from __future__ import annotations

__all__ = [
    "SYNTHETIC_TCKN_PREFIX",
    "is_synthetic_tckn",
    "is_valid_iban",
    "is_valid_tckn",
    "is_valid_vkn",
]

#: Gerçek bir TCKN bu karakterle başlayamaz. Tüm sentetik kimlikler başlar.
SYNTHETIC_TCKN_PREFIX = "0"

_IBAN_LENGTHS: dict[str, int] = {"TR": 26}


def is_valid_tckn(value: str) -> bool:
    """T.C. Kimlik Numarası checksum kontrolü.

    Algoritma kamuya açıktır (NVİ). Burada **tespit** için kullanılır: bu
    fonksiyonun ``True`` döndürdüğü hiçbir değer veri setine giremez.
    """
    digits = value.strip()
    if len(digits) != 11 or not digits.isdigit():
        return False
    if digits[0] == "0":
        return False

    numbers = [int(char) for char in digits]
    odd_sum = sum(numbers[0:9:2])  # 1., 3., 5., 7., 9. haneler
    even_sum = sum(numbers[1:8:2])  # 2., 4., 6., 8. haneler

    tenth = (odd_sum * 7 - even_sum) % 10
    if tenth != numbers[9]:
        return False
    return sum(numbers[:10]) % 10 == numbers[10]


def is_synthetic_tckn(value: str) -> bool:
    """Sentetik aralıkta mı? (11 hane, sayısal, ``0`` ile başlıyor)"""
    digits = value.strip()
    return len(digits) == 11 and digits.isdigit() and digits.startswith(SYNTHETIC_TCKN_PREFIX)


def is_valid_vkn(value: str) -> bool:
    """Vergi Kimlik Numarası (10 hane) checksum kontrolü."""
    digits = value.strip()
    if len(digits) != 10 or not digits.isdigit():
        return False

    total = 0
    for index in range(9):
        digit = int(digits[index])
        temp = (digit + 9 - index) % 10
        if temp == 9:
            total += temp
        else:
            total += (temp * pow(2, 9 - index)) % 9

    check = (10 - (total % 10)) % 10
    return check == int(digits[9])


def is_valid_iban(value: str) -> bool:
    """IBAN mod-97 kontrolü (ISO 13616).

    Yalnızca uzunluğu bilinen ülkeler kontrol edilir; bilinmeyen ülke kodu
    için ``False`` döner (tespit amaçlı, tam bir IBAN doğrulayıcı değil).
    """
    cleaned = "".join(value.split()).upper()
    if len(cleaned) < 5 or not cleaned[:2].isalpha() or not cleaned[2:].isalnum():
        return False

    expected = _IBAN_LENGTHS.get(cleaned[:2])
    if expected is not None and len(cleaned) != expected:
        return False

    rearranged = cleaned[4:] + cleaned[:4]
    digits: list[str] = []
    for char in rearranged:
        if char.isdigit():
            digits.append(char)
        elif char.isalpha():
            digits.append(str(ord(char) - ord("A") + 10))
        else:
            return False

    return int("".join(digits)) % 97 == 1
