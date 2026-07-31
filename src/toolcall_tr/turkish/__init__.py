"""Türkçe metin işleme — tek nokta.

Dağıtılırsa yanlış yapılır. Üç ailenin her biri gerçek bir hata modunu
kapatır:

`text`
    ``"IZMIR".lower()`` Python'da ``"izmir"`` verir; doğrusu ``"ızmır"``.
    Bu, müşteri adı eşleştirmesini *sessizce* bozan klasik hatadır.
`numbers`
    ``"1.250,50 TL"``: binlik ayracı nokta, ondalık ayracı virgül.
    ``float()`` patlar, virgülü noktaya çevirmek 1.25050 üretir, noktayı
    silmek 125050 üretir -- üçü de yanlış.
`dates`
    Göreli ifadeler (``"önümüzdeki cuma"``) **donmuş saate** göre çözülür;
    aksi hâlde ground-truth her gün değişir.

Bu paket **hiçbir iç modülü import etmez**.
"""

from toolcall_tr.turkish.dates import (
    MONTHS,
    WEEKDAYS,
    DateParseError,
    format_tr_date,
    parse_tr_date,
)
from toolcall_tr.turkish.morphology import (
    MIN_STEM_LENGTH,
    loose_match,
    stem_tr,
    tokenize_tr,
)
from toolcall_tr.turkish.numbers import (
    NumberParseError,
    format_tr_number,
    format_try,
    normalize_phone,
    parse_tr_number,
    parse_tr_percent,
)
from toolcall_tr.turkish.text import (
    ascii_fold_tr,
    casefold_tr,
    lower_tr,
    title_tr,
    upper_tr,
)

__all__ = [
    "MIN_STEM_LENGTH",
    "MONTHS",
    "WEEKDAYS",
    "DateParseError",
    "NumberParseError",
    "ascii_fold_tr",
    "casefold_tr",
    "format_tr_date",
    "format_tr_number",
    "format_try",
    "loose_match",
    "lower_tr",
    "normalize_phone",
    "parse_tr_date",
    "parse_tr_number",
    "parse_tr_percent",
    "stem_tr",
    "title_tr",
    "tokenize_tr",
    "upper_tr",
]
