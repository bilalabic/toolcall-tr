"""Türkçe sayı, para ve telefon biçimleri.

Türkçe'de binlik ayracı **nokta**, ondalık ayracı **virgüldür**:
``1.250,50 TL`` = 1250.50. ``float("1.250,50")`` patlar; virgülü nokta
yapmak 1.25050 üretir; noktayı silmek 125050 üretir. Üçü de yanlış.

LLM doğal Türkçe yazar (``"18.500 TL"``); kod normalize eder. Bu dönüşüm
ground-truth'un parçasıdır ve tek noktada yapılır.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = [
    "NumberParseError",
    "format_tr_number",
    "format_try",
    "normalize_phone",
    "parse_tr_number",
    "parse_tr_percent",
]

#: Para birimi işaretleri ve boşluklar ayrıştırmadan önce atılır.
_STRIP_RE = re.compile(r"[\s ]|TL|TRY|₺|USD|\$|EUR|€", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^-?[\d.,]+$")
_PHONE_STRIP_RE = re.compile(r"[\s\-(). ]")


class NumberParseError(ValueError):
    """Metin Türkçe sayı biçiminde ayrıştırılamadı."""


def parse_tr_number(text: str) -> Decimal:
    """``"1.250,50 TL"`` -> ``Decimal("1250.50")``.

    Ayraç belirleme kuralları:

    * Hem ``.`` hem ``,`` varsa: ``.`` binlik, ``,`` ondalık.
    * Yalnızca ``,`` varsa: ondalık.
    * Yalnızca ``.`` varsa: son grup **tam 3 hane** ise binlik, değilse
      ondalık. ``"18.500"`` -> 18500 ama ``"1.23"`` -> 1.23.

    Son kural bir sezgiseldir çünkü ``"1.234"`` gerçekten belirsizdir; Türkçe
    yazımda binlik ayracı olması çok daha olasıdır.

    `Decimal` döndürülür: para değerlerinde float yuvarlama hatası
    ground-truth'u bozar.
    """
    cleaned = _STRIP_RE.sub("", text).strip()
    if not cleaned or not _DIGITS_RE.match(cleaned):
        raise NumberParseError(f"Türkçe sayı biçiminde ayrıştırılamadı: {text!r}")

    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("-")

    has_dot = "." in cleaned
    has_comma = "," in cleaned

    if has_dot and has_comma:
        normalized = cleaned.replace(".", "").replace(",", ".")
    elif has_comma:
        normalized = cleaned.replace(",", ".")
    elif has_dot:
        head, _, tail = cleaned.rpartition(".")
        # Birden fazla nokta varsa kesin binlik ayracıdır ("1.234.567").
        normalized = cleaned.replace(".", "") if (len(tail) == 3 and head) else cleaned
    else:
        normalized = cleaned

    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise NumberParseError(f"Türkçe sayı biçiminde ayrıştırılamadı: {text!r}") from exc
    return -value if negative else value


def parse_tr_percent(text: str) -> Decimal:
    """``"%20"`` veya ``"20%"`` -> ``Decimal("20")``.

    Türkçe'de yüzde işareti sayının **önüne** yazılır; İngilizce'de sonuna.
    İkisi de kabul edilir.
    """
    return parse_tr_number(text.replace("%", ""))


def format_tr_number(value: Decimal | float | int, *, decimals: int = 2) -> str:
    """``1250.5`` -> ``"1.250,50"``."""
    quantized = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals))
    formatted = f"{quantized:,.{decimals}f}"
    # İngilizce biçimden Türkçe biçime: ayraçları takas et.
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_try(value: Decimal | float | int, *, decimals: int = 2) -> str:
    """``1250.5`` -> ``"1.250,50 TL"``."""
    return f"{format_tr_number(value, decimals=decimals)} TL"


def normalize_phone(text: str) -> str:
    """Türkçe telefon numarasını E.164 biçimine getirir.

    ``"0532 000 00 00"``, ``"+90 532 000 00 00"`` ve ``"5320000000"`` aynı
    sonucu verir: ``"+905320000000"``.
    """
    cleaned = _PHONE_STRIP_RE.sub("", text)
    if cleaned.startswith("+90"):
        digits = cleaned[3:]
    elif cleaned.startswith("0090"):
        digits = cleaned[4:]
    elif cleaned.startswith("90") and len(cleaned) == 12:
        digits = cleaned[2:]
    elif cleaned.startswith("0"):
        digits = cleaned[1:]
    else:
        digits = cleaned

    if not digits.isdigit() or len(digits) != 10:
        raise NumberParseError(f"geçerli bir Türkiye telefon numarası değil: {text!r}")
    return f"+90{digits}"
