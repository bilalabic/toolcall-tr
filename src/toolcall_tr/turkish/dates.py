"""Türkçe tarih ifadeleri — göreli ve mutlak.

**Göreli ifadeler donmuş saate göre çözülür.** ``datetime.now()`` kullanmak,
"önümüzdeki cuma" içeren her ground-truth'u nondeterministik yapardı: veri
bugün üretilince bir tarih, yarın yeniden üretilince başka bir tarih çıkardı.
Referans an her zaman dışarıdan verilir.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from toolcall_tr.turkish.text import lower_tr

__all__ = ["WEEKDAYS", "DateParseError", "format_tr_date", "parse_tr_date"]


class DateParseError(ValueError):
    """Metin Türkçe tarih ifadesi olarak ayrıştırılamadı."""


#: Pazartesi = 0 (``date.weekday()`` ile uyumlu).
WEEKDAYS: dict[str, int] = {
    "pazartesi": 0,
    "salı": 1,
    "sali": 1,
    "çarşamba": 2,
    "carsamba": 2,
    "perşembe": 3,
    "persembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}

MONTHS: dict[str, int] = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
}

MONTH_NAMES = [
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
]

#: "önümüzdeki", "gelecek", "haftaya" -> ileri; "geçen" -> geri.
_FORWARD = ("önümüzdeki", "onumuzdeki", "gelecek", "haftaya", "gelecek hafta")
_BACKWARD = ("geçen", "gecen", "önceki", "onceki")

_NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
_TEXT_DATE_RE = re.compile(r"^(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})$")


def parse_tr_date(text: str, *, now: datetime) -> date:
    """Türkçe tarih ifadesini mutlak tarihe çevirir.

    ``now`` **zorunludur ve donmuş saatten gelir**. Varsayılan değer vermek,
    çağıranın yanlışlıkla gerçek saati kullanmasına kapı açardı.

    Desteklenenler: ``bugün``, ``yarın``, ``dün``, ``öbür gün``,
    ``önümüzdeki cuma``, ``geçen salı``, ``15.03.2026``, ``15 Mart 2026``.
    """
    cleaned = lower_tr(text).strip().rstrip(".").strip()
    today = now.date()

    simple = {
        "bugün": 0,
        "bugun": 0,
        "yarın": 1,
        "yarin": 1,
        "öbür gün": 2,
        "obur gun": 2,
        "dün": -1,
        "dun": -1,
        "evvelsi gün": -2,
    }
    if cleaned in simple:
        return today + timedelta(days=simple[cleaned])

    absolute = _parse_absolute(cleaned)
    if absolute is not None:
        return absolute

    relative = _parse_relative_weekday(cleaned, today)
    if relative is not None:
        return relative

    raise DateParseError(f"Türkçe tarih ifadesi çözülemedi: {text!r}")


def _parse_absolute(cleaned: str) -> date | None:
    numeric = _NUMERIC_DATE_RE.match(cleaned)
    if numeric is not None:
        day, month, year = (int(part) for part in numeric.groups())
        try:
            return date(year, month, day)
        except ValueError as exc:
            raise DateParseError(f"geçersiz tarih: {cleaned!r}") from exc

    textual = _TEXT_DATE_RE.match(cleaned)
    if textual is not None:
        day_text, month_text, year_text = textual.groups()
        month = MONTHS.get(month_text, 0)
        if month == 0:
            raise DateParseError(f"bilinmeyen ay adı: {month_text!r}")
        try:
            return date(int(year_text), month, int(day_text))
        except ValueError as exc:
            raise DateParseError(f"geçersiz tarih: {cleaned!r}") from exc
    return None


def _parse_relative_weekday(cleaned: str, today: date) -> date | None:
    """``önümüzdeki cuma`` / ``geçen salı``.

    "Önümüzdeki X" = bugünden **sonraki** ilk X (bugün X ise gelecek hafta).
    "Geçen X" = bugünden **önceki** son X.
    """
    direction = 0
    remainder = cleaned
    for prefix in _FORWARD:
        if cleaned.startswith(prefix):
            direction = 1
            remainder = cleaned[len(prefix) :].strip()
            break
    else:
        for prefix in _BACKWARD:
            if cleaned.startswith(prefix):
                direction = -1
                remainder = cleaned[len(prefix) :].strip()
                break

    if direction == 0:
        # "bu cuma" veya çıplak "cuma": bugünden sonraki ilk o gün.
        remainder = cleaned.removeprefix("bu").strip()
        direction = 1

    target = WEEKDAYS.get(remainder)
    if target is None:
        return None

    if direction > 0:
        delta = (target - today.weekday()) % 7
        return today + timedelta(days=delta or 7)

    delta = (today.weekday() - target) % 7
    return today - timedelta(days=delta or 7)


def format_tr_date(value: date) -> str:
    """``date(2026, 3, 15)`` -> ``"15 Mart 2026"``."""
    return f"{value.day} {MONTH_NAMES[value.month - 1]} {value.year}"
