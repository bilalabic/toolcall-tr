"""Argüman normalizasyonu ve şema doğrulaması — yaprak yardımcı modül.

`canonical` gibi bu da bir yaprak: yalnızca `models`'a bağlıdır ve hem
`groundtruth` hem `validation` tarafından import edilebilir. Böylece
"argüman geçerli mi?" sorusu tek bir yerde cevaplanır ve iki farklı
implementasyon birbirinden sapmaz.

**Normalizasyon neden şart:** canonical JSON tek başına ``{"rows": 10}`` ile
``{"rows": "10"}``, ``1.0`` ile ``1``, ya da atlanmış-opsiyonel ile
açıkça-verilmiş-varsayılan arasındaki farkı çözmez. Bu farklar cassette
anahtarını değiştirir ve aynı semantik çağrı iki ayrı kayıt üretir. CKAN'da bu
teorik değil, pratikte başa gelen bir durumdur.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from toolcall_tr.models import ParamSpec, ToolSpec

__all__ = ["ArgumentError", "normalize_arguments", "type_matches", "validate_arguments"]

_TRUE = frozenset({"true", "1", "evet", "yes"})
_FALSE = frozenset({"false", "0", "hayır", "hayir", "no"})


class ArgumentError(ValueError):
    """Argümanlar tool şemasına uymuyor."""

    def __init__(self, tool_id: str, errors: list[str]) -> None:
        self.tool_id = tool_id
        self.errors = errors
        super().__init__(f"{tool_id}: " + "; ".join(errors))


def _coerce(param: ParamSpec, value: Any) -> Any:
    """Değeri parametre tipine getirir; getiremezse olduğu gibi bırakır.

    Dönüştürememek burada hata değildir: doğrulama `validate_arguments`'ın
    işidir ve tüm hataları birden toplayabilmesi için normalizasyonun
    patlamaması gerekir.
    """
    if value is None:
        return None

    if param.type == "integer":
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return value
        return value

    if param.type == "number":
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value

    if param.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
        return value

    if param.type == "string":
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return str(value)
        return value

    return value


def normalize_arguments(
    tool: ToolSpec,
    raw: Mapping[str, Any],
    *,
    apply_defaults: bool = True,
) -> dict[str, Any]:
    """Argümanları tool şemasına göre normalize eder.

    * Tipleri şemadaki tipe getirir (``"10"`` -> ``10``).
    * ``apply_defaults`` ile şema varsayılanlarını doldurur; böylece atlanmış
      opsiyonel ile açıkça verilmiş varsayılan aynı isteği üretir.
    * Anahtarları parametre tanım sırasına göre sıralar.

    Bilinmeyen anahtarlar **korunur**: onları burada sessizce atmak,
    "unknown parameter" hatasını görünmez yapardı. `validate_arguments`
    yakalar.
    """
    normalized: dict[str, Any] = {}
    for param in tool.parameters:
        if param.name in raw:
            normalized[param.name] = _coerce(param, raw[param.name])
        elif apply_defaults and param.has_default:
            normalized[param.name] = param.default

    for key in raw:
        if key not in normalized:
            normalized[key] = raw[key]
    return normalized


def validate_arguments(tool: ToolSpec, arguments: Mapping[str, Any]) -> list[str]:
    """Argümanları doğrular ve **tüm** hataları döner.

    Tek tek patlamak yerine hepsini toplamak, rapor üretimi için gereklidir:
    bir örneğin kaç ayrı sebeple reddedildiğini bilmek istiyoruz.
    """
    errors: list[str] = []
    known = {param.name: param for param in tool.parameters}

    for name in sorted(set(arguments) - set(known)):
        errors.append(f"şemada olmayan parametre: {name!r}")

    for param in tool.parameters:
        if param.name not in arguments:
            if param.required:
                errors.append(f"zorunlu parametre eksik: {param.name!r}")
            continue
        errors.extend(_check_value(param, arguments[param.name]))

    return errors


def _check_value(param: ParamSpec, value: Any) -> list[str]:
    name = param.name
    errors: list[str] = []

    if value is None:
        if param.required:
            errors.append(f"{name!r}: zorunlu parametre None olamaz")
        return errors

    if not type_matches(param.type, value):
        errors.append(f"{name!r}: beklenen tip {param.type}, gelen {type(value).__name__}")
        return errors

    if param.enum is not None and value not in param.enum:
        errors.append(f"{name!r}: izin verilen değerler {param.enum}, gelen {value!r}")

    if isinstance(value, str):
        if param.min_length is not None and len(value) < param.min_length:
            errors.append(f"{name!r}: en az {param.min_length} karakter olmalı")
        if param.max_length is not None and len(value) > param.max_length:
            errors.append(f"{name!r}: en fazla {param.max_length} karakter olmalı")
        if param.pattern is not None:
            import re

            if re.search(param.pattern, value) is None:
                errors.append(f"{name!r}: {param.pattern!r} desenine uymuyor")

    if isinstance(value, int | float) and not isinstance(value, bool):
        if param.minimum is not None and value < param.minimum:
            errors.append(f"{name!r}: en az {param.minimum} olmalı, gelen {value}")
        if param.maximum is not None and value > param.maximum:
            errors.append(f"{name!r}: en fazla {param.maximum} olmalı, gelen {value}")

    if isinstance(value, list):
        if param.min_items is not None and len(value) < param.min_items:
            errors.append(f"{name!r}: en az {param.min_items} öğe olmalı")
        if param.max_items is not None and len(value) > param.max_items:
            errors.append(f"{name!r}: en fazla {param.max_items} öğe olmalı")

    return errors


def type_matches(expected: str, value: Any) -> bool:
    """JSON tipi kontrolü.

    ``bool`` Python'da ``int``'in alt sınıfıdır; ``True``'yu geçerli bir
    tamsayı saymak sessiz hatalara yol açar, bu yüzden ayrı ele alınır.
    """
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False
